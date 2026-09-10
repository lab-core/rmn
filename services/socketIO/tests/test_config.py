"""Configuration parsing and token expiry."""

import datetime as dt

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
