"""The download link built by ``/file/share`` follows the request's host."""

import pytest


def _share(client, token, host):
    return client.post(
        "/files/share",
        data={"user_id": "alice", "token": token, "job_id": "job1", "file": "csv"},
        headers={"Host": host},
    )


@pytest.mark.parametrize(
    "host,scheme",
    [
        ("localhost", "http"),
        ("localhost:8085", "http"),
        ("127.0.0.1:8085", "http"),
        ("rmn.example.org", "https"),
        ("rmn.example.org:8443", "https"),
    ],
)
def test_share_url_scheme_follows_host(
    client, user_factory, job_factory, login, app_module_fixture, host, scheme
):
    user_factory("alice")
    job_factory("job1", owner="alice")
    app_module_fixture.mongo["RMN"]["jobs_output"].insert_one(
        {"job_id": "job1", "user_id": "alice", "zip_id_list": []}
    )
    token = login("alice")

    resp = _share(client, token, host)

    assert resp.status_code == 200, resp.data
    url = resp.get_json(force=True)["response"]["share_url"]
    assert url.startswith(f"{scheme}://{host}/api/file/download?job_id=job1&")
