"""The only place that decides WiFi vs. BLE vs. both."""

from enum import Enum, auto

from platform_proto.world_pb2 import Entity

from transport.base import Transport, TransportResult


class RouterMode(Enum):
    FAILOVER = auto()   # try transports in order, stop at first success
    BROADCAST = auto()  # send on every available transport


class TransportRouter:
    def __init__(self, transports: list[Transport], mode: RouterMode = RouterMode.FAILOVER):
        self._transports = transports  # order = preference
        self._mode = mode

    def send(self, entity: Entity) -> list[TransportResult]:
        results = []
        for t in self._transports:
            if not t.is_available():
                continue
            result = t.send(entity)
            results.append(result)
            if self._mode is RouterMode.FAILOVER and result.ok:
                break
        return results
