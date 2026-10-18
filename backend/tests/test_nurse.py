"""Nurse dashboard API: a resident's stored facts, consent to remember, forgetting, sessions and alerts."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.db import MemoryStore
from app.voice import live, memory

ROSE = "/api/participants/demo-rose"


@pytest.fixture
def bb(monkeypatch):
    """Fake Backboard holding one assistant (a1, Rose's) with a few memories. Records (method, path, body)."""
    calls: list = []
    mems = {"m1": {"content": "Loves Cary Grant", "kind": "care_profile"}, "m2": {"content": "Likes hot tea", "kind": "session"}}
    assistants = {"a1": "ReMind memory: demo-rose"}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        path = req.url.path.removeprefix("/api")
        calls.append((req.method, path, body))
        parts = path.strip("/").split("/")
        if parts == ["assistants"] and req.method == "GET":
            name = req.url.params.get("name")
            return httpx.Response(200, json=[{"assistant_id": a, "name": n} for a, n in assistants.items() if n == name])
        if parts == ["assistants"]:
            assistants["new1"] = body["name"]
            return httpx.Response(200, json={"assistant_id": "new1"})
        if len(parts) == 2:
            if parts[1] not in assistants:
                return httpx.Response(404)
            if req.method == "DELETE":
                del assistants[parts[1]]
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(200, json={"assistant_id": parts[1], "name": assistants[parts[1]]})
        if len(parts) == 3:
            if req.method == "POST":
                mems[f"m{len(mems) + 1}"] = {"content": body["content"], "kind": body["metadata"]["kind"]}
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200, json={"memories": [
                {"id": i, "content": m["content"], "metadata": {"kind": m["kind"]}, "created_at": "2026-10-18T09:00:00Z"}
                for i, m in mems.items()]})
        if len(parts) == 4 and parts[3] in mems:
            if req.method == "DELETE":
                del mems[parts[3]]
            else:
                mems[parts[3]] = {"content": body["content"], "kind": body["metadata"]["kind"]}
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    monkeypatch.setattr(settings, "backboard_api_key", "k")
    monkeypatch.setattr(settings, "backboard_url", "https://bb.test/api")
    monkeypatch.setattr(memory, "_transport", httpx.MockTransport(handler))
    return SimpleNamespace(calls=calls, mems=mems, assistants=assistants)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.settings, "mongodb_uri", "")
    with TestClient(main.app) as c:
        asyncio.run(main.app.state.store.update("participants", "demo-rose", {"backboardAssistantId": "a1"}))
        yield c


def test_residents_are_seeded_with_rooms(client):
    rooms = {p["alias"]: p.get("room") for p in client.get("/api/participants").json()}
    assert rooms["Rose"] == "12" and rooms["Arthur"] == "7"


def test_list_add_edit_delete_facts(client, bb):
    view = client.get(f"{ROSE}/memories").json()
    assert view["remember"] is True and view["assistantId"] == "a1"
    assert view["memories"][0] == {"id": "m1", "content": "Loves Cary Grant", "kind": "care_profile",
                                   "createdAt": "2026-10-18T09:00:00Z"}

    assert client.post(f"{ROSE}/memories", json={"content": " Rose's favourite food is hot dogs. "}).status_code == 200
    assert bb.calls[-1] == ("POST", "/assistants/a1/memories",
                            {"content": "Rose's favourite food is hot dogs.", "metadata": {"kind": "nurse"}})
    assert client.patch(f"{ROSE}/memories/m2", json={"content": "Likes milky tea"}).status_code == 200
    assert bb.calls[-1][:2] == ("PUT", "/assistants/a1/memories/m2") and bb.mems["m2"]["content"] == "Likes milky tea"
    assert client.delete(f"{ROSE}/memories/m1").status_code == 200
    assert "m1" not in bb.mems
    assert client.post(f"{ROSE}/memories", json={"content": ""}).status_code == 422


def test_consent_toggle_is_saved_and_blocks_new_facts(client, bb):
    p = client.put(f"{ROSE}/consent", json={"rememberPreferences": False}).json()
    assert p["consentFlags"] == {"sessionConsent": True, "rememberPreferences": False}
    assert client.get(ROSE).json()["consentFlags"]["rememberPreferences"] is False
    assert client.post(f"{ROSE}/memories", json={"content": "Likes jam"}).status_code == 409
    view = client.get(f"{ROSE}/memories").json()  # what is kept stays visible, so it can be forgotten
    assert view["remember"] is False and len(view["memories"]) == 2
    assert client.delete(f"{ROSE}/memories/m2").status_code == 200  # forgetting never needs consent
    assert client.put(f"{ROSE}/consent", json={"rememberPreferences": True}).json()["consentFlags"]["rememberPreferences"]
    assert client.post(f"{ROSE}/memories", json={"content": "Likes jam"}).status_code == 200


def test_memory_edits_need_backboard(client):
    assert client.post(f"{ROSE}/memories", json={"content": "Likes jam"}).status_code == 503
    assert client.put("/api/participants/nobody/consent", json={"rememberPreferences": False}).status_code == 404


def test_forget_everything_deletes_the_assistant_and_turns_consent_off(client, bb):
    p = client.delete(f"{ROSE}/memories").json()
    assert ("DELETE", "/assistants/a1", None) in bb.calls and "a1" not in bb.assistants
    assert p["backboardAssistantId"] is None and p["consentFlags"]["rememberPreferences"] is False
    assert client.get(f"{ROSE}/memories").json()["memories"] == []


def test_resident_sessions_and_acknowledge(client):
    store = main.app.state.store
    t = datetime(2026, 10, 18, 9, tzinfo=timezone.utc)
    for sid, pid, h in (("s1", "demo-rose", 9), ("s2", "demo-rose", 10), ("s3", "demo-tom", 11)):
        asyncio.run(store.insert("companion_sessions", {"_id": sid, "participantId": pid, "patientName": pid,
                                                        "startedAt": t.replace(hour=h), "endedAt": t.replace(hour=h),
                                                        "gamesPlayed": [], "observations": [], "alerts": ["Asked for help"]}))
    assert [s["_id"] for s in client.get(f"{ROSE}/sessions").json()] == ["s2", "s1"]
    assert client.post("/api/voice/sessions/s1/acknowledge").json()["acknowledgedAt"]
    assert client.post("/api/voice/sessions/nope/acknowledge").status_code == 404


async def test_live_writes_recheck_consent():
    """Consent turned off during a call: the remember tool's save and the after-call digest are dropped."""
    store = MemoryStore()
    await store.insert("participants", {"_id": "p1", "consentFlags": {"rememberPreferences": True}})
    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store)))
    wrote = []

    async def write(x):
        wrote.append(x)
    await live.if_still_remembering(ws, {"_id": "p1"}, write(1))
    await store.update("participants", "p1", {"consentFlags": {"rememberPreferences": False}})
    await live.if_still_remembering(ws, {"_id": "p1"}, write(2))
    await live.if_still_remembering(ws, {}, write(3))
    assert wrote == [1]
