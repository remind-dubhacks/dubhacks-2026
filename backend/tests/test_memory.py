"""Patient context: care profile -> prompt and pacing, and Backboard memory (mocked HTTP, no network)."""
import json

import httpx
import pytest

from app.config import settings
from app.main import DEMO_PARTICIPANT
from app.models import CareProfile
from app.voice import memory
from app.voice.live import NUDGE_AFTER_S, SLOW_VAD, VAD_PRESETS, build_setup, needs_slow_pacing
from app.voice.memory import provision  # the real one; conftest stubs memory.provision
from app.voice.prompts.voice_system_prompt import render_profile

ROSE = DEMO_PARTICIPANT["careProfile"]


def test_demo_profile_is_valid():
    assert CareProfile(**ROSE).pace == "slow"


def test_render_profile():
    text = render_profile("Rose", ROSE, ["Saw Roman Holiday three times with {her sister}."])
    assert text.startswith("\n\nABOUT ROSE")
    assert "Cary Grant" in text and "Who was your favourite leading man?" in text
    assert "never fill a silence quickly" in text  # pace=slow
    assert "loses a word" in text  # word_finding
    assert "Avoid raising: her late husband" in text
    assert "From earlier sessions: Saw Roman Holiday three times with {her sister}." in text
    assert "{name}" not in text
    assert render_profile("Ann", {}, []) == "" and render_profile("Ann", CareProfile().model_dump(), []) != ""


def test_stutter_note():
    assert "never finish their words" in render_profile("Bob", {"speech": ["stutter"]})


def test_build_setup_profile_and_pacing():
    setup = build_setup("Rose", ["faces"], vad="default", profile=ROSE, memories=["Loves {braces}."])["setup"]
    vad = setup["realtimeInputConfig"]["automaticActivityDetection"]
    assert vad == {**VAD_PRESETS["default"], **SLOW_VAD} and vad["silenceDurationMs"] >= 2000
    prompt = setup["systemInstruction"]["parts"][0]["text"]
    assert "Audrey Hepburn" in prompt and "Loves {braces}." in prompt
    plain = build_setup("Ann", ["faces"], vad="default")["setup"]
    assert plain["realtimeInputConfig"]["automaticActivityDetection"] == VAD_PRESETS["default"]
    assert "ABOUT" not in plain["systemInstruction"]["parts"][0]["text"]


def test_needs_slow_pacing():
    assert needs_slow_pacing({"speech": ["stutter"]}) and needs_slow_pacing({"pace": "slow"})
    assert not needs_slow_pacing({"speech": ["soft_voice"]}) and not needs_slow_pacing(None)
    assert NUDGE_AFTER_S < 45


EXISTING: dict[str, str] = {}  # assistant name -> id already on the fake Backboard account


@pytest.fixture
def backboard(monkeypatch):
    """Fake Backboard: records requests, answers like the documented API (and the backboard-sdk client)."""
    calls = []
    EXISTING.clear()

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else None
        calls.append((req.method, req.url.path, body, req.headers.get("X-API-Key")))
        if req.url.host != "bb.test":
            return httpx.Response(599)  # nothing may bypass Backboard
        if req.url.path.endswith("/threads/messages"):  # digest fact extraction
            facts = ["Rose loves Cary Grant.", "Rose's daughter Linda visits on Sundays."]
            return httpx.Response(200, json={"thread_id": "t1", "messages": [{"role": "assistant", "content": json.dumps(facts)}]})
        if req.method == "GET" and req.url.path.endswith("/assistants"):
            name = req.url.params.get("name")
            return httpx.Response(200, json=[{"assistant_id": EXISTING[name], "name": name}] if name in EXISTING else [])
        if req.url.path.endswith("/assistants"):
            return httpx.Response(200, json={"assistant_id": "a1"})
        if req.url.path.endswith("/memories/search") or (req.method == "GET" and req.url.path.endswith("/memories")):
            return httpx.Response(200, json={"memories": [{"id": "m1", "content": "Loves Cary Grant"}], "total_count": 1})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(settings, "backboard_api_key", "k")
    monkeypatch.setattr(settings, "backboard_url", "https://bb.test/api")
    monkeypatch.setattr(memory, "_transport", httpx.MockTransport(handler))
    return calls


async def test_recall_and_add(backboard):
    assert await memory.recall("a1", "movie stars") == ["Loves Cary Grant"]
    assert backboard[-1][:3] == ("POST", "/api/assistants/a1/memories/search", {"query": "movie stars", "limit": memory.RECALL_LIMIT})
    assert backboard[-1][3] == "k"
    assert await memory.recall("a1") == ["Loves Cary Grant"] and backboard[-1][0] == "GET"
    assert await memory.recall(None) == []
    assert await memory.add("a1", "Daughter is Linda.")
    assert backboard[-1][2] == {"content": "Daughter is Linda.", "metadata": {"kind": "fact"}}


async def test_ensure_assistant_creates_and_seeds(backboard):
    from app.db import MemoryStore
    store = MemoryStore()
    p = {"_id": "p1", "alias": "Rose", "careProfile": ROSE}
    await store.insert("participants", dict(p))
    assert await memory.ensure_assistant(store, p) == "a1"
    assert (await store.get("participants", "p1"))["backboardAssistantId"] == "a1"
    find, create = backboard[0], backboard[1]
    assert find[:2] == ("GET", "/api/assistants")  # looked up by name first
    assert create[1] == "/api/assistants" and create[2]["name"] == "ReMind memory: p1"
    assert create[2]["custom_fact_extraction_prompt"] == memory.FACT_PROMPT
    seeded = [c[2]["content"] for c in backboard if c[1] == "/api/assistants/a1/memories"]
    assert len(seeded) == len(memory.profile_memories(ROSE)) and any("Cary Grant" in s for s in seeded)
    assert await memory.ensure_assistant(store, p) == "a1" and len(backboard) == 2 + len(seeded)  # no second create


async def test_ensure_assistant_relinks_existing_without_seeding(backboard):
    """Our store lost the id (in-memory store after a restart): the assistant Backboard already has is re-linked, its
    memories kept, and the care profile is not seeded a second time."""
    from app.db import MemoryStore
    store = MemoryStore()
    EXISTING["ReMind memory: p1"] = "old1"
    p = {"_id": "p1", "alias": "Rose", "careProfile": ROSE}
    await store.insert("participants", dict(p))
    assert await memory.ensure_assistant(store, p) == "old1"
    assert (await store.get("participants", "p1"))["backboardAssistantId"] == "old1"
    assert [c[:2] for c in backboard] == [("GET", "/api/assistants")]


async def test_provision_covers_consenting_participants(backboard):
    from app.db import MemoryStore
    store = MemoryStore()
    await store.insert("participants", {"_id": "yes", "consentFlags": {"rememberPreferences": True}})
    await store.insert("participants", {"_id": "no", "consentFlags": {"rememberPreferences": False}})
    await provision(store)
    assert (await store.get("participants", "yes"))["backboardAssistantId"] == "a1"
    assert "backboardAssistantId" not in await store.get("participants", "no")


async def test_off_without_key_and_on_errors(monkeypatch):
    monkeypatch.setattr(settings, "backboard_api_key", "")
    assert await memory.recall("a1", "x") == [] and not await memory.add("a1", "x")
    monkeypatch.setattr(settings, "backboard_api_key", "k")
    monkeypatch.setattr(memory, "_transport", httpx.MockTransport(lambda r: httpx.Response(500)))
    assert await memory.recall("a1", "x") == []

    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)
    monkeypatch.setattr(memory, "_transport", httpx.MockTransport(timeout))
    assert await memory.recall("a1") == [] and await memory.create_assistant("Rose") is None


def test_is_known_matches_rewordings_not_new_facts():
    known = ["Married husband Harold in 1962 in Brighton.", "Rose likes tea."]
    assert memory.is_known("Rose married her husband Harold in 1962 in Brighton.", known, "Rose")
    assert not memory.is_known("Rose likes coffee.", known, "Rose")  # shares the name and "likes", not the fact
    assert not memory.is_known("Granddaughter Lily plays the violin.", known, "Rose")


async def test_digest_session_saves_only_new_facts(backboard, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "g")  # set, but extraction must still go through Backboard
    saved = await memory.digest_session("a1", "Rose", ["I do love Cary Grant.", "Linda comes every Sunday."])
    assert saved == ["Rose's daughter Linda visits on Sundays."]  # "loves Cary Grant" is already remembered
    assert all(c[3] == "k" for c in backboard)  # every request went to Backboard
    msg = next(c for c in backboard if c[1] == "/api/threads/messages")[2]
    assert msg["assistant_id"] == "a1" and msg["memory"] == "off" and msg["json_output"] is True
    assert msg["system_prompt"] == memory.DIGEST_PROMPT and "llm_provider" not in msg  # default model unless configured
    assert "Linda comes every Sunday." in msg["content"] and "Loves Cary Grant" in msg["content"]  # said + known
    adds = [c[2] for c in backboard if c[0] == "POST" and c[1] == "/api/assistants/a1/memories"]
    assert adds == [{"content": "Rose's daughter Linda visits on Sundays.", "metadata": {"kind": "session"}}]


async def test_digest_model_setting_and_object_replies(backboard, monkeypatch):
    monkeypatch.setattr(settings, "backboard_digest_model", "google/some-flash-model")
    monkeypatch.setattr(memory, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={
        "content": json.dumps({"facts": ["Rose's favourite food is hot dogs."]}), "thread_id": "t1"})))
    assert await memory.extract_facts("a1", "Rose", ["My favourite food is hot dogs."], []) == ["Rose's favourite food is hot dogs."]
    assert memory._digest_model() == {"llm_provider": "google", "model_name": "some-flash-model"}


async def test_digest_session_skips_without_input(backboard, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "g")
    assert await memory.digest_session(None, "Rose", ["hello"]) == []
    assert await memory.digest_session("a1", "Rose", []) == []
    assert backboard == []
