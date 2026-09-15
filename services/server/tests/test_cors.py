"""Browser origins allowed to call the API (CORS_ORIGINS)."""

import pytest

from app import cors_origins


def test_cors_origins_syntax():
    assert cors_origins("*") == "*"
    assert cors_origins(" * ") == "*"
    # a bare host allows both schemes, an entry with a scheme is kept as-is
    assert cors_origins("rmn.example.org") == ["https://rmn.example.org", "http://rmn.example.org"]
    assert cors_origins("https://a.org, b.org,,") == [
        "https://a.org",
        "https://b.org",
        "http://b.org",
    ]


def test_default_allows_every_origin(client):
    resp = client.post("/login", data={}, headers={"Origin": "https://evil.example"})
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://evil.example"


@pytest.mark.parametrize(
    "origin, allowed",
    [
        ("https://rmn.example.org", True),
        ("http://rmn.example.org", True),
        ("https://evil.example", False),
    ],
)
def test_pinned_origins(client, app_module_fixture, monkeypatch, origin, allowed):
    # @cross_origin() reads the app config on every request, so the pin can be
    # applied here; the app-level CORS(app) fallback (404s, 405s) copied the
    # config at import time and is not exercised
    monkeypatch.setitem(
        app_module_fixture.app.config, "CORS_ORIGINS", cors_origins("rmn.example.org")
    )
    resp = client.post("/login", data={}, headers={"Origin": origin})
    header = resp.headers.get("Access-Control-Allow-Origin")
    assert (header == origin) if allowed else (header is None)
    # the preflight of a cross-site POST gets the same answer
    resp = client.options(
        "/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    assert (
        (resp.headers.get("Access-Control-Allow-Origin") == origin)
        if allowed
        else (resp.headers.get("Access-Control-Allow-Origin") is None)
    )
