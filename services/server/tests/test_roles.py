"""The three roles, the managers of an account and the forced password change."""

import pytest

from service.user_service import (
    PASSWORD_SPECIAL_CHARACTERS,
    Role,
    password_error,
    temporary_password,
)

ADMIN = "Administrateur"
MANAGER = "Gestionnaire"
USER = "Utilisateur"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def users(app_module_fixture):
    return app_module_fixture.mongo["RMN"]["users"]


def _signup(client, creator, token, username, role=USER, password="Passw0rd!"):
    return client.post(
        "/users/signup",
        data={
            "user_id": creator,
            "username": username,
            "password": password,
            "role": role,
        },
        headers=_auth(token),
    )


def test_roles_are_ordered():
    assert Role.available(MANAGER)
    assert Role.at_least(ADMIN, Role.MANAGER)
    assert Role.at_least(MANAGER, Role.MANAGER)
    assert not Role.at_least(USER, Role.MANAGER)
    assert not Role.at_least("root", Role.USER)


def test_role_values_match_the_shared_enum():
    from rmn_common.status import User_Role

    assert [r.value for r in Role] == [r.value for r in User_Role]


def test_temporary_passwords_follow_the_rules():
    for _ in range(50):
        password = temporary_password()
        assert password_error(password) is None
        assert any(c in PASSWORD_SPECIAL_CHARACTERS for c in password)


def test_a_manager_creates_users_and_managers_but_no_admin(
    client, user_factory, login, users
):
    user_factory("chef", role=MANAGER)
    token = login("chef")

    assert _signup(client, "chef", token, "alice").status_code == 200
    assert _signup(client, "chef", token, "sous-chef", MANAGER).status_code == 200
    assert _signup(client, "chef", token, "boss", ADMIN).status_code == 403

    alice = users.find_one({"username": "alice"})
    assert alice["managers"] == ["chef"] and alice["must_change_password"] is True
    assert users.find_one({"username": "sous-chef"})["role"] == MANAGER
    assert users.find_one({"username": "boss"}) is None


def test_an_admin_creates_any_role_and_is_no_manager(
    client, user_factory, login, users
):
    user_factory("root", role=ADMIN)
    token = login("root")
    assert _signup(client, "root", token, "boss", ADMIN).status_code == 200
    boss = users.find_one({"username": "boss"})
    assert boss["managers"] == [] and boss["must_change_password"] is True


def test_a_user_creates_nobody(client, user_factory, login):
    user_factory("alice")
    assert _signup(client, "alice", login("alice"), "bob").status_code == 403


def test_a_manager_lists_only_the_accounts_it_manages(
    client, user_factory, login, users
):
    user_factory("chef", role=MANAGER)
    user_factory("autre", role=MANAGER)
    user_factory("alice")
    user_factory("bob")
    user_factory("root", role=ADMIN)
    users.update_one({"username": "alice"}, {"$set": {"managers": ["chef"]}})
    users.update_one({"username": "bob"}, {"$set": {"managers": ["autre", "chef"]}})
    # an admin listing a manager gives them nothing on it
    users.update_one({"username": "root"}, {"$set": {"managers": ["chef"]}})

    resp = client.get("/users/all", headers=_auth(login("chef")))
    assert [u["username"] for u in resp.get_json(force=True)["response"]] == [
        "alice",
        "bob",
    ]
    resp = client.get("/users/all", headers=_auth(login("autre")))
    assert [u["username"] for u in resp.get_json(force=True)["response"]] == ["bob"]


def test_reset_gives_a_temporary_password_and_closes_the_sessions(
    client, user_factory, login, users, app_module_fixture
):
    user_factory("chef", role=MANAGER)
    user_factory("alice")
    users.update_one({"username": "alice"}, {"$set": {"managers": ["chef"]}})
    old_session = login("alice")

    resp = client.post(
        "/users/reset_password",
        data={"user_id": "chef", "username": "alice"},
        headers=_auth(login("chef")),
    )
    assert resp.status_code == 200
    temporary = resp.get_json(force=True)["response"]["password"]
    assert users.find_one({"username": "alice"})["must_change_password"] is True
    tokens = app_module_fixture.mongo["RMN"]["tokens"]
    assert tokens.find_one({"token": old_session}) is None

    # the temporary password logs in, but only to change it
    session = login("alice", temporary)
    jobs = client.post("/jobs", data={"user_id": "alice"}, headers=_auth(session))
    assert jobs.status_code == 403
    assert jobs.get_json(force=True)["code"] == "password_change_required"

    same = client.post(
        "/users/password",
        data={"old_password": temporary, "new_password": temporary},
        headers=_auth(session),
    )
    assert same.status_code == 400

    changed = client.post(
        "/users/password",
        data={"old_password": temporary, "new_password": "N3wPassw0rd"},
        headers=_auth(session),
    )
    assert changed.status_code == 200
    assert users.find_one({"username": "alice"})["must_change_password"] is False
    # the same session goes on, without the limit
    assert (
        client.post(
            "/jobs", data={"user_id": "alice"}, headers=_auth(session)
        ).status_code
        == 200
    )
    resp = client.post(
        "/users/login", data={"username": "alice", "password": "N3wPassw0rd"}
    )
    assert resp.get_json(force=True)["response"]["mustChangePassword"] is False


def test_the_login_says_the_password_must_change(client, user_factory, users):
    user_factory("alice")
    users.update_one({"username": "alice"}, {"$set": {"must_change_password": True}})
    resp = client.post(
        "/users/login", data={"username": "alice", "password": "pass123"}
    )
    assert resp.get_json(force=True)["response"]["mustChangePassword"] is True


def test_a_manager_resets_only_the_accounts_it_manages(
    client, user_factory, login, users
):
    user_factory("chef", role=MANAGER)
    user_factory("alice")
    user_factory("root", role=ADMIN)
    users.update_one({"username": "root"}, {"$set": {"managers": ["chef"]}})
    token = login("chef")
    for target in ("alice", "root", "nobody"):
        resp = client.post(
            "/users/reset_password",
            data={"user_id": "chef", "username": target},
            headers=_auth(token),
        )
        assert resp.status_code == 404, target
    # a plain user resets nobody
    user_factory("bob")
    resp = client.post(
        "/users/reset_password",
        data={"user_id": "bob", "username": "alice"},
        headers=_auth(login("bob")),
    )
    assert resp.status_code == 403


def test_an_admin_resets_anyone(client, user_factory, login):
    user_factory("root", role=ADMIN)
    user_factory("boss", role=ADMIN)
    resp = client.post(
        "/users/reset_password",
        data={"user_id": "root", "username": "boss"},
        headers=_auth(login("root")),
    )
    assert resp.status_code == 200


def test_an_impersonated_session_is_not_forced(client, user_factory, login, users):
    user_factory("root", role=ADMIN)
    user_factory("alice")
    users.update_one({"username": "alice"}, {"$set": {"must_change_password": True}})
    resp = client.post(
        "/users/impersonate",
        data={"user_id": "root", "username": "alice"},
        headers=_auth(login("root")),
    )
    session = resp.get_json(force=True)["response"]
    assert session["mustChangePassword"] is False
    jobs = client.post(
        "/jobs", data={"user_id": "alice"}, headers=_auth(session["token"])
    )
    assert jobs.status_code == 200


def test_only_an_admin_sets_the_managers(client, user_factory, login, users):
    user_factory("root", role=ADMIN)
    user_factory("chef", role=MANAGER)
    user_factory("autre", role=MANAGER)
    user_factory("alice")

    def set_managers(caller, managers, username="alice"):
        return client.post(
            "/users/managers",
            data={"user_id": caller, "username": username, "managers": managers},
            headers=_auth(login(caller)),
        )

    assert set_managers("chef", ["chef"]).status_code == 403
    resp = set_managers("root", ["chef", "autre"])
    assert resp.status_code == 200
    assert users.find_one({"username": "alice"})["managers"] == ["autre", "chef"]
    # only Gestionnaires manage
    assert set_managers("root", ["alice"]).status_code == 400
    assert set_managers("root", ["root"]).status_code == 400
    assert set_managers("root", ["chef"], username="nobody").status_code == 404
    # an empty list removes them all
    assert set_managers("root", []).status_code == 200
    assert users.find_one({"username": "alice"})["managers"] == []
