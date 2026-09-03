"""Slack dead-man's switch for the server.

Every ``interval`` seconds a message saying "RMN is not responding" is
scheduled on Slack ``SLACK_DELAY`` seconds in the future, and the previously
scheduled ones are cancelled. If the server stops running the loop, the last
message is never cancelled and Slack posts the alert.

gunicorn runs several workers and each imports the app, so each would run its
own loop: every tick would schedule one message per worker and each worker
would try to delete the others' messages, the second delete failing with
``invalid_scheduled_message_id``. A short-lived Redis lock lets a single
worker do the tick; if Redis is unreachable every worker proceeds (duplicate
alerts are preferable to no alert).
"""

import os
import time
from datetime import datetime
from threading import Thread
from typing import Any, Dict, Optional

import requests

SLACK_CHANNEL = os.getenv("SLACK_CHANNEL") or "C094Y8KQ4HL"
SLACK_DELAY = 1800
MESSAGE = "🚨 RMN service is not responding, but was alive on {}"
REQUEST_TIMEOUT = 15
LOCK_KEY = "health_check:leader"
# Slack refuses to cancel a message that posts within 60 s of the request.
UNCANCELLABLE_WINDOW = 60
# Slack's answer when a scheduled message is already posted or deleted.
ALREADY_GONE = "invalid_scheduled_message_id"


def start_health_check(interval: int = 900, redis: Any = None) -> Thread:
    """Start the dead-man's switch loop in a daemon thread.

    Args:
        interval: Seconds between two ticks.
        redis: Redis client used for the leader lock; ``None`` disables the
            lock (every process runs the loop).

    Returns:
        The started thread.
    """
    slack = Slack(redis=redis)
    thread = Thread(target=slack.health_check, args=(interval,), daemon=True)
    print("✅ Health check thread started")
    thread.start()
    return thread


class Slack:
    """Schedules and cancels the "not responding" Slack message."""

    def __init__(
        self,
        token: Optional[str] = None,
        channel: str = SLACK_CHANNEL,
        redis: Any = None,
    ) -> None:
        """Read the bot token from ``SLACK_TOKEN`` unless given.

        Args:
            token: Slack bot token; defaults to the ``SLACK_TOKEN`` env var.
            channel: Channel the alert is scheduled in.
            redis: Redis client for the leader lock, or ``None``.
        """
        self.token = token or os.getenv("SLACK_TOKEN")
        self.channel = channel
        self.redis = redis
        self.header = {"Content-Type": "application/json; charset=utf-8"}
        if self.token is None:
            print("WARNING: SLACK_TOKEN is not set in environment")
        else:
            self.header["Authorization"] = f"Bearer {self.token}"

    def health_check(self, interval: int = 900) -> None:
        """Run ticks forever, ``interval`` seconds apart."""
        if self.token is None:
            print("SLACK_TOKEN is not set in environment, cannot run health check")
            return
        while True:
            if self.acquire_lock(interval):
                now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
                print(f"Run health check on {now}")
                try:
                    message_id = self.send_slack_message()
                    if message_id is None:
                        # the new alert is not armed: keep the previous ones,
                        # otherwise a Slack hiccup would disarm the switch
                        print("❌ keeping the previous Slack alerts armed")
                    else:
                        self.cancel_old_slack_messages(message_id)
                except Exception as e:  # keep the loop alive
                    print(e)
            time.sleep(interval)

    def acquire_lock(self, interval: int) -> bool:
        """Elect the worker that runs this tick.

        The lock expires a minute before the next tick so that whichever
        worker ticks first takes it, usually the same one. If a tick runs late
        the lock may change hands and two alerts get scheduled in that
        interval; both are cancelled at the next tick, so the switch stays
        armed either way. The goal is roughly one tick per interval, not a
        stable leader.

        Args:
            interval: Seconds between two ticks.

        Returns:
            True if this process should run the tick.
        """
        if self.redis is None:
            return True
        try:
            ttl = max(interval - 60, 1)
            return bool(self.redis.set(LOCK_KEY, os.getpid(), nx=True, ex=ttl))
        except Exception as e:
            print(f"health check: Redis lock unavailable ({e}), running anyway")
            return True

    def send_slack_message(self) -> Optional[str]:
        """Schedule the alert ``SLACK_DELAY`` seconds from now.

        Returns:
            Slack's ``scheduled_message_id``, or ``None`` if Slack did not
            accept it (the caller must then keep the older alerts).
        """
        now = datetime.now()
        now_ts = int(now.timestamp())
        formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")
        data = {
            "channel": self.channel,
            "text": MESSAGE.format(formatted),
            "post_at": now_ts + SLACK_DELAY,
        }
        try:
            response = self.post("https://slack.com/api/chat.scheduleMessage", data)
            body = response.json()
            if response.status_code != requests.codes.ok or not body.get("ok"):
                print("❌ Slack message not sent:", response.status_code)
                print("Slack response for message:", body)
                return None
            return body.get("scheduled_message_id")
        except requests.exceptions.Timeout:
            print("❌ Timeout sending to Slack")
            return None

    def cancel_old_slack_messages(self, keep_id: str) -> bool:
        """Cancel every alert scheduled before the one this tick armed.

        "Before" is decided with Slack's own ``date_created`` of the kept
        message, never with the local clock, so a skewed host cannot make us
        delete the fresh alert. A message newer than ours belongs to a
        sibling worker running the same tick and is left alone. A message
        that is already gone (posted, or deleted by a sibling) counts as
        cancelled; one that posts within the next minute cannot be cancelled
        anymore and is reported.

        Args:
            keep_id: ``scheduled_message_id`` of the alert armed by this tick.

        Returns:
            True if every older message is cancelled or already gone.
        """
        try:
            response = self.get_scheduled_messages()
            body = response.json()
            if response.status_code != requests.codes.ok or not body.get("ok"):
                print("❌ Slack scheduled messages not received:", response.status_code)
                print("Slack response for list:", body)
                return False

            pending = body.get("scheduled_messages", [])
            mine = next((m for m in pending if m["id"] == keep_id), None)
            if mine is None:
                # cannot tell old from new without our reference: cancel
                # nothing rather than risk disarming the switch
                print("❌ freshly scheduled Slack alert", keep_id, "not listed")
                return False

            ok = True
            now = int(time.time())
            for message in pending:
                if message["id"] == keep_id:
                    continue
                if message["date_created"] >= mine["date_created"]:
                    continue
                if message["post_at"] - now < UNCANCELLABLE_WINDOW:
                    print(
                        "❌ Slack alert",
                        message["id"],
                        "posts in less than a minute; too late to cancel it",
                    )
                    ok = False
                    continue
                ok = self.delete_scheduled_message(message["id"]) and ok
            return ok
        except requests.exceptions.Timeout:
            print("❌ Timeout sending to Slack")
            return False

    def delete_scheduled_message(self, message_id: str) -> bool:
        """Cancel one scheduled message.

        Args:
            message_id: Slack ``scheduled_message_id``.

        Returns:
            True if cancelled or already gone.
        """
        response = self.post(
            "https://slack.com/api/chat.deleteScheduledMessage",
            {"channel": self.channel, "scheduled_message_id": message_id},
        )
        body = response.json()
        if response.status_code == requests.codes.ok and body.get("ok"):
            return True
        if body.get("error") == ALREADY_GONE:
            # posted already, or a sibling worker deleted it first
            return True
        print("Slack response for delete:", body)
        print(
            "❌ Slack scheduled messages not deleted:", message_id, response.status_code
        )
        return False

    def get_scheduled_messages(self) -> requests.Response:
        """List the pending scheduled messages of the channel."""
        return self.post(
            "https://slack.com/api/chat.scheduledMessages.list",
            {"channel": self.channel},
        )

    def post(self, url: str, data: Dict[str, Any]) -> requests.Response:
        """POST JSON to a Slack Web API method with the bot token."""
        return requests.post(
            url, json=data, headers=self.header, timeout=REQUEST_TIMEOUT
        )

    def check_scheduled_messages(self) -> None:
        """Print the pending scheduled messages (manual inspection)."""
        body = self.get_scheduled_messages().json()
        print(body)
        now_ts = int(datetime.now().timestamp())
        for message in body.get("scheduled_messages", []):
            print(
                "Message to be posted in",
                message["post_at"] - now_ts,
                "seconds:",
                message,
            )


if __name__ == "__main__":
    Slack().check_scheduled_messages()
