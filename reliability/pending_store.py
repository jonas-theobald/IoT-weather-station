"""Holds the latest unsent Entity, not a FIFO -- Hydris merges metrics by
id with last-write-wins, so only the freshest reading matters."""

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
