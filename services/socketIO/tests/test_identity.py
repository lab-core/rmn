"""Who a connection is (``identify``) and which rooms it may join (``can_join``)."""

from app import can_join, identify
from conftest import SERVICE_TOKEN

ANONYMOUS = {"role": "anonymous"}


def test_service_token_identifies_the_backend():
    assert identify({"service_token": SERVICE_TOKEN}) == {"role": "service"}
    assert identify({"service_token": "wrong"}) == ANONYMOUS


def test_non_dict_or_empty_auth_is_anonymous():
    assert identify(None) == ANONYMOUS
    assert identify("tok") == ANONYMOUS
    assert identify({}) == ANONYMOUS


def test_valid_user_token(make_token):
    make_token("alice")
    assert identify({"token": "tok-alice"}) == {"role": "user", "user_id": "alice"}
    assert identify({"token": "tok-alice", "user_id": "alice"}) == {"role": "user", "user_id": "alice"}
    # the claimed user must match the token's owner
    assert identify({"token": "tok-alice", "user_id": "bob"}) == ANONYMOUS


def test_expired_and_unknown_tokens_are_ignored(make_token):
    make_token("alice", age_days=40)
    assert identify({"token": "tok-alice"}) == ANONYMOUS
    assert identify({"token": "tok-nobody"}) == ANONYMOUS


def test_non_string_credentials_are_rejected_before_any_query(make_token):
    make_token("alice")
    assert identify({"token": {"$ne": ""}}) == ANONYMOUS
    assert identify({"token": ""}) == ANONYMOUS
    assert identify({"share_token": {"$ne": ""}}) == ANONYMOUS


def test_share_token(make_token):
    assert identify({"share_token": "s1"}) == {"role": "share", "share_token": "s1"}
    # an invalid user token does not block a share token
    assert identify({"token": "tok-nobody", "share_token": "s1"}) == {"role": "share", "share_token": "s1"}


def test_room_name_must_be_a_non_empty_string():
    assert can_join({"role": "service"}, None) is False
    assert can_join({"role": "service"}, "") is False
    assert can_join({"role": "service"}, {"$ne": ""}) is False


def test_service_joins_any_room():
    assert can_join({"role": "service"}, "anything") is True


def test_user_joins_own_room_jobs_and_templates(db):
    db["eval_jobs"].insert_one({"job_id": "job", "user_id": "alice"})
    db["template"].insert_one({"template_id": "tpl", "user_id": "alice"})
    alice = {"role": "user", "user_id": "alice"}
    bob = {"role": "user", "user_id": "bob"}

    assert can_join(alice, "alice") is True
    assert can_join(alice, "job") is True
    assert can_join(alice, "tpl") is True
    assert can_join(alice, "bob") is False
    assert can_join(alice, "other-job") is False
    assert can_join(bob, "job") is False
    assert can_join(bob, "tpl") is False


def test_share_token_joins_the_shared_job_only(db):
    db["eval_jobs"].insert_many(
        [
            {"job_id": "job", "share_token": {"questions": "s1", "all": "s2"}},
            {"job_id": "private", "user_id": "alice"},
        ]
    )
    db["jobs_output"].insert_one({"job_id": "out", "share_token": "s3"})

    assert can_join({"role": "share", "share_token": "s1"}, "job") is True
    assert can_join({"role": "share", "share_token": "s2"}, "job") is True
    assert can_join({"role": "share", "share_token": "s3"}, "out") is True
    assert can_join({"role": "share", "share_token": "s3"}, "job") is False
    assert can_join({"role": "share", "share_token": "s9"}, "job") is False
    assert can_join({"role": "share", "share_token": "s1"}, "private") is False


def test_anonymous_joins_nothing(db):
    db["eval_jobs"].insert_one({"job_id": "job", "user_id": "alice"})
    assert can_join({"role": "anonymous"}, "job") is False
    assert can_join({}, "job") is False
