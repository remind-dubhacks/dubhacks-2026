"""Live relay against a fake Gemini Live server (no network, no key)."""
import asyncio
import base64
import json
import threading

import websockets
from fastapi.testclient import TestClient

from app import main
from app.config import settings


START_GAME = [{"id": "c1", "name": "start_game", "args": {"game_id": "reorder"}}]


def fake_gemini(port_holder: list, received: list, calls: list | None = None):
    calls = calls or START_GAME

    async def handler(ws):
        async for raw in ws:
            ev = json.loads(raw)
            received.append(ev)
            if "setup" in ev:
                await ws.send(json.dumps({"setupComplete": {}}))
            elif "realtimeInput" in ev and "text" in ev["realtimeInput"] and sum("text" in e.get("realtimeInput", {}) for e in received) == 1:
                send = lambda o: ws.send(json.dumps(o))  # noqa: E731
                await send({"serverContent": {"inputTranscription": {"text": "play the ordering game"}}})
                await send({"toolCall": {"functionCalls": calls}})
            elif "toolResponse" in ev:
                send = lambda o: ws.send(json.dumps(o))  # noqa: E731
                await send({"serverContent": {"outputTranscription": {"text": "Put the cup first."},
                                              "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(b"\x00\x01" * 4).decode()}}]}}})
                await send({"serverContent": {"turnComplete": True}})

    async def main_():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port_holder.append(server.sockets[0].getsockname()[1])
            await asyncio.Future()

    asyncio.run(main_())


def test_live_relay(monkeypatch):
    port, received = [], []
    threading.Thread(target=fake_gemini, args=(port, received), daemon=True).start()
    for _ in range(50):
        if port:
            break
        threading.Event().wait(0.05)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port[0]}")

    got = []
    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live") as ws:
        ws.send_bytes(b"\x00\x00" * 10)
        while not any(m["type"] == "ai_done" for m in got):
            got.append(ws.receive_json())
    types = [m["type"] for m in got]
    assert {"tool", "user_text", "audio", "ai_done"} <= set(types)
    assert next(m for m in got if m["type"] == "tool")["state"]["phase"] == "awaiting"
    setup = received[0]["setup"]
    assert setup["tools"][0]["functionDeclarations"][0]["name"] == "list_games" and "inputAudioTranscription" in setup
    assert any("audio" in e.get("realtimeInput", {}) for e in received)
    assert any("toolResponse" in e for e in received)


def test_build_setup_uses_settings():
    from app.voice.live import VAD_PRESETS, build_setup
    gen = build_setup("Ann", ["faces"])["setup"]["generationConfig"]
    assert gen["temperature"] == settings.gemini_live_temperature and gen["maxOutputTokens"] == settings.gemini_live_max_output_tokens
    setup = build_setup("Ann", ["faces"], vad="default")["setup"]
    assert setup["realtimeInputConfig"]["automaticActivityDetection"] == VAD_PRESETS["default"]
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] == 1200
    assert "outputAudioTranscription" in setup and "Ann" in setup["systemInstruction"]["parts"][0]["text"]
    legacy = build_setup("Ann", ["faces"], vad="legacy", temperature=-1, max_output_tokens=0)["setup"]["generationConfig"]
    assert "temperature" not in legacy and "maxOutputTokens" not in legacy


def test_should_remind(monkeypatch):
    from app.voice.live import should_remind
    monkeypatch.setattr(settings, "gemini_live_remind_every", 8)
    monkeypatch.setattr(settings, "gemini_live_remind_words", 40)
    assert should_remind(8, 0, [])
    assert not should_remind(8, 8, [])  # already reminded at this turn
    assert not should_remind(3, 0, [50])
    assert should_remind(3, 0, [41, 60])
    assert not should_remind(3, 0, [41, 12])


def test_live_relay_sends_reminder_without_turn_complete(monkeypatch):
    port, received = [], []
    threading.Thread(target=fake_gemini, args=(port, received), daemon=True).start()
    for _ in range(50):
        if port:
            break
        threading.Event().wait(0.05)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port[0]}")
    monkeypatch.setattr(settings, "gemini_live_remind_every", 1)

    got = []
    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live") as ws:
        while not any(m["type"] == "ai_done" for m in got):
            got.append(ws.receive_json())
        for _ in range(50):
            if any("clientContent" in e for e in received):
                break
            threading.Event().wait(0.05)
    cc = next(e["clientContent"] for e in received if "clientContent" in e)
    assert cc["turnComplete"] is False and "short sentences" in cc["turns"][0]["parts"][0]["text"]


def test_live_relay_uses_patient_context(monkeypatch):
    """?participantId= loads the care profile and memories into setup; remember_fact goes to memory in the background."""
    from app.voice import memory
    calls = [{"id": "c1", "name": "remember_fact", "args": {"fact": "Her favourite film is Roman Holiday."}}]
    port, received = [], []
    threading.Thread(target=fake_gemini, args=(port, received, calls), daemon=True).start()
    for _ in range(50):
        if port:
            break
        threading.Event().wait(0.05)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port[0]}")
    recalled, added = [], []

    async def fake_recall(aid, query=""):
        recalled.append((aid, query))
        return ["Saw Roman Holiday three times."]

    async def fake_add(aid, content, kind="fact"):
        added.append((aid, content))
        return True
    monkeypatch.setattr(memory, "recall", fake_recall)
    monkeypatch.setattr(memory, "add", fake_add)

    got = []
    with TestClient(main.app) as c:
        asyncio.run(main.app.state.store.update("participants", "demo-rose", {"backboardAssistantId": "a1"}))
        with c.websocket_connect("/api/voice/live?participantId=demo-rose&games=faces") as ws:
            while not any(m["type"] == "ai_done" for m in got):
                got.append(ws.receive_json())
        for _ in range(50):
            if added:
                break
            threading.Event().wait(0.05)
    setup = received[0]["setup"]
    prompt = setup["systemInstruction"]["parts"][0]["text"]
    assert "ABOUT ROSE" in prompt and "Cary Grant" in prompt and "Saw Roman Holiday three times." in prompt
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] >= 2000
    assert recalled[0][0] == "a1" and "classic movie stars" in recalled[0][1]
    greeting = next(e["realtimeInput"]["text"] for e in received if "text" in e.get("realtimeInput", {}))
    assert "Rose" in greeting and "classic movie stars" in greeting
    assert added == [("a1", "Her favourite film is Roman Holiday.")]
