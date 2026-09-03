"""Slack dead-man's switch: single leader per tick, tolerant deletes."""

from unittest.mock import MagicMock

import fakeredis
import pytest

import service.health_check as hc


def _response(body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    return resp


@pytest.fixture
def slack_calls(monkeypatch):
    """Record every Slack call; ``responses`` maps URL suffix -> body."""
    calls = []
    responses = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url.rsplit("/", 1)[-1], json))
        assert timeout is not None, "Slack calls must not hang forever"
        return _response(responses[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(hc.requests, "post", fake_post)
    return calls, responses


def test_already_gone_message_counts_as_cancelled(slack_calls, capsys):
    calls, responses = slack_calls
    responses["chat.scheduledMessages.list"] = {
        "ok": True,
        "scheduled_messages": [
            {"id": "OLD", "date_created": 10, "post_at": 10**12},
        ],
    }
    responses["chat.deleteScheduledMessage"] = {
        "ok": False,
        "error": "invalid_scheduled_message_id",
    }
    assert hc.Slack(token="t").cancel_old_slack_messages(ts=100) is True
    assert "❌" not in capsys.readouterr().out


def test_other_delete_errors_are_reported(slack_calls, capsys):
    calls, responses = slack_calls
    responses["chat.scheduledMessages.list"] = {
        "ok": True,
        "scheduled_messages": [
            {"id": "OLD", "date_created": 10, "post_at": 10**12},
        ],
    }
    responses["chat.deleteScheduledMessage"] = {"ok": False, "error": "not_authed"}
    assert hc.Slack(token="t").cancel_old_slack_messages(ts=100) is False
    assert "not deleted: OLD" in capsys.readouterr().out


def test_only_messages_created_before_this_tick_are_deleted(slack_calls):
    calls, responses = slack_calls
    responses["chat.scheduledMessages.list"] = {
        "ok": True,
        "scheduled_messages": [
            {"id": "OLD", "date_created": 10, "post_at": 10**12},
            {"id": "MINE", "date_created": 100, "post_at": 10**12},
        ],
    }
    responses["chat.deleteScheduledMessage"] = {"ok": True}
    hc.Slack(token="t").cancel_old_slack_messages(ts=100)
    deleted = [
        j["scheduled_message_id"]
        for m, j in calls
        if m == "chat.deleteScheduledMessage"
    ]
    assert deleted == ["OLD"]


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
