"""Sync API: watermark init-to-newest, UTC timestamps on the wire, ack."""

import pytest

import database


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()


@pytest.fixture()
def client():
    from web_server import app
    return app.test_client()


def test_pending_initializes_to_newest_and_acks(client):
    database.save_reading(20.0, 50.0, 1000.0)
    body = client.get("/api/sync/pending?name=usb").get_json()
    assert body["readings"] == []  # first contact never replays history
    first = body["watermark"]

    database.save_reading(21.0, 51.0, 1001.0)
    body = client.get("/api/sync/pending?name=usb").get_json()
    assert len(body["readings"]) == 1
    r = body["readings"][0]
    assert r["temperature"] == 21.0
    assert r["timestamp"].endswith("+00:00")  # wire speaks UTC

    resp = client.post("/api/sync/ack", json={"name": "usb", "last_id": r["id"]})
    assert resp.get_json()["watermark"] == r["id"]
    assert client.get("/api/sync/pending?name=usb").get_json()["readings"] == []
    assert first < r["id"]


def test_ack_rejects_garbage(client):
    assert client.post("/api/sync/ack", json={"name": "usb"}).status_code == 400
