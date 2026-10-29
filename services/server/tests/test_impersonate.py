"""An admin taking the place of another user, and coming back."""

ADMIN = "Administrateur"
USER = "Utilisateur"


def _impersonate(client, admin, token, username):
    return client.post(
        "/users/impersonate",
        data={"user_id": admin, "username": username},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_only_an_admin_may_impersonate(client, user_factory, login):
    user_factory("alice")
    user_factory("bob")
    token = login("alice")
    resp = _impersonate(client, "alice", token, "bob")
    # a role too low is refused without ending the session
    assert resp.status_code == 403 and resp.get_json(force=True)["code"] == "forbidden"


def test_the_session_is_the_users_own(
    client, user_factory, job_factory, login, app_module_fixture
):
    user_factory("root", role=ADMIN)
    user_factory("alice")
    job_factory("job-a", "alice", queued_time="2026-10-28")
    token = login("root")

    resp = _impersonate(client, "root", token, "alice")
    assert resp.status_code == 200
    session = resp.get_json(force=True)["response"]
    assert session["username"] == "alice" and session["role"] == USER
    assert session["impersonatedBy"] == "root"
    record = app_module_fixture.mongo["RMN"]["tokens"].find_one(
        {"token": session["token"]}
    )
    assert record["username"] == "alice" and record["impersonated_by"] == "root"

    # alice's routes answer as for alice, writes included
    headers = {"Authorization": f"Bearer {session['token']}"}
    jobs = client.post("/jobs", data={"user_id": "alice"}, headers=headers)
    assert jobs.status_code == 200
    assert [j["job_id"] for j in jobs.get_json(force=True)["response"]] == ["job-a"]
    resp = client.put(
        "/users/updateSaveVerifiedImages",
        data={"username": "alice", "saveVerifiedImages": "1"},
        headers=headers,
    )
    assert resp.status_code == 200
    # and the admin's own session still works
    assert (
        client.get(
            "/users/all", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 200
    )


def test_an_admin_can_be_impersonated_and_the_chain_keeps_its_origin(
    client, user_factory, login
):
    user_factory("root", role=ADMIN)
    user_factory("boss", role=ADMIN)
    user_factory("alice")
    token = login("root")

    boss = _impersonate(client, "root", token, "boss").get_json(force=True)["response"]
    assert boss["role"] == ADMIN and boss["impersonatedBy"] == "root"

    alice = _impersonate(client, "boss", boss["token"], "alice").get_json(force=True)[
        "response"
    ]
    assert alice["impersonatedBy"] == "root"

    # becoming the origin again is a plain session
    back = _impersonate(client, "boss", boss["token"], "root").get_json(force=True)[
        "response"
    ]
    assert back["username"] == "root" and "impersonatedBy" not in back


def test_unknown_or_missing_user(client, user_factory, login):
    user_factory("root", role=ADMIN)
    token = login("root")
    assert _impersonate(client, "root", token, "nobody").status_code == 404
    resp = client.post(
        "/users/impersonate",
        data={"user_id": "root"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_users_list_is_for_managers_and_admins(client, user_factory, login):
    user_factory("root", role=ADMIN)
    user_factory("Bob")
    user_factory("alice")
    assert (
        client.get(
            "/users/all", headers={"Authorization": f"Bearer {login('alice')}"}
        ).status_code
        == 403
    )

    resp = client.get(
        "/users/all", headers={"Authorization": f"Bearer {login('root')}"}
    )
    assert resp.status_code == 200
    assert resp.get_json(force=True)["response"] == [
        {
            "username": "alice",
            "role": USER,
            "managers": [],
            "mustChangePassword": False,
        },
        {"username": "Bob", "role": USER, "managers": [], "mustChangePassword": False},
        {
            "username": "root",
            "role": ADMIN,
            "managers": [],
            "mustChangePassword": False,
        },
    ]


def test_logout_deletes_only_that_token(
    client, user_factory, login, app_module_fixture
):
    user_factory("alice")
    first, second = login("alice"), login("alice")
    resp = client.post("/users/logout", headers={"Authorization": f"Bearer {first}"})
    assert resp.status_code == 200
    tokens = app_module_fixture.mongo["RMN"]["tokens"]
    assert tokens.find_one({"token": first}) is None
    assert tokens.find_one({"token": second}) is not None
    assert (
        client.post(
            "/users/logout", headers={"Authorization": f"Bearer {first}"}
        ).status_code
        == 401
    )
