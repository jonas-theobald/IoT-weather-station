"""Store-and-forward for the WiFi/gRPC path: SQLite is the source of truth,
this replays whatever the hub hasn't acked yet.

The watermark is the last acked reading rowid, durable in sync_state -- a
crashed pusher resumes where it left off, and a lost ack at worst re-pushes
one reading (idempotent: same metric ids, same measured_at).

Ordering is load-bearing: the engine ignores updates whose lifetime.fresh is
older than what the entity already has, so the backlog MUST drain oldest
first, and the live reading is simply the newest backlog item -- never push
"now" ahead of the gap or the whole gap gets silently dropped.

First run initializes the watermark to the newest existing reading: the
feature syncs gaps from then on, it does not replay months of pre-feature
history into the hub.
"""

from __future__ import annotations

import datetime

import database
from model.entity_builder import StationConfig, build_weather_entity

DEFAULT_BATCH_LIMIT = 500  # per drain call; keeps a huge gap from blocking the loop


def _parse_db_timestamp(ts: str) -> datetime.datetime:
    # readings.timestamp is naive local time (datetime.now().isoformat());
    # interpret as local, convert to aware UTC for measured_at.
    return datetime.datetime.fromisoformat(ts).astimezone(datetime.timezone.utc)


class BacklogSource:
    def __init__(self, station: StationConfig, name: str = "wifi",
                 batch_limit: int = DEFAULT_BATCH_LIMIT):
        self._station = station
        self._name = name
        self._batch_limit = batch_limit
        if database.get_sync_watermark(name) is None:
            database.set_sync_watermark(name, database.get_max_reading_id())

    def pending(self):
        """Unacked readings as (rowid, Entity), oldest first, batch-limited."""
        last = database.get_sync_watermark(self._name)
        out = []
        for rid, ts, temperature, humidity, pressure in database.get_readings_after(
            last, self._batch_limit
        ):
            reading = {
                "temperature_c": temperature,
                "humidity_percent": humidity,
                "pressure_hpa": pressure,
            }
            out.append((rid, build_weather_entity(
                reading, self._station, _parse_db_timestamp(ts))))
        return out

    def ack(self, rowid: int) -> None:
        database.set_sync_watermark(self._name, rowid)
