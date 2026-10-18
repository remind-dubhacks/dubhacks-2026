from fastapi.testclient import TestClient

from app import main
from app.voice import agent


def post(c, text, table=None):
    return c.post("/api/voice/turn", json={"sessionId": "t", "text": text, "tableOrder": table}).json()


def test_voice_flow_rules(monkeypatch):
    monkeypatch.setattr(agent.settings, "gemini_api_key", "")
    with TestClient(main.app) as c:
        r = post(c, "let's play the ordering game")
        assert r["toolCalls"][0]["name"] == "start_game" and r["state"]["phase"] == "awaiting"
        target = r["state"]["target"]
        r = post(c, "I'm done", r["state"]["shuffledOrder"])
        assert r["toolCalls"][0]["name"] == "check_arrangement" and not r["toolCalls"][0]["result"]["correct"]
        r = post(c, "done", target)
        assert r["state"]["result"] == "correct"
        assert post(c, "stop")["state"]["phase"] == "stopped"


def test_gemini_tool_loop(monkeypatch):
    monkeypatch.setattr(agent.settings, "gemini_api_key", "k")
    script = [
        {"role": "model", "parts": [{"functionCall": {"name": "start_game", "args": {"game_id": "reorder"}}}]},
        {"role": "model", "parts": [{"text": "Let's play! Put the cup, apple, then book."}]},
    ]
    seen = []

    async def fake(contents, system):
        seen.append(len(contents))
        return script[len(seen) - 1]

    monkeypatch.setattr(agent, "_gemini", fake)
    import sys
    sys.modules["app.voice.router"].SESSIONS.clear()
    with TestClient(main.app) as c:
        r = post(c, "play the ordering game")
        assert r["toolCalls"][0]["name"] == "start_game" and r["state"]["phase"] == "awaiting"
        assert r["reply"].startswith("Let's play")
        assert seen == [1, 3]  # user, then user+functionCall+functionResponse


def test_gemini_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(agent.settings, "gemini_api_key", "k")

    async def boom(contents, system):
        raise RuntimeError("quota")

    monkeypatch.setattr(agent, "_gemini", boom)
    with TestClient(main.app) as c:
        r = post(c, "let's play the game")
    assert r["state"]["phase"] == "awaiting"


def test_tts_needs_key(monkeypatch):
    monkeypatch.setattr(agent.settings, "elevenlabs_api_key", "")
    with TestClient(main.app) as c:
        assert c.post("/api/voice/tts", json={"text": "hi"}).status_code == 503


def test_tool_catalog():
    with TestClient(main.app) as c:
        names = [t["name"] for t in c.get("/api/voice/tools").json()]
    assert names == ["list_games", "start_game", "check_arrangement", "exercise_step", "alert_caregiver", "stop"]
