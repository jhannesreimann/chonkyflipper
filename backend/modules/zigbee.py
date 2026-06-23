#!/usr/bin/env python3
"""
Zigbee Module - Zigbee2MQTT bridge via local MQTT broker
Communicates with zigbee2mqtt service running on localhost:1883
"""

import json
import threading
import time


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

    # ------------------------------------------------------------------
    # Internal MQTT plumbing
    # ------------------------------------------------------------------

    def _connect(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            return False

        client = mqtt.Client(client_id='chonkyflipper-zigbee')
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

    def get_devices(self):
        if not self._ensure_connected():
            return {'success': False, 'error': 'MQTT broker not available'}
        time.sleep(0.5)
        with self._lock:
            devices = self._cache.get(f'{self.BASE_TOPIC}/bridge/devices', [])
        return {
            'success': True,
            'devices': devices if isinstance(devices, list) else [],
        }

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

    def get_network_map(self):
        result, error = self._publish_and_wait(
            f'{self.BASE_TOPIC}/bridge/request/networkmap',
            f'{self.BASE_TOPIC}/bridge/response/networkmap',
            {'type': 'raw', 'routes': False}, timeout=15,
        )
        if error:
            return {'success': False, 'error': error}
        return {'success': True, 'map': result.get('data') if isinstance(result, dict) else result}

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

    def get_device_state(self, device_name):
        if not self._ensure_connected():
            return {'success': False, 'error': 'MQTT broker not available'}
        self._client.publish(f'{self.BASE_TOPIC}/{device_name}/get', json.dumps({'state': ''}))
        time.sleep(0.5)
        with self._lock:
            state = self._cache.get(f'{self.BASE_TOPIC}/{device_name}')
        return {'success': True, 'device': device_name, 'state': state}

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
