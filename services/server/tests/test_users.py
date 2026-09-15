"""User management: signup rules, profile flags, password change and token helpers."""

import datetime as dt
import json

import service.user_service as user_service
from service.user_service import Role, UserService, _utc, token_expired
from werkzeug.security import check_password_hash
import pytest

ADMIN = "Administrateur"
USER = "Utilisateur"


def test_role_available():
    assert Role.available(USER) is True
    assert Role.available(ADMIN) is True
    assert Role.available("root") is False


def test_utc_normalises_naive_datetimes():
    naive = dt.datetime(2026, 1, 1, 12)
    aware = dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC)
    assert _utc(naive) == aware
    assert _utc(aware) is aware


def test_token_expiry_rules(monkeypatch):
    now = dt.datetime.now(dt.UTC)
    assert token_expired({}) is True
    assert token_expired({"creation_time": now}) is False
    assert token_expired({"creation_time": now - dt.timedelta(days=31)}) is True
    assert token_expired({"creation_time": (now - dt.timedelta(days=31)).replace(tzinfo=None)}) is True
    monkeypatch.setattr(user_service, "TOKEN_TTL_DAYS", 0)
    assert token_expired({}) is False


def test_signup_requires_an_admin_token(client, user_factory, login):
    user_factory("alice")
    token = login("alice")
    resp = client.post(
        "/signup",
        data={"user_id": "alice", "token": token, "username": "bob", "password": "Passw0rd", "role": USER},
    )
    assert resp.status_code == 401


def test_admin_signup_validates_and_hashes(client, user_factory, login, app_module_fixture):
    user_factory("root", role=ADMIN)
    token = login("root")
    base = {"user_id": "root", "token": token, "role": USER}

    assert client.post("/signup", data={**base, "username": "bob", "password": "bad space"}).status_code == 400
    assert client.post("/signup", data={**base, "username": "bob", "password": "Passw0rd", "role": "Boss"}).status_code == 400
    assert client.post("/signup", data={**base, "username": "bob"}).status_code == 400

    resp = client.post("/signup", data={**base, "username": "bob", "password": "S3cret!!"})
    assert resp.status_code == 200
    bob = app_module_fixture.mongo["RMN"]["users"].find_one({"username": "bob"})
    assert bob["role"] == USER
    assert bob["password"] != "S3cret!!" and check_password_hash(bob["password"], "S3cret!!")
    assert bob["saveVerifiedImages"] is False and bob["moodleStructureInd"] is True

    # the name is taken now
    assert client.post("/signup", data={**base, "username": "bob", "password": "Other123"}).status_code == 404


def test_profile_flags(client, user_factory, login, app_module_fixture):
    user_factory("alice")
    token = login("alice")
    users = app_module_fixture.mongo["RMN"]["users"]

    resp = client.put(
        "/updateSaveVerifiedImages", data={"username": "alice", "token": token, "saveVerifiedImages": "1"}
    )
    assert resp.status_code == 200
    assert users.find_one({"username": "alice"})["saveVerifiedImages"] is True

    resp = client.put(
        "/updateMoodleStructureInd", data={"username": "alice", "token": token, "moodleStructureInd": "0"}
    )
    assert resp.status_code == 200
    assert users.find_one({"username": "alice"})["moodleStructureInd"] is False

    assert client.put("/updateSaveVerifiedImages", data={"username": "alice", "token": token}).status_code == 400


def test_change_password_checks_the_old_one(client, user_factory, login):
    user_factory("alice", password="pass123")
    token = login("alice", "pass123")
    base = {"username": "alice", "token": token}

    assert client.post("/password", data={**base, "old_password": "nope", "new_password": "NewPass1"}).status_code == 500
    assert client.post("/password", data={**base, "old_password": "pass123", "new_password": "bad space"}).status_code == 400
    assert client.post("/password", data={**base, "old_password": "pass123"}).status_code == 400

    assert client.post("/password", data={**base, "old_password": "pass123", "new_password": "NewPass1"}).status_code == 200
    assert client.post("/login", data={"username": "alice", "password": "pass123"}).status_code == 404
    login("alice", "NewPass1")


def test_delete_tokens_by_owner_and_age(app_module_fixture):
    db = app_module_fixture.mongo["RMN"]
    now = dt.datetime.now(dt.UTC)
    db["tokens"].insert_many(
        [
            {"token": "a-fresh", "username": "alice", "creation_time": now},
            {"token": "a-old", "username": "alice", "creation_time": now - dt.timedelta(days=10)},
            {"token": "b-old", "username": "bob", "creation_time": now - dt.timedelta(days=10)},
        ]
    )

    UserService.delete_tokens("alice", 5, db)
    assert sorted(t["token"] for t in db["tokens"].find()) == ["a-fresh", "b-old"]

    UserService.delete_tokens(None, 0, db)
    assert db["tokens"].count_documents({}) == 0


def test_users_and_delete(app_module_fixture, user_factory):
    db = app_module_fixture.mongo["RMN"]
    user_factory("alice")
    user_factory("bob")
    UserService.create_token("alice", USER, db)

    assert sorted(UserService.users(db)) == ["alice", "bob"]
    UserService.delete("alice", db)
    assert UserService.users(db) == ["bob"]
    assert db["tokens"].count_documents({"username": "alice"}) == 0


def test_profile_flags_apply_to_the_token_owner(client, user_factory, login, app_module_fixture):
    # no username in the form: the token says who is updated
    user_factory("alice")
    token = login("alice")
    users = app_module_fixture.mongo["RMN"]["users"]
    resp = client.put("/updateSaveVerifiedImages", data={"token": token, "saveVerifiedImages": "1"})
    assert resp.status_code == 200
    assert users.find_one({"username": "alice"})["saveVerifiedImages"] is True
    resp = client.put("/updateMoodleStructureInd", data={"token": token, "moodleStructureInd": "0"})
    assert resp.status_code == 200
    assert users.find_one({"username": "alice"})["moodleStructureInd"] is False


@pytest.mark.parametrize("username", ["ab", "bad name", "../..", "a" * 65, "x/y", ""])
def test_signup_rejects_unsafe_usernames(client, user_factory, login, username):
    # the username names a directory (front_page_temp) and is a key everywhere
    user_factory("root", role=ADMIN)
    token = login("root")
    base = {"user_id": "root", "token": token, "role": USER, "password": "S3cret!!"}
    assert client.post("/signup", data={**base, "username": username}).status_code == 400


def test_signup_accepts_the_usual_usernames(client, user_factory, login):
    user_factory("root", role=ADMIN)
    token = login("root")
    base = {"user_id": "root", "token": token, "role": USER, "password": "S3cret!!"}
    for username in ("jean.dupont", "j_dupont@poly", "JD-2026"):
        assert client.post("/signup", data={**base, "username": username}).status_code == 200


def test_passwords_shorter_than_the_minimum_are_refused(client, user_factory, login):
    # the webapp asked for 8 characters in its change dialog, the server took 1
    user_factory("root", role=ADMIN)
    user_factory("alice", password="pass1234")
    short = "A" * (user_service.MIN_PASSWORD_LENGTH - 1)
    ok = "A" * user_service.MIN_PASSWORD_LENGTH
    root, alice = login("root"), login("alice", "pass1234")

    resp = client.post(
        "/signup", data={"user_id": "root", "token": root, "role": USER, "username": "bob", "password": short}
    )
    assert resp.status_code == 400 and "8 characters" in json.loads(resp.data)["response"]
    resp = client.post(
        "/password",
        data={"username": "alice", "token": alice, "old_password": "pass1234", "new_password": short},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/admin/change_password",
        data={"username": "alice", "new_password": short},
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert resp.status_code == 400
    too_long = "A" * (user_service.MAX_PASSWORD_LENGTH + 1)
    resp = client.post(
        "/signup", data={"user_id": "root", "token": root, "role": USER, "username": "bob", "password": too_long}
    )
    assert resp.status_code == 400 and "64 characters" in json.loads(resp.data)["response"]
    # the old password is untouched by the refused attempts
    login("alice", "pass1234")

    assert client.post(
        "/signup", data={"user_id": "root", "token": root, "role": USER, "username": "bob", "password": ok}
    ).status_code == 200
    # the classical special characters are all accepted
    assert client.post(
        "/signup", data={"user_id": "root", "token": root, "role": USER, "username": "carol", "password": "P@ss!#$%^&*.?_-"}
    ).status_code == 200
    login("carol", "P@ss!#$%^&*.?_-")


def test_admin_password_reset_of_an_unknown_user_is_a_404(client):
    resp = client.post(
        "/admin/change_password",
        data={"username": "ghost", "new_password": "Reset123"},
        headers={"X-Admin-Key": "test-admin-key"},
    )
    assert resp.status_code == 404
