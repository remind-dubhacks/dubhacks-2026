"""Live relay against a fake Gemini Live server (no network, no key)."""
import asyncio
import base64
import json
import threading

import websockets
from fastapi.testclient import TestClient

from app import main
from app.config import settings


def fake_gemini(port_holder: list, received: list):
    async def handler(ws):
        async for raw in ws:
            ev = json.loads(raw)
            received.append(ev)
            if "setup" in ev:
                await ws.send(json.dumps({"setupComplete": {}}))
            elif "realtimeInput" in ev and "text" in ev["realtimeInput"] and sum("text" in e.get("realtimeInput", {}) for e in received) == 1:
                send = lambda o: ws.send(json.dumps(o))  # noqa: E731
                await send({"serverContent": {"inputTranscription": {"text": "play the ordering game"}}})
                await send({"toolCall": {"functionCalls": [{"id": "c1", "name": "start_game", "args": {"game_id": "reorder"}}]}})
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
