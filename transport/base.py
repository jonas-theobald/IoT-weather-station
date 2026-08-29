"""
Transport-agnostic port: everything above this layer only calls
Transport.is_available()/send(entity) and never knows whether the bytes
travel over WiFi, BLE, or anything added later.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from platform_proto.world_pb2 import Entity


class TransportKind(Enum):
    WIFI = auto()
    BLE = auto()


@dataclass
class TransportResult:
    kind: TransportKind
    ok: bool
    detail: str = ""


class Transport(Protocol):
    kind: TransportKind

    def is_available(self) -> bool:
        """Cheap, local check -- a hint for routing, not a guarantee send() will succeed."""
        ...

    def send(self, entity: Entity) -> TransportResult: ...
