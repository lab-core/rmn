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
        def connect(self, url, auth):
            connected.append((url, auth))

    monkeypatch.setattr(fresh.socketio, "Client", FakeClient)
    assert isinstance(fresh.socketio_client(), FakeClient)
    assert connected == [("http://localhost:7000", {"service_token": "svc"})]
