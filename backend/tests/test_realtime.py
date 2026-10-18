"""Relay test against a fake xAI realtime server (no network, no key)."""
import asyncio
import base64
import json
import threading

import websockets
from fastapi.testclient import TestClient

from app import main
from app.config import settings


def run_fake_xai(port_holder: list, received: list):
    async def handler(ws):
        async for raw in ws:
            ev = json.loads(raw)
            received.append(ev)
            if ev["type"] == "response.create" and len([e for e in received if e["type"] == "response.create"]) == 1:
                await ws.send(json.dumps({"type": "response.output_audio.delta", "delta": base64.b64encode(b"\x00\x01" * 4).decode()}))
                await ws.send(json.dumps({"type": "response.output_audio_transcript.done", "transcript": "Hello, I'm ReMind."}))
                await ws.send(json.dumps({"type": "response.done"}))
                await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "play the ordering game"}))
                await ws.send(json.dumps({"type": "response.function_call_arguments.done", "name": "start_game", "call_id": "c1", "arguments": '{"game_id":"reorder"}'}))
                await ws.send(json.dumps({"type": "response.done"}))

    async def main_():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port_holder.append(server.sockets[0].getsockname()[1])
            await asyncio.Future()

    asyncio.run(main_())


def test_relay(monkeypatch):
    port, received = [], []
    threading.Thread(target=run_fake_xai, args=(port, received), daemon=True).start()
    for _ in range(50):
        if port:
            break
        threading.Event().wait(0.05)
    monkeypatch.setattr(settings, "xai_api_key", "test-key")
    monkeypatch.setattr(settings, "xai_voice_url", f"ws://127.0.0.1:{port[0]}")

    got = []
    with TestClient(main.app) as c, c.websocket_connect("/api/voice/ws") as ws:
        ws.send_bytes(b"\x00\x00" * 10)  # mic audio -> input_audio_buffer.append
        while not any(m["type"] == "tool" for m in got):
            got.append(ws.receive_json())
    types = [m["type"] for m in got]
    assert "audio" in types and "ai_done" in types and "user_text" in types
    tool = next(m for m in got if m["type"] == "tool")
    assert tool["name"] == "start_game" and tool["state"]["phase"] == "awaiting"

    for _ in range(40):  # relay answers the tool call, then asks the model to continue
        if any(e["type"] == "function_call_output" for e in [e.get("item", {}) | {"type": e.get("item", {}).get("type")} for e in received if e["type"] == "conversation.item.create"]):
            break
        threading.Event().wait(0.05)
    kinds = [e["type"] for e in received]
    assert kinds[0] == "session.update" and "input_audio_buffer.append" in kinds
    assert any(e.get("item", {}).get("type") == "function_call_output" for e in received)
    assert received[0]["session"]["tools"][0]["name"] == "list_games"
