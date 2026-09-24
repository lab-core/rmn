"""Slack dead-man's switch: single leader per tick, tolerant deletes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import fakeredis
import pytest

import service.health_check as hc


def _response(body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    return resp


def _pending(*msgs):
    """Slack list response: ``msgs`` are ``(id, date_created)`` pairs."""
    return {
        "ok": True,
        "scheduled_messages": [
            {"id": i, "date_created": c, "post_at": 10**12} for i, c in msgs
        ],
    }


def _deleted(calls):
    return [
        j["scheduled_message_id"]
        for m, j in calls
        if m == "chat.deleteScheduledMessage"
    ]


@pytest.fixture
def slack_calls(monkeypatch):
    """Record every Slack call; ``responses`` maps method name -> body."""
    calls = []
    responses = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        calls.append((method, json))
        assert timeout is not None, "Slack calls must not hang forever"
        return _response(responses[method])

    monkeypatch.setattr(hc.requests, "post", fake_post)
    return calls, responses


def test_already_gone_message_counts_as_cancelled(slack_calls, capsys):
    _, responses = slack_calls
    responses["chat.scheduledMessages.list"] = _pending(("OLD", 10), ("MINE", 100))
    responses["chat.deleteScheduledMessage"] = {
        "ok": False,
        "error": "invalid_scheduled_message_id",
    }
    assert hc.Slack(token="t").cancel_old_slack_messages("MINE") is True
    assert "❌" not in capsys.readouterr().out


def test_other_delete_errors_are_reported(slack_calls, capsys):
    _, responses = slack_calls
    responses["chat.scheduledMessages.list"] = _pending(("OLD", 10), ("MINE", 100))
    responses["chat.deleteScheduledMessage"] = {"ok": False, "error": "not_authed"}
    assert hc.Slack(token="t").cancel_old_slack_messages("MINE") is False
    assert "not deleted: OLD" in capsys.readouterr().out


def test_only_messages_older_than_ours_are_deleted(slack_calls):
    calls, responses = slack_calls
    responses["chat.scheduledMessages.list"] = _pending(
        ("OLD", 10), ("MINE", 100), ("SIBLING", 101)
    )
    responses["chat.deleteScheduledMessage"] = {"ok": True}
    assert hc.Slack(token="t").cancel_old_slack_messages("MINE") is True
    assert _deleted(calls) == ["OLD"]


def test_cleanup_ignores_the_local_clock(slack_calls, monkeypatch):
    calls, responses = slack_calls
    monkeypatch.setattr(hc.time, "time", lambda: 10**9)  # host clock far ahead
    responses["chat.scheduledMessages.list"] = _pending(("OLD", 10), ("MINE", 100))
    responses["chat.deleteScheduledMessage"] = {"ok": True}
    hc.Slack(token="t").cancel_old_slack_messages("MINE")
    assert _deleted(calls) == ["OLD"]


def test_nothing_deleted_when_our_message_is_not_listed(slack_calls, capsys):
    calls, responses = slack_calls
    responses["chat.scheduledMessages.list"] = _pending(("OLD", 10))
    assert hc.Slack(token="t").cancel_old_slack_messages("MINE") is False
    assert _deleted(calls) == []
    assert "not listed" in capsys.readouterr().out


def test_schedule_returns_the_message_id(slack_calls):
    _, responses = slack_calls
    responses["chat.scheduleMessage"] = {"ok": True, "scheduled_message_id": "Q1"}
    assert hc.Slack(token="t").send_slack_message() == "Q1"


def test_alert_shows_local_and_utc_time(slack_calls, monkeypatch):
    calls, responses = slack_calls
    responses["chat.scheduleMessage"] = {"ok": True, "scheduled_message_id": "Q1"}
    monkeypatch.setattr(hc, "TIMEZONE", "America/Montreal")
    tz = ZoneInfo("America/Montreal")
    before = datetime.now(tz)
    hc.Slack(token="t").send_slack_message()
    after = datetime.now(tz)
    text = calls[-1][1]["text"]
    assert text.endswith((hc.format_time(before), hc.format_time(after)))


def test_format_time_pairs_the_zones(monkeypatch):
    monkeypatch.setattr(hc, "TIMEZONE", "America/Montreal")
    expected = "Friday, September 04, 2026 at 01:27 PM EDT (2026-09-04 17:27 UTC)"
    local = datetime(2026, 9, 4, 13, 27, tzinfo=ZoneInfo("America/Montreal"))
    assert hc.format_time(local) == expected
    # any zone in, TIMEZONE out (a UTC datetime is not printed as-is)
    assert hc.format_time(local.astimezone(UTC)) == expected


def test_unknown_time_zone_falls_back_to_system_time(monkeypatch, capsys):
    monkeypatch.setattr(hc, "TIMEZONE", "Mars/Olympus_Mons")
    assert hc.local_now().utcoffset() is not None
    assert "unknown TZ" in capsys.readouterr().out


def test_failed_schedule_returns_none(slack_calls, capsys):
    _, responses = slack_calls
    responses["chat.scheduleMessage"] = {"ok": False, "error": "not_authed"}
    assert hc.Slack(token="t").send_slack_message() is None
    assert "not sent" in capsys.readouterr().out


def test_timeout_on_schedule_returns_none(monkeypatch):
    def raise_timeout(*a, **k):
        raise hc.requests.exceptions.Timeout()

    monkeypatch.setattr(hc.requests, "post", raise_timeout)
    assert hc.Slack(token="t").send_slack_message() is None


def test_no_authorization_header_without_token(monkeypatch):
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    assert "Authorization" not in hc.Slack().header
    assert "Authorization" in hc.Slack(token="t").header


def test_lock_lets_a_single_worker_run_the_tick():
    redis = fakeredis.FakeStrictRedis()
    first, second = hc.Slack(token="t", redis=redis), hc.Slack(token="t", redis=redis)
    assert first.acquire_lock(interval=900) is True
    assert second.acquire_lock(interval=900) is False
    assert 0 < redis.ttl(hc.LOCK_KEY) <= 840


def test_lock_fails_open_when_redis_is_down():
    redis = MagicMock()
    redis.set.side_effect = ConnectionError("redis down")
    assert hc.Slack(token="t", redis=redis).acquire_lock(interval=900) is True


def test_no_lock_without_redis():
    assert hc.Slack(token="t", redis=None).acquire_lock(interval=900) is True


def test_lock_fails_open_on_redis_timeout():
    redis = MagicMock()
    redis.set.side_effect = TimeoutError("socket timeout")
    assert hc.Slack(token="t", redis=redis).acquire_lock(interval=900) is True


def test_takeover_steals_a_lock_left_by_a_dead_process():
    """A restarted pod must tick now, not an interval after the one it replaced."""
    redis = fakeredis.FakeStrictRedis()
    dead = hc.Slack(token="t", redis=redis)
    assert dead.acquire_lock(interval=900) is True
    restarted = hc.Slack(token="t", redis=redis)
    assert restarted.acquire_lock(interval=900) is False
    assert restarted.acquire_lock(interval=900, takeover=True) is True
    assert 0 < redis.ttl(hc.LOCK_KEY) <= 840


def test_first_tick_runs_under_a_stale_lock(slack_calls, monkeypatch):
    """The daily rollout: the alert armed before the restart is cancelled."""
    calls, responses = slack_calls
    redis = fakeredis.FakeStrictRedis()
    # the pod being replaced ticked 14 minutes ago and left its lock behind
    hc.Slack(token="t", redis=redis).acquire_lock(interval=900)
    responses["chat.scheduleMessage"] = {"ok": True, "scheduled_message_id": "NEW"}
    responses["chat.scheduledMessages.list"] = _pending(("ARMED", 10), ("NEW", 100))
    responses["chat.deleteScheduledMessage"] = {"ok": True}

    # one pass of the loop: sleep ends it, as the thread would run forever
    monkeypatch.setattr(
        hc.time, "sleep", lambda _: (_ for _ in ()).throw(StopIteration)
    )
    with pytest.raises(StopIteration):
        hc.Slack(token="t", redis=redis).health_check(interval=900)

    assert _deleted(calls) == ["ARMED"]


def test_only_the_first_tick_takes_over(slack_calls, monkeypatch):
    """Take-over is for start-up only: later ticks go back through the lock."""
    calls, responses = slack_calls
    redis = fakeredis.FakeStrictRedis()
    responses["chat.scheduleMessage"] = {"ok": True, "scheduled_message_id": "NEW"}
    responses["chat.scheduledMessages.list"] = _pending(("NEW", 100))

    passes = []

    def stop_after_two(_):
        passes.append(1)
        if len(passes) == 2:
            raise StopIteration

    monkeypatch.setattr(hc.time, "sleep", stop_after_two)
    with pytest.raises(StopIteration):
        hc.Slack(token="t", redis=redis).health_check(interval=900)

    scheduled = [m for m, _ in calls if m == "chat.scheduleMessage"]
    assert len(passes) == 2 and scheduled == ["chat.scheduleMessage"]
