"""The socketIO client both backends push notifications through.

The server and the executor tell the webapp what just happened over the
socketIO relay. That push is best effort by nature: the state is already in
MongoDB before anything is emitted, so a browser that misses an event sees
the same thing on its next request. Neither service, though, used to treat it
that way, and a relay restart took both of them down with it (October 2026):

- the server held one connected client for the life of the process, so once
  the relay dropped, ``emit`` raised ``BadNamespaceError`` out of whatever
  route was emitting and the user got a 500;
- the executor connected at start-up and let the ConnectionError escape, so
  every pod spawned while the relay was restarting died before taking a job.

``BestEffortRelay`` holds the client instead: it reconnects when it has to,
rate-limits the attempts, and turns every failure into a logged no-op. It
never imports socketio -- the caller passes a factory that builds and
connects its own client -- so the service keeps deciding what a connection
is (its url, its credentials) and this package keeps its stdlib-only imports.
"""

import time
from typing import Any, Callable


class BestEffortRelay:
    """A socketIO client wrapped so an outage never reaches its caller.

    Args:
        connect: builds a *connected* client. Called again on every
            reconnection, and may raise: that is what being down looks like.
            The object it returns is used for its ``connected`` attribute and
            its ``emit`` and ``disconnect`` methods.
    """

    #: seconds before a relay that refused a connection is tried again, so
    #: that a down relay costs one attempt per cooldown and not one per event
    RETRY_COOLDOWN = 5.0

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect
        self._client: Any = None
        self._next_try = 0.0

    @property
    def connected(self) -> bool:
        """Whether a client is currently connected to the relay."""
        return self._client is not None and self._client.connected

    def connect(self) -> bool:
        """(Re)connect if needed, and report whether the relay is usable.

        Never raises: a caller treats a missing relay as a dropped
        notification, never as a failure of its own work.
        """
        if self.connected:
            return True
        if time.monotonic() < self._next_try:
            return False
        self.disconnect()  # drop a client that is present but disconnected
        try:
            self._client = self._connect()
        except Exception as exc:
            self._next_try = time.monotonic() + self.RETRY_COOLDOWN
            print(f"WARNING: socketIO relay unreachable: {exc}", flush=True)
            return False
        return True

    def emit(self, event: str, data: Any) -> bool:
        """Send ``event`` to the relay, and report whether it went out."""
        if not self.connect():
            print(f"WARNING: dropped socketIO event {event!r}: relay unreachable",
                  flush=True)
            return False
        try:
            self._client.emit(event, data)
            return True
        except Exception as exc:
            print(f"WARNING: dropped socketIO event {event!r}: {exc}", flush=True)
            self.disconnect()
            return False

    def disconnect(self) -> None:
        """Drop the underlying client, if there is one. Never raises."""
        if self._client is None:
            return
        try:
            self._client.disconnect()
        except Exception:
            pass
        self._client = None
