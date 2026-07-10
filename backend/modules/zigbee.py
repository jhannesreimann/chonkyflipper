#!/usr/bin/env python3
"""
Zigbee Module - Zigbee2MQTT bridge via local MQTT broker
Communicates with zigbee2mqtt service running on localhost:1883
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime


class ZigbeeModule:
    """Zigbee network management via Zigbee2MQTT over MQTT"""

    BASE_TOPIC = 'zigbee2mqtt'

    def __init__(self, broker='localhost', port=1883):
        self.broker = broker
        self.port = port
        self._client = None
        self._cache = {}
        self._response_events = {}
        self._lock = threading.Lock()
        self._connected = False
        self._connect_event = threading.Event()
        self._event_log = deque(maxlen=200)
        self._last_network_map = None

    # Internal MQTT plumbing

    def _connect(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            return False

        # Client id must be unique per process: gunicorn runs multiple workers,
        # and an MQTT broker kicks any client that reconnects with an id already
        # in use. Two workers sharing 'chonkyflipper-zigbee' flap each other off,
        # so a request published by one worker gets its response delivered to the
        # other, and the original waiter then times out. Per-pid ids keep each
        # worker's subscription stable.
        client = mqtt.Client(client_id=f'chonkyflipper-zigbee-{os.getpid()}')
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        try:
            self._connect_event.clear()
            client.connect(self.broker, self.port, keepalive=30)
            client.loop_start()
            self._client = client
            if not self._connect_event.wait(timeout=3):
                return False
            return True
        except Exception:
            return False

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            client.subscribe(f'{self.BASE_TOPIC}/#')
            self._connect_event.set()

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        self._connect_event.clear()

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            payload = msg.payload.decode()

        with self._lock:
            self._cache[topic] = payload
            if topic in self._response_events:
                self._response_events[topic].set()
            self._record_event(topic, payload)

    def _record_event(self, topic, payload):
        """Append noteworthy MQTT messages to the rolling event log.

        Caller must hold self._lock. Captures two kinds of activity:
        lifecycle events from bridge/event (join/leave/announce/interview)
        and per-device state changes from zigbee2mqtt/<friendly_name>.
        """
        entry = None
        if topic == f'{self.BASE_TOPIC}/bridge/event' and isinstance(payload, dict):
            data = payload.get('data') or {}
            entry = {
                'timestamp': datetime.now().isoformat(),
                'category': 'lifecycle',
                'type': payload.get('type', 'event'),
                'device': data.get('friendly_name') or data.get('ieee_address'),
                'detail': data,
            }
        else:
            # Device state topic is exactly zigbee2mqtt/<name> (2 parts, not a
            # bridge topic). This naturally excludes /availability, /get, /set
            # sub-topics, which have 3+ parts.
            parts = topic.split('/')
            if (len(parts) == 2 and parts[0] == self.BASE_TOPIC
                    and parts[1] != 'bridge' and isinstance(payload, dict)):
                entry = {
                    'timestamp': datetime.now().isoformat(),
                    'category': 'state',
                    'type': 'state_change',
                    'device': parts[1],
                    'detail': payload,
                }
        if entry is not None:
            self._event_log.append(entry)

    def _ensure_connected(self):
        if self._connected:
            return True
        if self._client is not None:
            try:
                self._connect_event.clear()
                self._client.reconnect()
                if not self._connect_event.wait(timeout=2):
                    return False
                return True
            except Exception:
                pass
        return self._connect()

    def _publish_and_wait(self, req_topic, res_topic, payload, timeout=5):
        if not self._ensure_connected():
            return None, 'MQTT broker not available'

        event = threading.Event()
        with self._lock:
            self._response_events[res_topic] = event
            self._cache.pop(res_topic, None)

        self._client.publish(req_topic, json.dumps(payload))
        got_response = event.wait(timeout)

        with self._lock:
            self._response_events.pop(res_topic, None)
            result = self._cache.get(res_topic) if got_response else None

        if not got_response:
            return None, f'Timeout waiting for {res_topic}'
        return result, None

    # Public API

    def get_bridge_info(self):
        if not self._ensure_connected():
            return {'success': False, 'error': 'MQTT broker not available'}
        time.sleep(0.5)
        with self._lock:
            info = self._cache.get(f'{self.BASE_TOPIC}/bridge/info')
            state = self._cache.get(f'{self.BASE_TOPIC}/bridge/state')
        if info is None and state is None:
            return {
                'success': False,
                'error': 'Zigbee2MQTT not responding - is the service running?',
            }
        return {'success': True, 'state': state, 'info': info}


    def get_device_dashboard(self):
        """
        Combined dashboard view: merges the device registry (bridge/devices)
        with each device's live retained state (battery, linkquality/LQI,
        on/off state, availability) cached from its zigbee2mqtt/<name> topic.
        """
        if not self._ensure_connected():
            return {'success': False, 'error': 'MQTT broker not available'}
        time.sleep(0.5)
        with self._lock:
            registry = self._cache.get(f'{self.BASE_TOPIC}/bridge/devices', [])
            cache_snapshot = dict(self._cache)

        if not isinstance(registry, list):
            registry = []

        devices = []
        for dev in registry:
            friendly = dev.get('friendly_name')
            if not friendly:
                continue
            state = cache_snapshot.get(f'{self.BASE_TOPIC}/{friendly}')
            if not isinstance(state, dict):
                state = {}
            definition = dev.get('definition') or {}
            devices.append({
                'friendly_name': friendly,
                'ieee_address': dev.get('ieee_address'),
                'type': dev.get('type'),
                'model': definition.get('model'),
                'vendor': definition.get('vendor'),
                'description': definition.get('description'),
                'power_source': dev.get('power_source'),
                'battery': state.get('battery'),
                'linkquality': state.get('linkquality'),
                'state': state.get('state'),
                'last_seen': state.get('last_seen'),
                'available': self._parse_availability(
                    cache_snapshot.get(f'{self.BASE_TOPIC}/{friendly}/availability')
                ),
            })

        return {'success': True, 'devices': devices}

    @staticmethod
    def _parse_availability(payload):
        """Z2M availability is either a plain 'online'/'offline' string or {'state': 'online'}."""
        if payload is None:
            return None
        if isinstance(payload, dict):
            return payload.get('state') == 'online'
        return str(payload).strip().lower() == 'online'

    def get_event_log(self, limit=50):
        """Return recent network events (join/leave/announce/state), newest first.

        Reads the in-memory rolling buffer. Calls _ensure_connected() first so
        the subscriber is running and future events get captured.
        """
        self._ensure_connected()
        with self._lock:
            events = list(self._event_log)
        total = len(events)
        events.reverse()
        if limit:
            events = events[:limit]
        return {
            'success': True,
            'connected': self._connected,
            'events': events,
            'total': total,
        }

    def get_network_map(self):
        result, error = self._publish_and_wait(
            f'{self.BASE_TOPIC}/bridge/request/networkmap',
            f'{self.BASE_TOPIC}/bridge/response/networkmap',
            {'type': 'raw', 'routes': False}, timeout=40,
        )
        if error:
            # Fall back to the last good map (flagged stale) rather than a bare
            # failure, so a slow build or transient hiccup does not blank the view.
            if self._last_network_map is not None:
                cached = dict(self._last_network_map)
                cached.update({'success': True, 'stale': True})
                return cached
            return {'success': False, 'error': error}

        # Response shape: {data: {type, routes, value: {nodes, links}}, status}
        data = result.get('data') if isinstance(result, dict) else None
        value = data.get('value') if isinstance(data, dict) else None
        if not isinstance(value, dict):
            value = data if isinstance(data, dict) else {}
        nodes = value.get('nodes', []) or []
        links = value.get('links', []) or []
        # Only the coordinator with no links means nothing is paired yet. This
        # is a valid state, not a failure, so flag it for the UI.
        mesh_empty = len(links) == 0 and len(nodes) <= 1

        out = {
            'success': True,
            'map': {'nodes': nodes, 'links': links},
            'nodes': nodes,
            'links': links,
            'mesh_empty': mesh_empty,
            'stale': False,
        }
        self._last_network_map = {
            'map': out['map'], 'nodes': nodes, 'links': links, 'mesh_empty': mesh_empty,
        }
        return out

    def permit_join(self, enable, duration=254):
        payload = {'value': bool(enable), 'time': duration if enable else 0}
        result, error = self._publish_and_wait(
            f'{self.BASE_TOPIC}/bridge/request/permit_join',
            f'{self.BASE_TOPIC}/bridge/response/permit_join',
            payload,
        )
        if error:
            return {'success': False, 'error': error}
        return {'success': True, 'result': result}


    def set_device_state(self, device_name, payload):
        if not self._ensure_connected():
            return {'success': False, 'error': 'MQTT broker not available'}
        self._client.publish(f'{self.BASE_TOPIC}/{device_name}/set', json.dumps(payload))
        time.sleep(0.3)
        with self._lock:
            state = self._cache.get(f'{self.BASE_TOPIC}/{device_name}')
        return {'success': True, 'device': device_name, 'state': state}

    def remove_device(self, device_name):
        payload = {'id': device_name, 'force': False}
        result, error = self._publish_and_wait(
            f'{self.BASE_TOPIC}/bridge/request/device/remove',
            f'{self.BASE_TOPIC}/bridge/response/device/remove',
            payload,
        )
        if error:
            return {'success': False, 'error': error}
        return {'success': True, 'result': result}

    def rename_device(self, from_name, to_name):
        payload = {'from': from_name, 'to': to_name}
        result, error = self._publish_and_wait(
            f'{self.BASE_TOPIC}/bridge/request/device/rename',
            f'{self.BASE_TOPIC}/bridge/response/device/rename',
            payload,
        )
        if error:
            return {'success': False, 'error': error}
        return {'success': True, 'result': result}
