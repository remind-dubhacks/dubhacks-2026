from fastapi.testclient import TestClient

from app import main
from app.voice import agent


def post(c, text, table=None):
    return c.post("/api/voice/turn", json={"sessionId": "t", "text": text, "tableOrder": table}).json()


def test_voice_flow_rules(monkeypatch):
    async def no_llm(messages):
        return None
    monkeypatch.setattr(agent, "_chat", no_llm)
    with TestClient(main.app) as c:
        r = post(c, "let's play the ordering game")
        assert r["toolCalls"][0]["name"] == "start_game" and r["state"]["phase"] == "awaiting"
        target = r["state"]["target"]
        r = post(c, "I'm done", r["state"]["shuffledOrder"])
        assert r["toolCalls"][0]["name"] == "check_arrangement" and not r["toolCalls"][0]["result"]["correct"]
        r = post(c, "done", target)
        assert r["state"]["result"] == "correct"
        assert post(c, "stop")["state"]["phase"] == "stopped"
