"""BLE peripheral transport: exposes the current reading as a GATT server.

Unlike the WiFi adapter this doesn't move serialized Entity bytes -- a full
protobuf Entity needs chunking below the default 23-byte MTU, and the hub
side (a Hydris plugin) has no protobuf runtime on its BLE path anyway.
Instead the values travel as standard Environmental Sensing Service
characteristics (single-MTU, readable by any BLE tool), plus DIS for
identity and one custom service the hub's discovery filters on. send()
stays Entity-in like every transport; the mapping back out of the Entity
happens here and nowhere else. See docs/HYDRIS_INTEGRATION.md.
"""

from __future__ import annotations

import json
import struct
import threading

from platform_proto import metrics_pb2
from platform_proto.world_pb2 import Entity

from model.entity_builder import StationConfig

from .base import Transport, TransportKind, TransportResult

# Discovery anchor: the Hydris engine's scanner records advertised service
# UUIDs on ble.device.* entities and the plugin filters on this one. Must
# stay in sync with the hub-side plugin. Generated once, never rotate.
STATION_SERVICE_UUID = "eef67fbe-b177-4705-857f-6a475536a66f"
STATION_META_CHAR_UUID = "7b264d39-5415-43fa-afa7-fd1f7972387b"

# Bluetooth SIG assigned numbers (16-bit, full 128-bit form for BlueZ).
ESS_SERVICE_UUID = "0000181a-0000-1000-8000-00805f9b34fb"
TEMPERATURE_CHAR_UUID = "00002a6e-0000-1000-8000-00805f9b34fb"  # sint16, 0.01 degC
HUMIDITY_CHAR_UUID = "00002a6f-0000-1000-8000-00805f9b34fb"     # uint16, 0.01 %
PRESSURE_CHAR_UUID = "00002a6d-0000-1000-8000-00805f9b34fb"     # uint32, 0.1 Pa
DIS_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
DIS_MANUFACTURER_CHAR_UUID = "00002a29-0000-1000-8000-00805f9b34fb"
DIS_MODEL_CHAR_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
DIS_SERIAL_CHAR_UUID = "00002a25-0000-1000-8000-00805f9b34fb"
DIS_FIRMWARE_CHAR_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

DIS_MANUFACTURER = "jonas-theobald"
DIS_MODEL = "IoT-weather-station BME280"
DIS_FIRMWARE = "1.0.0"

# ESS "value is not known" sentinels (GATT spec, per characteristic).
_TEMPERATURE_UNKNOWN = struct.pack("<h", -32768)
_HUMIDITY_UNKNOWN = struct.pack("<H", 0xFFFF)
_PRESSURE_UNKNOWN = struct.pack("<I", 0xFFFFFFFF)


def encode_temperature(celsius: float) -> bytes:
    return struct.pack("<h", round(celsius * 100))


def encode_humidity(percent: float) -> bytes:
    return struct.pack("<H", round(percent * 100))


def encode_pressure(hpa: float) -> bytes:
    return struct.pack("<I", round(hpa * 1000))  # 1 hPa = 1000 * 0.1 Pa


def encode_from_entity(entity: Entity) -> dict[str, bytes]:
    """Entity -> {char uuid: ESS-encoded value}; the only Entity-aware bit."""
    encoders = {
        metrics_pb2.MetricKindTemperature: (TEMPERATURE_CHAR_UUID, encode_temperature),
        metrics_pb2.MetricKindHumidity: (HUMIDITY_CHAR_UUID, encode_humidity),
        metrics_pb2.MetricKindPressure: (PRESSURE_CHAR_UUID, encode_pressure),
    }
    out = {}
    for metric in entity.metric.metrics:
        if metric.kind in encoders:
            uuid, encode = encoders[metric.kind]
            out[uuid] = encode(metric.double)
    return out


def station_metadata(station: StationConfig) -> bytes:
    """Read-once JSON so the hub needs no per-station config of its own."""
    return json.dumps(
        {
            "v": 1,
            "id": station.entity_id,
            "label": station.label,
            "lat": station.lat,
            "lon": station.lon,
            "alt": station.alt,
        },
        separators=(",", ":"),
    ).encode()


def device_serial() -> str:
    """Pi SoC serial -- the hub keys entity identity on this (DIS 2A25),
    so it must survive reboots and BLE address changes."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    import uuid

    return f"{uuid.getnode():012x}"  # non-Pi fallback: MAC as hex


class BleGattTransport:
    kind = TransportKind.BLE

    def __init__(self, station: StationConfig, adapter_address: str | None = None,
                 device_name: str = "hydris-weather"):
        from bluezero import adapter, peripheral  # import here: BlueZ-only dependency

        if adapter_address is None:
            adapter_address = list(adapter.Adapter.available())[0].address

        self._values = {
            TEMPERATURE_CHAR_UUID: _TEMPERATURE_UNKNOWN,
            HUMIDITY_CHAR_UUID: _HUMIDITY_UNKNOWN,
            PRESSURE_CHAR_UUID: _PRESSURE_UNKNOWN,
        }
        self._char_index: dict[str, int] = {}  # uuid -> position in peripheral.characteristics
        meta = station_metadata(station)

        self._peripheral = peripheral.Peripheral(adapter_address, local_name=device_name)

        # Station service first: bluezero advertises primary services in
        # order, and this 128-bit UUID is the one discovery must see.
        self._add_service(1, STATION_SERVICE_UUID)
        self._add_char(1, 1, STATION_META_CHAR_UUID, ["read"], lambda: list(meta))

        self._add_service(2, ESS_SERVICE_UUID)
        for chr_id, uuid in enumerate(
            (TEMPERATURE_CHAR_UUID, HUMIDITY_CHAR_UUID, PRESSURE_CHAR_UUID), start=1
        ):
            self._add_char(2, chr_id, uuid, ["read", "notify"],
                           lambda u=uuid: list(self._values[u]))

        serial = device_serial()
        self._add_service(3, DIS_SERVICE_UUID)
        for chr_id, (uuid, value) in enumerate(
            (
                (DIS_MANUFACTURER_CHAR_UUID, DIS_MANUFACTURER),
                (DIS_MODEL_CHAR_UUID, DIS_MODEL),
                (DIS_SERIAL_CHAR_UUID, serial),
                (DIS_FIRMWARE_CHAR_UUID, DIS_FIRMWARE),
            ),
            start=1,
        ):
            self._add_char(3, chr_id, uuid, ["read"], lambda v=value: list(v.encode()))

        # publish() runs the GLib mainloop and never returns -- it owns
        # advertising and all D-Bus traffic. Everything after this point
        # must reach BlueZ via GLib.idle_add, never directly.
        self._thread = threading.Thread(
            target=self._peripheral.publish, name="ble-gatt", daemon=True
        )
        self._thread.start()

    def _add_service(self, srv_id: int, uuid: str) -> None:
        self._peripheral.add_service(srv_id=srv_id, uuid=uuid, primary=True)

    def _add_char(self, srv_id: int, chr_id: int, uuid: str, flags: list[str],
                  read_callback) -> None:
        self._peripheral.add_characteristic(
            srv_id=srv_id, chr_id=chr_id, uuid=uuid, value=[],
            notifying=False, flags=flags, read_callback=read_callback,
        )
        self._char_index[uuid] = len(self._char_index)

    def is_available(self) -> bool:
        return self._thread.is_alive()

    def send(self, entity: Entity) -> TransportResult:
        updates = encode_from_entity(entity)
        if not updates:
            return TransportResult(self.kind, False, "entity carries no ESS-mappable metric")
        self._values.update(updates)
        try:
            from gi.repository import GLib

            GLib.idle_add(self._apply, updates)
            return TransportResult(self.kind, True)
        except Exception as e:  # BlueZ D-Bus errors aren't a narrow, well-known type
            return TransportResult(self.kind, False, str(e))

    def _apply(self, updates: dict[str, bytes]) -> bool:
        # Mainloop thread. set_value on a notifying characteristic is what
        # emits the PropertiesChanged the subscribed hub receives.
        for uuid, value in updates.items():
            self._peripheral.characteristics[self._char_index[uuid]].set_value(list(value))
        return False  # one-shot idle callback
