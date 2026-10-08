"""The relay wrapper: a socketIO outage must never reach the caller."""

import pytest

from rmn_common.relay import BestEffortRelay


class FakeClient:
    """Stands in for ``socketio.Client``: what the relay uses of one."""

    def __init__(self, emit_error=None):
        self.connected = True
        self.sent = []
        self.disconnected = 0
        self._emit_error = emit_error

    def emit(self, event, data):
        if self._emit_error:
            raise self._emit_error
        self.sent.append((event, data))

    def disconnect(self):
        self.disconnected += 1
        self.connected = False


def refusing():
    raise ConnectionError("Connection refused")


def test_it_connects_once_and_reuses_the_client():
    built = []

    def connect():
        client = FakeClient()
        built.append(client)
        return client

    relay = BestEffortRelay(connect)
    assert relay.emit("job_status", "{}") is True
    assert relay.emit("job_status", "{}") is True
    assert len(built) == 1
    assert built[0].sent == [("job_status", "{}"), ("job_status", "{}")]


def test_a_relay_that_is_down_drops_the_event_instead_of_raising(capsys):
    relay = BestEffortRelay(refusing)
    assert relay.connect() is False
    assert relay.connected is False
    assert relay.emit("job_status", "{}") is False
    out = capsys.readouterr().out
    assert "relay unreachable" in out


def test_a_down_relay_is_retried_once_per_cooldown(monkeypatch):
    """Every request emits: a down relay must not mean a connection each time."""
    attempts = []

    def connect():
        attempts.append(1)
        refusing()

    now = {"t": 1000.0}
    monkeypatch.setattr("rmn_common.relay.time.monotonic", lambda: now["t"])

    relay = BestEffortRelay(connect)
    relay.emit("a", "{}")
    relay.emit("b", "{}")
    relay.emit("c", "{}")
    assert len(attempts) == 1  # the cooldown swallowed the other two

    now["t"] += BestEffortRelay.RETRY_COOLDOWN + 0.1
    relay.emit("d", "{}")
    assert len(attempts) == 2


def test_it_reconnects_once_the_relay_is_back(monkeypatch):
    up = {"value": False}
    built = []

    def connect():
        if not up["value"]:
            refusing()
        client = FakeClient()
        built.append(client)
        return client

    monkeypatch.setattr(BestEffortRelay, "RETRY_COOLDOWN", 0)
    relay = BestEffortRelay(connect)
    assert relay.emit("job_status", "{}") is False

    up["value"] = True
    assert relay.emit("job_status", "{}") is True
    assert built[0].sent == [("job_status", "{}")]


def test_a_client_that_dropped_is_replaced(monkeypatch):
    built = []

    def connect():
        client = FakeClient()
        built.append(client)
        return client

    monkeypatch.setattr(BestEffortRelay, "RETRY_COOLDOWN", 0)
    relay = BestEffortRelay(connect)
    assert relay.emit("one", "{}") is True
    built[0].connected = False  # the relay restarted under us

    assert relay.emit("two", "{}") is True
    assert len(built) == 2
    assert built[0].disconnected == 1  # the dead client was dropped
    assert built[1].sent == [("two", "{}")]


def test_an_emit_that_fails_drops_the_client(capsys, monkeypatch):
    built = []

    def connect():
        client = FakeClient(emit_error=RuntimeError("/ is not a connected namespace"))
        built.append(client)
        return client

    monkeypatch.setattr(BestEffortRelay, "RETRY_COOLDOWN", 0)
    relay = BestEffortRelay(connect)
    assert relay.emit("job_status", "{}") is False
    assert "not a connected namespace" in capsys.readouterr().out
    assert relay.connected is False  # dropped, so the next emit reconnects


def test_disconnect_is_safe_before_and_after_connecting():
    relay = BestEffortRelay(refusing)
    relay.disconnect()  # nothing connected yet

    class Stubborn(FakeClient):
        def disconnect(self):
            raise RuntimeError("already gone")

    relay = BestEffortRelay(Stubborn)
    assert relay.emit("job_status", "{}") is True
    relay.disconnect()  # the error is swallowed
    assert relay.connected is False


@pytest.mark.parametrize("event", ["job_status", "document_ready"])
def test_the_payload_is_passed_through_untouched(event):
    relay = BestEffortRelay(FakeClient)
    assert relay.emit(event, '{"job_id": "j"}') is True
    assert relay._client.sent == [(event, '{"job_id": "j"}')]
