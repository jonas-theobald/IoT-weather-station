"""BLE peripheral transport: chunks the serialized Entity across a GATT
characteristic (MTU-limited, unlike a network packet). Structural sketch,
not verified end-to-end -- no hub-side BLE central exists yet to receive
this, and bluezero's peripheral mode hasn't been tested against real
BlueZ. See docs/HYDRIS_INTEGRATION.md."""

from platform_proto.world_pb2 import Entity

from .base import Transport, TransportKind, TransportResult

SERVICE_UUID = "REPLACE-WITH-PRIVATE-128BIT-UUID"
ENTITY_CHAR_UUID = "REPLACE-WITH-PRIVATE-128BIT-UUID"
CHUNK_SIZE = 180  # conservative default; negotiate up via MTU exchange if the central supports it


class BleGattTransport:
    kind = TransportKind.BLE

    def __init__(self, adapter_address: str, device_name: str):
        from bluezero import peripheral  # unverified against a real BlueZ stack

        self._peripheral = peripheral.Peripheral(adapter_address, local_name=device_name)
        self._peripheral.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)
        self._peripheral.add_characteristic(
            srv_id=1, chr_id=1, uuid=ENTITY_CHAR_UUID,
            value=[], notifying=False, flags=["read", "notify"],
        )
        self._published = False

    def is_available(self) -> bool:
        return True  # stub -- BLE peripheral mode has no local "am I associated" signal

    def send(self, entity: Entity) -> TransportResult:
        payload = entity.SerializeToString()
        chunks = [payload[i:i + CHUNK_SIZE] for i in range(0, len(payload), CHUNK_SIZE)] or [b""]
        try:
            for i, chunk in enumerate(chunks):
                framed = bytes([1 if i == len(chunks) - 1 else 0]) + chunk
                self._peripheral.characteristics[0].set_value(list(framed))
                if not self._published:
                    self._peripheral.publish()
                    self._published = True
            return TransportResult(self.kind, True)
        except Exception as e:  # BlueZ D-Bus errors aren't a narrow, well-known type
            return TransportResult(self.kind, False, str(e))
