"""The url space and the blueprints have to keep agreeing.

Two ways they can drift apart, both silent. A route filed in the wrong
blueprint would answer on a path that says otherwise -- which is why every
rule now has to sit under its blueprint's prefix. And a path the webapp
calls that the server does not serve is a 404 at runtime: the specs stub the
http client, so nothing on that side notices.

Only literal paths are checked. The one url built from a variable -- the
share dialog posts to the kind of thing being shared -- maps that kind to a
route through a constant, and its own spec asserts what comes out.
"""

import re
from pathlib import Path

import pytest

WEBAPP = Path(__file__).resolve().parents[2] / "webapp" / "ng" / "src"
# `${SERVER_URL}documents/replace`, SERVER_URL + 'users/login'
CALLS = re.compile(r"SERVER_URL\}([a-zA-Z0-9_/]+)|SERVER_URL \+ ['\"]([a-zA-Z0-9_/]+)")


def webapp_paths():
    found = set()
    for source in WEBAPP.rglob("*.ts"):
        if source.name.endswith(".spec.ts"):
            continue
        for match in CALLS.finditer(source.read_text()):
            found.add("/" + (match.group(1) or match.group(2)))
    return found


def test_every_path_the_webapp_calls_is_served(app_module_fixture):
    if not WEBAPP.exists():  # the server image ships without the webapp
        pytest.skip("webapp sources not present")
    served = {str(rule) for rule in app_module_fixture.app.url_map.iter_rules()}
    called = webapp_paths()
    assert called, "no API call found in the webapp: the pattern stopped matching"
    assert called <= served, f"the webapp calls paths nothing serves: {sorted(called - served)}"


def test_every_route_sits_under_its_blueprint(app_module_fixture):
    """What makes the layout self-enforcing rather than a convention."""
    app = app_module_fixture.app
    stray = []
    for rule in app.url_map.iter_rules():
        blueprint = rule.endpoint.rsplit(".", 1)[0] if "." in rule.endpoint else None
        if blueprint is None or blueprint not in app.blueprints:
            continue  # the root route and flask's own static rule
        prefix = app.blueprints[blueprint].url_prefix
        assert prefix, f"blueprint {blueprint} has no url_prefix"
        if not str(rule).startswith(prefix):
            stray.append(f"{rule} is served by {blueprint} ({prefix})")
    assert not stray, "\n".join(stray)
