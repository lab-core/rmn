"""The client factories: Mongo and the socket server fail closed without secrets."""

import importlib.util

import pytest

import utils.clients as clients


def test_mongo_url_requires_credentials(monkeypatch):
    # the defaults were adminuser / example: a missing variable connected with
    # the sample password instead of failing
    monkeypatch.delenv("MONGODB_USER", raising=False)
    monkeypatch.delenv("MONGODB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        clients.mongo_url()
    monkeypatch.setenv("MONGODB_USER", "u")
    monkeypatch.setenv("MONGODB_PASSWORD", "p")
    assert clients.mongo_url().startswith("mongodb://u:p@")


# conftest swaps the factories of ``utils.clients`` for in-memory doubles, so
# the real ones are exercised on a fresh copy of the module
@pytest.fixture
def fresh():
    spec = importlib.util.spec_from_file_location("fresh_clients", clients.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mongo_client_connects_with_the_credentials(fresh, monkeypatch):
    monkeypatch.setenv("MONGODB_USER", "u")
    monkeypatch.setenv("MONGODB_PASSWORD", "p")
    monkeypatch.setattr(fresh, "MongoClient", lambda url: ("client", url))
    assert fresh.mongo_client() == ("client", fresh.mongo_url())


def test_redis_client_is_authenticated_only_when_a_password_is_set(fresh, monkeypatch):
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    client = fresh.redis_client(socket_timeout=2)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["password"] is None and kwargs["socket_timeout"] == 2
    monkeypatch.setenv("REDIS_PASSWORD", "secret")
    assert (
        fresh.redis_client().connection_pool.connection_kwargs["password"] == "secret"
    )


def test_socketio_token_is_mandatory_in_production(fresh, monkeypatch, capsys):
    monkeypatch.delenv("SOCKETIO_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError):
        fresh.socketio_service_token()
    # elsewhere it only warns: the events would be dropped, nothing else
    monkeypatch.setenv("ENVIRONMENT", "test")
    assert fresh.socketio_service_token() is None
    assert "SOCKETIO_SERVICE_TOKEN is not set" in capsys.readouterr().out


def test_socketio_client_authenticates_as_the_backend(fresh, monkeypatch):
    monkeypatch.setenv("SOCKETIO_SERVICE_TOKEN", "svc")
    connected = []

    class FakeClient:
        connected = True

        def connect(self, url, auth):
            connected.append((url, auth))

    monkeypatch.setattr(fresh.socketio, "Client", FakeClient)
    relay = fresh.socketio_client()
    assert relay.connected
    assert connected == [("http://localhost:7000", {"service_token": "svc"})]


def test_a_relay_that_is_down_does_not_reach_the_caller(fresh, monkeypatch, capsys):
    """A socketIO outage must not 500 the route that emitted."""
    monkeypatch.setenv("SOCKETIO_SERVICE_TOKEN", "svc")

    class RefusingClient:
        connected = False

        def connect(self, url, auth):
            raise ConnectionError("Connection refused")

    monkeypatch.setattr(fresh.socketio, "Client", RefusingClient)
    relay = fresh.socketio_client()  # start-up must survive it
    assert relay.connected is False
    assert relay.emit("job_status", "{}") is False
    out = capsys.readouterr().out
    assert "relay unreachable" in out


def test_job_questions_is_indexed_by_job(app_module_fixture):
    """Every job_questions query starts with job_id; none of them had an index.

    A job of 6041 documents was a 141 ms COLLSCAN in Mongo's slow query log.
    """
    from service.indexes import ensure_job_question_indexes

    db = app_module_fixture.mongo["RMN"]
    ensure_job_question_indexes(db)
    indexes = db["job_questions"].index_information()
    assert [("job_id", 1), ("document_index", 1)] == indexes["job_document"]["key"]
    assert [("job_id", 1), ("question_index", 1)] == indexes["job_question"]["key"]
