"""Store-and-forward: watermark durability, oldest-first drain, mid-drain
resume. The ordering matters upstream: the engine drops updates whose
lifetime.fresh is older than the entity's, so a backlog pushed out of order
is a backlog silently lost."""

import datetime

import pytest

import database
from model.entity_builder import StationConfig
from reliability.backlog import BacklogSource
from transport.grpc_wifi import GrpcWifiTransport

STATION = StationConfig(entity_id="test.weather", label="Test Station")


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()


def _insert(ts: str, t=20.0, h=50.0, p=1000.0):
    database.save_reading(t, h, p)
    # save_reading stamps now(); pin the timestamp for deterministic tests
    import sqlite3
    conn = sqlite3.connect(database.DB_PATH)
    rowid = conn.execute("SELECT MAX(id) FROM readings").fetchone()[0]
    conn.execute("UPDATE readings SET timestamp = ? WHERE id = ?", (ts, rowid))
    conn.commit()
    conn.close()
    return rowid


def test_watermark_roundtrip():
    assert database.get_sync_watermark("wifi") is None
    database.set_sync_watermark("wifi", 7)
    assert database.get_sync_watermark("wifi") == 7
    database.set_sync_watermark("wifi", 9)
    assert database.get_sync_watermark("wifi") == 9


def test_readings_after_orders_and_limits():
    ids = [_insert(f"2026-08-30T10:00:{i:02d}") for i in range(5)]
    rows = database.get_readings_after(ids[1], limit=2)
    assert [r[0] for r in rows] == ids[2:4]  # oldest first, capped


def test_first_run_does_not_replay_history():
    _insert("2026-08-30T09:00:00")
    _insert("2026-08-30T09:00:15")
    src = BacklogSource(STATION)
    assert src.pending() == []  # watermark initialized to newest existing


def test_pending_builds_entities_oldest_first():
    src = BacklogSource(STATION)  # watermark at 0 (empty db)
    _insert("2026-08-30T10:00:00", t=21.5)
    _insert("2026-08-30T10:00:15", t=21.6)
    items = src.pending()
    assert len(items) == 2
    temps = [e.metric.metrics[0].double for _, e in items]
    assert temps == [21.5, 21.6]
    # measured_at rides the reading's own time, converted to UTC
    first_dt = items[0][1].metric.metrics[0].measured_at.ToDatetime(
        tzinfo=datetime.timezone.utc)
    local = datetime.datetime.fromisoformat("2026-08-30T10:00:00").astimezone(
        datetime.timezone.utc)
    assert first_dt == local
    # lifetime.fresh advances with the readings -- the engine accepts the
    # sequence only if it is monotonic
    fresh = [e.lifetime.fresh.ToDatetime() for _, e in items]
    assert fresh[0] < fresh[1]


def test_ack_advances_and_drain_resumes():
    src = BacklogSource(STATION)
    r1 = _insert("2026-08-30T10:00:00")
    r2 = _insert("2026-08-30T10:00:15")
    src.ack(r1)
    assert [rid for rid, _ in src.pending()] == [r2]


class _FakeStub:
    def __init__(self, fail_at=None):
        self.pushed = []
        self._fail_at = fail_at

    def Push(self, req, timeout=None):
        if self._fail_at is not None and len(self.pushed) == self._fail_at:
            import grpc

            class _Unavailable(grpc.RpcError):
                def code(self):
                    return "UNAVAILABLE"

            raise _Unavailable()
        self.pushed.append(req.changes[0])


def test_transport_drains_oldest_first_and_resumes_after_failure():
    src = BacklogSource(STATION)
    for i in range(3):
        _insert(f"2026-08-30T10:00:{i * 15:02d}", t=20.0 + i)
    transport = GrpcWifiTransport("localhost:1", backlog=src)
    transport._stub = _FakeStub(fail_at=2)  # third push fails mid-drain

    result = transport.send(entity=None)  # entity ignored when backlog is set
    assert not result.ok
    assert len(transport._stub.pushed) == 2  # first two acked before failure

    transport._stub = _FakeStub()
    result = transport.send(entity=None)
    assert result.ok
    # only the third reading remains -- watermark survived the failure
    assert [e.metric.metrics[0].double for e in transport._stub.pushed] == [22.0]
