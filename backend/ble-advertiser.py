#!/usr/bin/env python3
"""
Standalone BLE advertiser. Registers a single LEAdvertisement1 object with
BlueZ and broadcasts it until killed (SIGTERM) or the duration elapses.

Run by the backend as a detached subprocess (see BluetoothModule.spoof_*).
Config is passed as a JSON string argv[1]:

    {
      "adapter": "hci0", "duration": 60, "type": "broadcast|peripheral",
      "name": "Fake", "service_uuids": ["feaa"],
      "manufacturer_data": {"76": "0215..."},   # company id -> hex
      "service_data": {"0000feaa-...": "10..."}, # uuid -> hex
      "include_tx_power": true
    }
"""

import asyncio
import json
import signal
import sys

from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method, dbus_property
from dbus_fast import BusType, Variant, PropertyAccess

BLUEZ = 'org.bluez'
ADV_PATH = '/org/chonky/advertisement0'


class Advertisement(ServiceInterface):
    def __init__(self, cfg):
        super().__init__('org.bluez.LEAdvertisement1')
        self._type = cfg.get('type', 'peripheral')
        self._name = cfg.get('name') or ''
        self._uuids = cfg.get('service_uuids') or []
        self._mfg = {
            int(k): Variant('ay', bytes.fromhex(v))
            for k, v in (cfg.get('manufacturer_data') or {}).items()
        }
        self._sdata = {
            k: Variant('ay', bytes.fromhex(v))
            for k, v in (cfg.get('service_data') or {}).items()
        }
        self._tx = bool(cfg.get('include_tx_power'))

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> 's':
        return self._type

    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> 's':
        return self._name

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> 'as':
        return self._uuids

    @dbus_property(access=PropertyAccess.READ)
    def ManufacturerData(self) -> 'a{qv}':
        return self._mfg

    @dbus_property(access=PropertyAccess.READ)
    def ServiceData(self) -> 'a{sv}':
        return self._sdata

    @dbus_property(access=PropertyAccess.READ)
    def IncludeTxPower(self) -> 'b':
        return self._tx

    @method()
    def Release(self):
        pass


async def main():
    cfg = json.loads(sys.argv[1])
    adapter = cfg.get('adapter', 'hci0')
    duration = int(cfg.get('duration', 60))

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    intro = await bus.introspect(BLUEZ, f'/org/bluez/{adapter}')
    obj = bus.get_proxy_object(BLUEZ, f'/org/bluez/{adapter}', intro)

    try:
        await obj.get_interface('org.bluez.Adapter1').set_powered(True)
    except Exception:
        pass

    adv_mgr = obj.get_interface('org.bluez.LEAdvertisingManager1')
    adv = Advertisement(cfg)
    bus.export(ADV_PATH, adv)
    await adv_mgr.call_register_advertisement(ADV_PATH, {})

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        await asyncio.wait_for(stop.wait(), timeout=duration)
    except asyncio.TimeoutError:
        pass
    finally:
        try:
            await adv_mgr.call_unregister_advertisement(ADV_PATH)
        except Exception:
            pass
        bus.unexport(ADV_PATH)


if __name__ == '__main__':
    asyncio.run(main())
