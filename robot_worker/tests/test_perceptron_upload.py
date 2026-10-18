"""Upload + train flow against a mock Perceptron API that enforces the participant OpenAPI rules."""

import json
import re

import httpx
import pytest

from worker import studio

HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MockPerceptron:
    def __init__(self):
        self.calls, self.put_paths, self.keys = [], [], []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, body = req.url.path, json.loads(req.content or b"{}")
        self.calls.append((req.method, path))
        assert req.headers["authorization"] == "Bearer test-key"
        if req.method == "POST" and path == "/v1/datasets":
            assert set(body) <= {"name", "source_kind", "repo_id", "revision"}  # additionalProperties: false
            assert 1 <= len(body["name"]) <= 100
            self.keys.append(req.headers["idempotency-key"])
            # Simulate an async operation answered with a same-origin 303 to a polling URL.
            return httpx.Response(303, headers={"Location": "/v1/operations/op1?sig=abc"})
        if req.method == "GET" and path == "/v1/operations/op1":
            assert req.url.params["sig"] == "abc"  # query string kept exactly
            return httpx.Response(200, json={"id": "ds_123", "status": "pending_upload"})
        if path == "/v1/datasets/ds_123/uploads":
            files = body["files"]
            assert set(body) == {"files"} and 1 <= len(files) <= 500
            for f in files:
                assert set(f) == {"path", "size_bytes", "sha256"} and f["size_bytes"] >= 1 and HEX64.match(f["sha256"])
            return httpx.Response(200, json={"files": [{"path": f["path"], "url": f"https://signed.example/{f['path']}", "method": "PUT", "headers": {"Content-Length": str(f["size_bytes"])}} for f in files]})
        if path == "/v1/datasets/ds_123/finalize":
            return httpx.Response(202, json={"id": "ds_123", "status": "validating"})
        if path == "/v1/jobs":
            assert body["action_horizon"] in (20, 30) and 1 <= body["steps"] <= 10000
            assert set(body) <= {"dataset_id", "backend", "mode", "action_horizon", "rtc_enabled", "steps"}
            return httpx.Response(202, json={"id": "job_1", "status": "queued"})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})


@pytest.fixture
def api(tmp_path, monkeypatch):
    repo = tmp_path / "team" / "remind-sort"
    (repo / "meta").mkdir(parents=True)
    (repo / "meta/info.json").write_text(json.dumps({"total_episodes": 3}))
    (repo / "data/chunk-000").mkdir(parents=True)
    (repo / "data/chunk-000/file-000.parquet").write_bytes(b"x" * 10)
    (repo / "meta/empty.txt").write_bytes(b"")  # zero-byte: must be skipped
    monkeypatch.setattr(studio, "DATA_HOME", tmp_path)
    monkeypatch.setenv("PERCEPTRON_API_KEY", "test-key")
    mock = MockPerceptron()
    real_client = httpx.Client
    monkeypatch.setattr(studio, "pc", lambda: real_client(base_url="https://robotics.perceptron.inc", headers={"Authorization": "Bearer test-key"},
                                                           transport=httpx.MockTransport(mock.handler), follow_redirects=True))

    def fake_put(method, url, headers, content, timeout):
        assert "authorization" not in {k.lower() for k in headers}  # never send the team key to signed URLs
        assert int(headers["Content-Length"]) == len(content)
        mock.put_paths.append(url.rsplit("/", 1)[-1] if "/" in url else url)
        return httpx.Response(200)

    monkeypatch.setattr(studio.httpx, "request", fake_put)
    return mock


def test_upload_follows_schema_and_finalizes(api):
    studio.uploads["team/remind-sort"] = {"phase": "starting", "done": 0, "total": 0}
    studio._upload("team/remind-sort")
    u = studio.uploads["team/remind-sort"]
    assert u["phase"] == "finalized", u
    assert u["datasetId"] == "ds_123" and u["done"] == u["total"] == 2  # empty file skipped
    assert ("POST", "/v1/datasets/ds_123/finalize") in api.calls


def test_retry_uses_same_idempotency_key(api):
    for _ in range(2):
        studio.uploads["team/remind-sort"] = {"phase": "starting", "done": 0, "total": 0}
        studio._upload("team/remind-sort")
    assert api.keys[0] == api.keys[1] == "upload-team-remind-sort-3ep"


def test_train_validates_limits(api):
    assert studio.train(studio.TrainIn(datasetId="ds_123", steps=1000))["id"] == "job_1"
    with pytest.raises(Exception):
        studio.TrainIn(datasetId="ds_123", steps=20000)
    with pytest.raises(Exception):
        studio.TrainIn(datasetId="ds_123", actionHorizon=25)


def test_api_error_message_is_readable(api):
    with pytest.raises(studio.HTTPException) as e:
        studio.dataset_status("missing")
    assert "not_found" in e.value.detail
