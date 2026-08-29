"""
Non-native transport: BLE GATT has no concept of protobuf, so this
adapter serializes the same Entity to bytes and chunks it across a
custom characteristic. The Pi is the BLE *peripheral* here -- the mirror
image of Hydris's own `airthings` example plugin, which is written to be
the *central* that connects out to a sensor.

STATUS: structural sketch only, not verified end-to-end. Two open
problems, tracked in docs/HYDRIS_INTEGRATION.md Section 10, items 5-7:

  1. There is no hub-side receiver yet. Something has to act as BLE
     central, connect in, reassemble the chunks, and call
     WorldService.Push -- either a Hydris plugin using
     Hydris.bluetooth.requestDevice()/openBLEStream() from inside the
     engine, or a standalone bridge daemon. Without it, this transport
     publishes into the void.
  2. `bluezero`'s peripheral/GATT-server support was not installed or
     exercised in this build pass (deliberately -- see the loop's scope
     note) and Linux BlueZ peripheral mode is known to be less turnkey
     than central/scanning mode. Treat the import and API surface below
     as unverified until tested against a real BlueZ stack on the
     target Pi.

Framing: GATT writes/notifies are capped by the negotiated MTU (as low
as 20 bytes on BLE 4.x, more on 4.2+/5). A serialized weather Entity is
well under 1KB, so a 1-byte "is this the last chunk" flag plus payload
is enough -- no need for anything fancier.
"""

from platform_proto.world_pb2 import Entity

from .base import Transport, TransportKind, TransportResult

SERVICE_UUID = "REPLACE-WITH-PRIVATE-128BIT-UUID"
ENTITY_CHAR_UUID = "REPLACE-WITH-PRIVATE-128BIT-UUID"
CHUNK_SIZE = 180  # conservative default; negotiate up via MTU exchange if the central supports it


class BleGattTransport:
    kind = TransportKind.BLE

    def __init__(self, adapter_address: str, device_name: str):
        # [unverified] see module docstring, item 2.
        from bluezero import peripheral

        self._peripheral = peripheral.Peripheral(adapter_address, local_name=device_name)
        self._peripheral.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)
        self._peripheral.add_characteristic(
            srv_id=1, chr_id=1, uuid=ENTITY_CHAR_UUID,
            value=[], notifying=False, flags=["read", "notify"],
        )
        self._published = False

    def is_available(self) -> bool:
        # Unlike WiFi, BLE peripheral mode has no local "am I associated"
        # signal -- success really means "a central is connected and
        # subscribed," which this adapter can't verify before sending.
        # Optimistic stub, not a real health check (open item #6).
        return True

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
