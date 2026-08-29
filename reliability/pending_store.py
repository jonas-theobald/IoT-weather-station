"""
Because Hydris merges the metric component additively by metric id with
last-write-wins per id (Developer Guide -> Entity Merge & Synchronization),
there's no value in queueing every failed reading -- only the freshest
value per metric matters. This is intentionally the latest unsent Entity,
not a FIFO of history.

Named `reliability/`, not `queue/`: a top-level `queue/` package would
shadow Python's stdlib `queue` module for the whole process once the repo
root is on sys.path (confirmed while building this -- grpcio imports
`queue` internally, and the stdlib module becomes unreachable the moment
a local `queue/` directory sits earlier on the path).
"""

from __future__ import annotations  # `Entity | None` needs this on Python < 3.10 (e.g. Pi OS Bullseye's 3.9)

from platform_proto.world_pb2 import Entity


class PendingEntityStore:
    def __init__(self):
        self._pending: Entity | None = None

    def stash(self, entity: Entity) -> None:
        self._pending = entity

    def clear(self) -> None:
        self._pending = None

    def pending(self) -> Entity | None:
        return self._pending
