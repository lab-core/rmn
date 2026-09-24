"""End-to-end through Flask-SocketIO's test client: who can push, who receives."""

import json

import pytest

import app as app_module
from conftest import SERVICE_TOKEN


@pytest.fixture
def alice_job(db, make_token):
    make_token("alice")
    make_token("bob")
    db["eval_jobs"].insert_one({"job_id": "job", "user_id": "alice"})
    db["template"].insert_one({"template_id": "tpl", "user_id": "alice"})


def _names(client):
    return [event["name"] for event in client.get_received()]


def test_service_job_status_reaches_the_user_room(connect, alice_job):
    alice = connect({"token": "tok-alice", "user_id": "alice"})
    assert alice.is_connected()
    alice.emit("join", "alice")
    alice.get_received()

    service = connect({"service_token": SERVICE_TOKEN})
    payload = json.dumps({"user_id": "alice", "job_id": "job", "status": "RUN"})
    service.emit("job_status", payload)

    received = alice.get_received()
    assert [e["name"] for e in received] == ["job_status"]
    assert received[0]["args"] == [payload]


def test_job_status_also_reaches_the_job_room(connect, alice_job):
    alice = connect({"token": "tok-alice"})
    alice.emit("join", "job")
    alice.get_received()
    service = connect({"service_token": SERVICE_TOKEN})
    service.emit("job_status", json.dumps({"user_id": "alice", "job_id": "job", "status": "RUN"}))
    assert _names(alice) == ["job_status"]


@pytest.mark.parametrize(
    "event,room,payload",
    [
        ("document_ready", "job", {"job_id": "job", "document_index": 0}),
        ("doc_validated", "job", {"job_id": "job", "document_index": 0}),
        ("template_rendered", "tpl", {"template_id": "tpl"}),
    ],
)
def test_room_scoped_events(connect, alice_job, event, room, payload):
    alice = connect({"token": "tok-alice"})
    alice.emit("join", room)
    bystander = connect({"token": "tok-bob"})
    bystander.emit("join", "bob")
    alice.get_received()
    bystander.get_received()

    service = connect({"service_token": SERVICE_TOKEN})
    service.emit(event, json.dumps(payload))

    assert _names(alice) == [event]
    assert _names(bystander) == []


def test_only_the_service_can_push(connect, alice_job):
    alice = connect({"token": "tok-alice"})
    alice.emit("join", "job")
    alice.get_received()

    bob = connect({"token": "tok-bob"})
    bob.emit("job_status", json.dumps({"user_id": "alice", "job_id": "job", "status": "ERROR"}))
    bob.emit("document_ready", json.dumps({"job_id": "job"}))
    bob.emit("template_rendered", json.dumps({"template_id": "job"}))
    share = connect({"share_token": "unknown"})
    share.emit("doc_validated", json.dumps({"job_id": "job"}))

    assert _names(alice) == []


def test_join_is_denied_without_rights(connect, alice_job):
    bob = connect({"token": "tok-bob"})
    bob.emit("join", "job")  # alice's job
    bob.get_received()

    service = connect({"service_token": SERVICE_TOKEN})
    service.emit("document_ready", json.dumps({"job_id": "job"}))
    service.emit("job_status", json.dumps({"user_id": "alice", "job_id": "job", "status": "RUN"}))

    assert _names(bob) == []


def test_anonymous_connections_are_refused(connect, alice_job):
    # no credential, an expired token, an unknown share token: refused at the
    # handshake instead of kept as a dead socket
    assert not connect({}).is_connected()
    assert not connect({"token": "nope"}).is_connected()
    assert connect({"share_token": "unknown"}).is_connected()  # a share role, checked at join
    assert app_module.connections == {} or all(c["role"] != "anonymous" for c in app_module.connections.values())


def test_share_token_receives_the_shared_job(connect, db):
    db["eval_jobs"].insert_one({"job_id": "job", "user_id": "alice", "share_token": {"questions": "s1"}})
    viewer = connect({"share_token": "s1"})
    viewer.emit("join", "job")
    viewer.get_received()

    service = connect({"service_token": SERVICE_TOKEN})
    service.emit("doc_validated", json.dumps({"job_id": "job"}))
    assert _names(viewer) == ["doc_validated"]


def test_leave_stops_delivery(connect, alice_job):
    alice = connect({"token": "tok-alice"})
    alice.emit("join", "job")
    alice.emit("leave", "job")
    alice.emit("leave", None)  # ignored, must not raise
    alice.get_received()

    service = connect({"service_token": SERVICE_TOKEN})
    service.emit("document_ready", json.dumps({"job_id": "job"}))
    assert _names(alice) == []


def test_connection_is_rejected_when_identification_fails(connect, monkeypatch):
    def boom(auth):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(app_module, "identify", boom)
    client = connect({"token": "tok-alice"})
    assert not client.is_connected()
    assert app_module.connections == {}


def test_join_failure_is_swallowed(connect, alice_job, monkeypatch):
    alice = connect({"token": "tok-alice"})

    def boom(identity, room):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(app_module, "can_join", boom)
    alice.emit("join", "job")  # must not raise or disconnect
    assert alice.is_connected()


def test_disconnect_forgets_the_connection(connect):
    client = connect({"service_token": SERVICE_TOKEN})
    assert [c["role"] for c in app_module.connections.values()] == ["service"]
    client.disconnect()
    assert app_module.connections == {}
