import pytest
from fastapi.testclient import TestClient

from app import main, robot_client


class FakeWorker:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.stopped = False

    async def health(self):
        return {"ready": True, "busy": False, "mode": "fake"}

    async def submit(self, job_id, action_id, object_id):
        self.jobs[job_id] = {"status": "verifying"}
        return self.jobs[job_id]

    async def status(self, job_id):
        return self.jobs[job_id]

    async def stop(self):
        self.stopped = True
        return {}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.settings, "mongodb_uri", "")
    fake = FakeWorker()
    for name in ("health", "submit", "status", "stop"):
        monkeypatch.setattr(robot_client, name, getattr(fake, name))
    with TestClient(main.app) as c:
        c.fake = fake
        yield c


def start(client):
    r = client.post("/api/sessions", json={"participantId": "demo-rose", "caregiverApproved": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_requires_caregiver_approval(client):
    r = client.post("/api/sessions", json={"participantId": "demo-rose"})
    assert r.status_code == 403


def test_full_tea_flow(client):
    sess = start(client)
    assert sess["state"] == "prompting"

    turn = client.post("/api/agent/turn", json={"sessionId": sess["_id"], "text": "I'd like tea please"}).json()
    assert turn["turn"]["intent"] == "select_object"
    assert turn["turn"]["objectId"] == "tea_box"
    assert turn["session"]["state"] == "validated"

    job = client.post("/api/robot/jobs", json={"sessionId": sess["_id"], "objectId": "tea_box"}).json()
    polled = client.get(f"/api/robot/jobs/{job['_id']}").json()
    # The worker finished moving, but success is not claimed until a caregiver confirms.
    assert polled["status"] == "verifying"
    assert polled["sessionState"] == "verifying"
    assert "tray" not in (polled["reply"] or "")

    done = client.post(f"/api/robot/jobs/{job['_id']}/verify", json={"success": True}).json()
    assert done["status"] == "succeeded"
    assert done["sessionState"] == "complete"
    assert "tea in the tray" in done["reply"]

    p = client.get("/api/participants/demo-rose").json()
    assert p["preferences"]["favoriteObjectId"] == "tea_box"


def test_rejects_unvalidated_object(client):
    sess = start(client)
    r = client.post("/api/robot/jobs", json={"sessionId": sess["_id"], "objectId": "coffee_box"})
    assert r.status_code == 409


def test_rejects_object_not_in_activity(client):
    sess = start(client)
    turn = client.post("/api/agent/turn", json={"sessionId": sess["_id"], "text": "sugar"}).json()
    assert turn["turn"]["intent"] == "unclear"
    assert turn["session"]["state"] == "prompting"


def test_failed_verification_needs_staff(client):
    sess = start(client)
    client.post("/api/agent/turn", json={"sessionId": sess["_id"], "text": "coffee"})
    job = client.post("/api/robot/jobs", json={"sessionId": sess["_id"], "objectId": "coffee_box"}).json()
    client.get(f"/api/robot/jobs/{job['_id']}")
    r = client.post(f"/api/robot/jobs/{job['_id']}/verify", json={"success": False}).json()
    assert r["sessionState"] == "needs_staff"
    # No new selections while staff are needed.
    t = client.post("/api/agent/turn", json={"sessionId": sess["_id"], "text": "tea"}).json()
    assert t["session"]["state"] == "needs_staff"
    assert client.post(f"/api/sessions/{sess['_id']}/resume").json()["state"] == "prompting"


def test_stop_by_voice(client):
    sess = start(client)
    r = client.post("/api/agent/turn", json={"sessionId": sess["_id"], "text": "stop please"}).json()
    assert r["session"]["state"] == "stopped"
    assert client.fake.stopped
    t = client.post("/api/agent/turn", json={"sessionId": sess["_id"], "text": "tea"}).json()
    assert t["session"]["state"] == "stopped"


def test_delete_participant(client):
    sess = start(client)
    client.post("/api/feedback", json={"sessionId": sess["_id"], "enjoyed": True})
    r = client.delete("/api/participants/demo-rose").json()
    assert r["deleted"]["participants"] == 1
    assert r["deleted"]["sessions"] == 1
    assert r["deleted"]["feedback"] == 1
    assert client.get("/api/participants/demo-rose").status_code == 404
