"""Configuration parsing and token expiry."""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

import app as app_module
from app import _origins, token_expired


def test_origins_expand_bare_hosts_to_both_schemes():
    assert _origins("rmn.example.ca, https://x.y,,http://z") == [
        "https://rmn.example.ca",
        "http://rmn.example.ca",
        "https://x.y",
        "http://z",
    ]
    assert _origins("") == []


def test_wildcard_cors_is_kept_as_is():
    assert app_module.cors_allowed_origins == "*"


def test_token_expiry_rules(monkeypatch):
    now = dt.datetime.now(dt.UTC)
    assert token_expired({}) is True  # legacy token without a timestamp
    assert token_expired({"creation_time": now}) is False
    assert token_expired({"creation_time": now - dt.timedelta(days=31)}) is True
    # pymongo hands back naive UTC datetimes
    assert token_expired({"creation_time": (now - dt.timedelta(days=31)).replace(tzinfo=None)}) is True
    assert token_expired({"creation_time": (now - dt.timedelta(days=1)).replace(tzinfo=None)}) is False

    monkeypatch.setattr(app_module, "TOKEN_TTL_DAYS", 0)
    assert token_expired({}) is False
    assert token_expired({"creation_time": now - dt.timedelta(days=400)}) is False


def _load_app(monkeypatch, **env):
    """Import app.py afresh, as a separate module, under ``env``.

    The configuration is read at import time; the module the other tests use
    is left alone (conftest already swapped pymongo for mongomock, so a second
    import is cheap and offline).
    """
    for name in ("ENVIRONMENT", "SOCKETIO_SERVICE_TOKEN", "MONGODB_USER", "MONGODB_PASSWORD",
                 "SOCKETIO_CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("app_under_test", Path(app_module.__file__))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_refuses_to_start_without_the_service_token(monkeypatch):
    # without it the backend can never authenticate: every notification
    # would be dropped and the real-time updates would silently stop
    with pytest.raises(RuntimeError, match="SOCKETIO_SERVICE_TOKEN"):
        _load_app(monkeypatch, ENVIRONMENT="production", MONGODB_USER="u", MONGODB_PASSWORD="p")


def test_development_starts_without_the_service_token_but_says_so(monkeypatch, capsys):
    module = _load_app(monkeypatch, ENVIRONMENT="development")
    assert "SOCKETIO_SERVICE_TOKEN is not set" in capsys.readouterr().out
    assert module.SERVICE_TOKEN is None


def test_production_refuses_to_start_without_mongo_credentials(monkeypatch):
    with pytest.raises(RuntimeError, match="MONGODB_USER and MONGODB_PASSWORD"):
        _load_app(monkeypatch, ENVIRONMENT="production", SOCKETIO_SERVICE_TOKEN="svc")


def test_production_uses_the_cluster_mongo_and_the_configured_origins(monkeypatch):
    module = _load_app(monkeypatch, ENVIRONMENT="production", SOCKETIO_SERVICE_TOKEN="svc",
                       MONGODB_USER="u", MONGODB_PASSWORD="p", SOCKETIO_CORS_ORIGINS="rmn.example.ca")
    assert module.mongodb_host == "mongo"
    # the configured host comes first; the relay's own in-cluster names follow
    # it, so that the backend may upgrade to WebSocket (see the test below)
    assert module.cors_allowed_origins[:2] == ["https://rmn.example.ca", "http://rmn.example.ca"]


def test_the_backend_may_upgrade_to_websocket(monkeypatch):
    """The relay's own in-cluster name has to be an accepted origin.

    The server and the executor connect to ``http://socketio:7000``, and
    their WebSocket client sends that as the Origin where their polling
    client sends none. Without it the upgrade is refused with a 400 and every
    backend connection falls back to long-polling -- which is what the
    cluster did once the server gained ``websocket-client``.
    """
    module = _load_app(monkeypatch, ENVIRONMENT="production", SOCKETIO_SERVICE_TOKEN="svc",
                       MONGODB_USER="u", MONGODB_PASSWORD="p",
                       SOCKETIO_CORS_ORIGINS="rmn.example.ca")
    assert module.cors_allowed_origins == [
        "https://rmn.example.ca",
        "http://rmn.example.ca",
        "http://socketio:7000",
        "http://localhost:7000",
    ]


def test_a_wildcard_still_allows_everything(monkeypatch):
    """"*" must stay a wildcard, not become a four-entry list."""
    module = _load_app(monkeypatch, ENVIRONMENT="production", SOCKETIO_SERVICE_TOKEN="svc",
                       MONGODB_USER="u", MONGODB_PASSWORD="p",
                       SOCKETIO_CORS_ORIGINS="*")
    assert module.cors_allowed_origins == "*"
