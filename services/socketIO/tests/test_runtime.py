"""The server must keep answering while a handler waits on Mongo.

Regression test for the October 2026 crash loop: the app ran its handlers as
eventlet greenthreads on a single hub (``monkey_patch(select=False,
thread=False)``) while pymongo waited on the unpatched ``select`` and
``threading`` primitives. The first Mongo lookup from the connect handler
could park the hub, and with it every other greenthread -- the readiness and
liveness probes included -- until the kubelet killed the pod.
"""

import json
import threading
import time
import urllib.request

import pytest
from werkzeug.serving import make_server

import app as app_module

HANDSHAKE = "/socket.io/?EIO=4&transport=polling"


def test_the_app_does_not_run_on_an_eventlet_hub():
    import sys

    assert app_module.socketio.async_mode == "threading"
    # importing eventlet at all would re-introduce the monkey patching
    assert "eventlet" not in sys.modules


@pytest.fixture
def server():
    """Serve the real WSGI app on a background thread, one thread per request."""
    srv = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    thread.join(timeout=5)


def _handshake(base):
    """Open an engine.io session and return its sid (what the probes hit)."""
    raw = urllib.request.urlopen(base + HANDSHAKE, timeout=5).read().decode()
    return json.loads(raw[1:])["sid"]  # the payload is prefixed with "0"


def test_a_handler_waiting_on_mongo_does_not_freeze_the_server(server, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def slow_identify(auth):
        """Stand in for a Mongo lookup that does not come back."""
        entered.set()
        release.wait(30)
        return {"role": "anonymous"}

    monkeypatch.setattr(app_module, "identify", slow_identify)
    sid = _handshake(server)

    def connect():
        request = urllib.request.Request(f"{server}{HANDSHAKE}&sid={sid}", data=b"40")
        try:
            urllib.request.urlopen(request, timeout=30).read()
        except OSError:  # the session is torn down with the server
            pass

    client = threading.Thread(target=connect, daemon=True)
    client.start()
    try:
        assert entered.wait(5), "the connect handler never ran"
        # the probes must still get an answer while that handler is stuck
        started = time.monotonic()
        _handshake(server)
        assert time.monotonic() - started < 2
    finally:
        release.set()
        client.join(timeout=5)


def test_eventlet_is_not_a_dependency_any_more():
    """Guard against a re-introduction: the deadlock came with the library.

    Checked in the file rather than with an import, since the test venv may
    get eventlet from somewhere else (as test_clients does for requests in
    the executor).
    """
    from pathlib import Path

    requirements = Path(__file__).resolve().parent.parent.joinpath("requirements.txt")
    names = {
        line.split("==")[0].strip().lower()
        for line in requirements.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "eventlet" not in names
    assert "gunicorn" in names  # what serves the app in the image


def test_gunicorn_keeps_its_heartbeat_file_off_the_read_only_root():
    """The pod runs with readOnlyRootFilesystem, so /tmp is not writable.

    gunicorn creates a heartbeat file per worker through ``tempfile``, and
    without ``--worker-tmp-dir`` pointing somewhere writable the worker dies
    at boot with "No usable temporary directory found" -- which is how v1.6.6
    first reached the cluster. Checked in the file: nothing in the test
    environment has the image's filesystem.
    """
    from pathlib import Path

    dockerfile = Path(__file__).resolve().parent.parent.joinpath("Dockerfile")
    content = dockerfile.read_text()
    assert "gunicorn" in content
    assert '"--worker-tmp-dir", "/dev/shm"' in content
    # gunicorn 26 also opens a management socket under $HOME/.gunicorn, which
    # is on the same read-only filesystem; nothing here uses it
    assert '"--no-control-socket"' in content
