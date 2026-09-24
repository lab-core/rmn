"""Correcting the student number read off a copy, and the link that shares it.

The owner and a matricule ("mat") or job-wide ("all") share link may correct a
copy; a question link may not, nor may another user. The link itself is
created and revoked by the owner only.
"""

import json

import pytest


@pytest.fixture
def job(job_factory, user_factory, app_module_fixture):
    user_factory("alice")
    job_factory(
        "j1", "alice", share_token={"mat": "tok-mat", "all": "tok-all", "1": "tok-q1"}
    )
    app_module_fixture.mongo["RMN"]["job_documents"].insert_one(
        {
            "job_id": "j1",
            "document_index": 0,
            "matricule": "111",
            "status": "TO VALIDATE",
        }
    )
    return app_module_fixture


def _doc(app_module):
    return app_module.mongo["RMN"]["job_documents"].find_one(
        {"job_id": "j1", "document_index": 0}
    )


def _update(client, **auth):
    return client.post(
        "/matricules/update",
        data={"job_id": "j1", "document_index": "0", "matricule": "1234567", **auth},
    )


def test_owner_corrects_the_matricule_and_validates_the_copy(client, job, login):
    job.sio.emit.reset_mock()
    resp = _update(client, token=login("alice"))

    assert resp.status_code == 200, resp.data
    doc = _doc(job)
    assert (doc["matricule"], doc["status"]) == ("1234567", "VALIDATED")
    event, payload = job.sio.emit.call_args.args
    assert event == "doc_validated"
    assert json.loads(payload) == {
        "job_id": "j1",
        "user_id": "alice",
        "document_index": 0,
        "matricule": True,
    }


@pytest.mark.parametrize("share_token", ["tok-mat", "tok-all"])
def test_a_matricule_or_job_wide_link_may_correct_the_matricule(
    client, job, share_token
):
    resp = _update(client, share_token=share_token)
    assert resp.status_code == 200, resp.data
    assert _doc(job)["matricule"] == "1234567"


@pytest.mark.parametrize("share_token", ["tok-q1", "garbage"])
def test_a_question_link_or_a_bad_token_cannot_touch_the_matricule(
    client, job, share_token
):
    resp = _update(client, share_token=share_token, question_index="1")
    assert resp.status_code == 401
    assert _doc(job)["matricule"] == "111"


def test_another_user_cannot_correct_the_matricule(client, job, user_factory, login):
    user_factory("bob")
    resp = _update(client, token=login("bob"))
    assert resp.status_code == 401
    assert _doc(job)["matricule"] == "111"


@pytest.mark.parametrize("missing", ["document_index", "matricule"])
def test_update_requires_every_field(client, job, login, missing):
    data = {"job_id": "j1", "document_index": "0", "matricule": "1", "token": login()}
    del data[missing]
    resp = client.post("/matricules/update", data=data)
    assert resp.status_code == 400
    assert missing in resp.get_json(force=True)["response"]


def test_owner_sets_the_status_of_a_copy(client, job, login):
    resp = client.post(
        "/matricules/status/update",
        data={
            "job_id": "j1",
            "document_index": "0",
            "status": "HIGH ACCURACY",
            "token": login(),
        },
    )
    assert resp.status_code == 200, resp.data
    assert _doc(job)["status"] == "HIGH ACCURACY"
    # the matricule itself is untouched
    assert _doc(job)["matricule"] == "111"


def test_a_matricule_link_may_set_the_status(client, job):
    resp = client.post(
        "/matricules/status/update",
        data={
            "job_id": "j1",
            "document_index": "0",
            "status": "VALIDATED",
            "share_token": "tok-mat",
        },
    )
    assert resp.status_code == 200
    assert _doc(job)["status"] == "VALIDATED"


def test_an_unknown_status_is_refused(client, job, login):
    resp = client.post(
        "/matricules/status/update",
        data={
            "job_id": "j1",
            "document_index": "0",
            "status": "NOT_READY",
            "token": login(),
        },
    )
    assert resp.status_code == 400
    assert _doc(job)["status"] == "TO VALIDATE"


def test_status_update_requires_the_status(client, job, login):
    resp = client.post(
        "/matricules/status/update",
        data={"job_id": "j1", "document_index": "0", "token": login()},
    )
    assert resp.status_code == 400


def test_a_question_link_cannot_set_the_status(client, job):
    resp = client.post(
        "/matricules/status/update",
        data={
            "job_id": "j1",
            "document_index": "0",
            "status": "VALIDATED",
            "share_token": "tok-q1",
            "question_index": "1",
        },
    )
    assert resp.status_code == 401
    assert _doc(job)["status"] == "TO VALIDATE"


# ------------------------------------------------------------- share link ---
def _share(client, token, job_id="j1", host="rmn.example.org"):
    return client.post(
        "/matricules/share",
        data={"job_id": job_id, "token": token},
        headers={"Host": host},
    )


def test_share_creates_a_mat_token_once_and_reuses_it(
    client, user_factory, job_factory, login, app_module_fixture
):
    user_factory("alice")
    job_factory("j1", "alice", groups=["A", "B"])
    token = login()

    first = _share(client, token)
    assert first.status_code == 200, first.data
    body = first.get_json(force=True)["response"]
    stored = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    mat = stored["share_token"]["mat"]
    assert body["share_url"] == (
        f"https://rmn.example.org/matricule-validation/?job_id=j1&token={mat}"
    )
    assert body["groups"] == ["A", "B"]

    again = _share(client, token).get_json(force=True)["response"]
    assert again["share_url"] == body["share_url"]


def test_share_adds_mat_next_to_the_existing_question_links(
    client, job_factory, user_factory, login, app_module_fixture
):
    user_factory("alice")
    job_factory("j1", "alice", share_token={"1": "tok-q1"})

    resp = _share(client, login(), host="localhost:8085")

    assert resp.status_code == 200
    url = resp.get_json(force=True)["response"]["share_url"]
    assert url.startswith("http://localhost:8085/matricule-validation/?job_id=j1&")
    assert resp.get_json(force=True)["response"]["groups"] == [""]
    tokens = app_module_fixture.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})[
        "share_token"
    ]
    assert tokens["1"] == "tok-q1"
    assert url.endswith(f"token={tokens['mat']}")


def test_another_user_cannot_share_the_matricule_page(client, job, user_factory, login):
    user_factory("bob")
    resp = _share(client, login("bob"))
    assert resp.status_code == 404
    stored = job.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})
    assert stored["share_token"]["mat"] == "tok-mat"


def test_share_requires_a_job_id_and_a_host(client, job, login):
    token = login()
    assert client.post("/matricules/share", data={"token": token}).status_code == 400
    # the test client always sends a Host: blank it explicitly
    resp = client.post(
        "/matricules/share", data={"job_id": "j1", "token": token}, headers={"Host": ""}
    )
    assert resp.status_code == 400


def test_share_requires_a_login(client, job):
    resp = client.post("/matricules/share", data={"job_id": "j1", "token": "tok-mat"})
    assert resp.status_code == 401


def test_unshare_revokes_only_the_mat_link(client, job, login):
    resp = client.post("/matricules/unshare", data={"job_id": "j1", "token": login()})

    assert resp.status_code == 200
    tokens = job.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})["share_token"]
    assert tokens == {"all": "tok-all", "1": "tok-q1"}
    assert _update(client, share_token="tok-mat").status_code == 401


def test_another_user_cannot_unshare(client, job, user_factory, login):
    user_factory("bob")
    resp = client.post(
        "/matricules/unshare", data={"job_id": "j1", "token": login("bob")}
    )
    assert resp.status_code == 404
    tokens = job.mongo["RMN"]["eval_jobs"].find_one({"job_id": "j1"})["share_token"]
    assert tokens["mat"] == "tok-mat"


def test_unshare_requires_a_job_id(client, job, login):
    assert client.post("/matricules/unshare", data={"token": login()}).status_code == 400
