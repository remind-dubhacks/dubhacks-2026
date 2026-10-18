"""Live relay against fake Gemini Live and fake Backboard Realtime servers (no network, no keys)."""
import asyncio
import base64
import json
import threading

import websockets
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.voice import memory

START_GAME = [{"id": "c1", "name": "start_game", "args": {"game_id": "reorder"}}]
AUDIO = base64.b64encode(b"\x00\x01" * 4).decode()


def serve(target, *args) -> int:
    port: list = []
    threading.Thread(target=target, args=(port, *args), daemon=True).start()
    for _ in range(50):
        if port:
            break
        threading.Event().wait(0.05)
    return port[0]


def run_server(port_holder: list, handler):
    async def main_():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port_holder.append(server.sockets[0].getsockname()[1])
            await asyncio.Future()

    asyncio.run(main_())


def wait_for(cond) -> None:
    for _ in range(50):
        if cond():
            return
        threading.Event().wait(0.05)


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
                                              "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": AUDIO}}]}}})
                await send({"serverContent": {"turnComplete": True}})

    run_server(port_holder, handler)


def refusing_backboard(port_holder: list, received: list):
    """Answers setup the way Backboard does on an account without paid realtime credits."""
    async def handler(ws):
        async for raw in ws:
            received.append(json.loads(raw))
            await ws.send(json.dumps({"type": "error", "code": "insufficient_credits",
                                      "message": "Paid or eligible subscription credits are required for native audio."}))

    run_server(port_holder, handler)


def fake_backboard(port_holder: list, received: list, end_first: bool = False):
    """Speaks the documented Backboard Realtime protocol. Records frames; binary audio as {"binary": n}."""
    connections = []

    async def handler(ws):
        try:
            await session(ws)
        except websockets.ConnectionClosed:
            pass

    async def session(ws):
        connections.append(ws)
        n = len(connections)
        send = lambda o: ws.send(json.dumps(o))  # noqa: E731
        async for raw in ws:
            if isinstance(raw, bytes):
                received.append({"binary": len(raw)})
                continue
            ev = json.loads(raw)
            received.append(ev)
            if "provider" in ev:  # setup frame
                ev["_api_key"] = ws.request.headers.get("X-API-Key")
                await send({"type": "session.begin", "session_id": f"s{n}", "thread_id": "t1", "assistant_id": ev.get("assistant_id")})
                if end_first and n == 1:
                    await send({"type": "session.ended"})
                elif end_first:
                    await send({"type": "transcript.delta", "role": "assistant", "text": "Where were we?", "item_id": "r1"})
            elif ev.get("type") == "provider.event" and "text" in ev["event"].get("realtimeInput", {}) and sum(
                    "text" in e.get("event", {}).get("realtimeInput", {}) for e in received) == 1:
                await send({"type": "transcript.delta", "role": "user", "text": "play the ordering game", "item_id": "u1"})
                await send({"type": "transcript.final", "role": "user", "text": "play the ordering game", "item_id": "u1"})
                await send({"type": "tool.call", "name": "start_game", "arguments": json.dumps({"game_id": "reorder"}),
                            "tool_call_id": "c1", "hosted": False})
            elif ev.get("type") == "tool.outputs":
                await send({"type": "transcript.delta", "role": "assistant", "text": "Put the cup first.", "item_id": "a1"})
                await send({"type": "audio.delta", "data": AUDIO, "sample_rate": 24000, "item_id": "a1"})
                await send({"type": "response.done"})
            elif ev.get("type") == "stop":
                await send({"type": "session.ended"})

    run_server(port_holder, handler)


def collect(ws, until: str = "ai_done") -> list[dict]:
    got = []
    while not any(m["type"] == until for m in got):
        got.append(ws.receive_json())
    return got


def finish(c, ws) -> None:
    """Disconnect and wait until the relay has saved its session record (its last step). Leaving the
    websocket_connect block cancels a handler that is still running, which fails the test."""
    ws.close()
    wait_for(lambda: c.get("/api/voice/sessions").json())


def test_live_relay(monkeypatch):
    received = []
    port = serve(fake_gemini, received)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port}")

    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live") as ws:
        ws.send_bytes(b"\x00\x00" * 10)
        got = collect(ws)
        finish(c, ws)
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


def test_transport_choice(monkeypatch):
    from app.voice.live import transport
    monkeypatch.setattr(settings, "voice_transport", "")
    assert transport() == "gemini"
    monkeypatch.setattr(settings, "backboard_api_key", "k")
    assert transport() == "backboard"
    monkeypatch.setattr(settings, "voice_transport", "gemini")
    assert transport() == "gemini"


def test_live_relay_sends_reminder_without_turn_complete(monkeypatch):
    received = []
    port = serve(fake_gemini, received)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port}")
    monkeypatch.setattr(settings, "gemini_live_remind_every", 1)

    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live") as ws:
        collect(ws)
        wait_for(lambda: any("clientContent" in e for e in received))
        finish(c, ws)
    cc = next(e["clientContent"] for e in received if "clientContent" in e)
    assert cc["turnComplete"] is False and "short sentences" in cc["turns"][0]["parts"][0]["text"]


def test_gemini_fallback_reads_memories_into_prompt(monkeypatch):
    """Direct Gemini: the care profile and recalled memories go into the prompt; nothing is written mid-call, and
    what the person said is digested afterwards."""
    received, recalled, added, digested = [], [], [], []
    port = serve(fake_gemini, received)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port}")

    async def fake_recall(aid, query=""):
        recalled.append((aid, query))
        return ["Saw Roman Holiday three times."]

    async def fake_add(*a, **kw):
        added.append(a)
    async def fake_digest(aid, patient, said):
        digested.append((aid, patient, list(said)))
    monkeypatch.setattr(memory, "recall", fake_recall)
    monkeypatch.setattr(memory, "add", fake_add)
    monkeypatch.setattr(memory, "digest_session", fake_digest)

    with TestClient(main.app) as c:
        asyncio.run(main.app.state.store.update("participants", "demo-rose", {"backboardAssistantId": "a1"}))
        with c.websocket_connect("/api/voice/live?participantId=demo-rose&games=faces") as ws:
            collect(ws)
            finish(c, ws)
            wait_for(lambda: digested)
    setup = received[0]["setup"]
    prompt = setup["systemInstruction"]["parts"][0]["text"]
    assert "ABOUT ROSE" in prompt and "Cary Grant" in prompt and "Saw Roman Holiday three times." in prompt
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] >= 2000
    assert recalled[0][0] == "a1" and "classic movie stars" in recalled[0][1]
    greeting = next(e["realtimeInput"]["text"] for e in received if "text" in e.get("realtimeInput", {}))
    assert "Rose" in greeting and "classic movie stars" in greeting
    assert added == []
    assert digested and digested[0][:2] == ("a1", "Rose")


def use_backboard(monkeypatch, port: int) -> None:
    monkeypatch.setattr(settings, "voice_transport", "backboard")
    monkeypatch.setattr(settings, "backboard_api_key", "bb-key")
    monkeypatch.setattr(settings, "backboard_realtime_url", f"ws://127.0.0.1:{port}")


def test_backboard_relay(monkeypatch):
    """Through Backboard: setup frame carries the patient's assistant + memory=Readonly + native Gemini config; tools,
    transcripts, audio and the silent reminder all round-trip; the session is stopped cleanly at the end and what
    the person said is digested into memory."""
    received, digested = [], []
    port = serve(fake_backboard, received)
    use_backboard(monkeypatch, port)
    monkeypatch.setattr(settings, "gemini_live_remind_every", 1)

    async def fake_digest(aid, patient, said):
        digested.append((aid, patient, list(said)))
    monkeypatch.setattr(memory, "digest_session", fake_digest)

    with TestClient(main.app) as c:
        asyncio.run(main.app.state.store.update("participants", "demo-rose", {"backboardAssistantId": "a1"}))
        with c.websocket_connect("/api/voice/live?participantId=demo-rose&games=faces") as ws:
            ws.send_bytes(b"\x00\x00" * 10)
            got = collect(ws)
            wait_for(lambda: any("clientContent" in e.get("event", {}) for e in received))
            finish(c, ws)
            wait_for(lambda: any(e.get("type") == "stop" for e in received))  # background close: stop handshake
            wait_for(lambda: digested)

    setup = received[0]
    assert setup["_api_key"] == "bb-key"
    assert setup["provider"] == "google" and setup["model"] == settings.backboard_realtime_model
    assert setup["assistant_id"] == "a1" and setup["memory"] == "Readonly"
    assert digested == [("a1", "Rose", ["play the ordering game"])]
    assert "ABOUT ROSE" in setup["system_prompt"] and "Cary Grant" in setup["system_prompt"]
    opts = setup["provider_options"]
    assert "systemInstruction" not in opts and opts["realtimeInputConfig"]["automaticActivityDetection"]["silenceDurationMs"] == 2200
    assert opts["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert "start_game" in [t["function"]["name"] for t in setup["tools"]]

    assert any(e.get("binary") == 20 for e in received)  # mic audio forwarded as raw binary
    greeting = next(e["event"]["realtimeInput"]["text"] for e in received if e.get("type") == "provider.event")
    assert "Rose" in greeting
    outputs = next(e["outputs"] for e in received if e.get("type") == "tool.outputs")
    tool_msg = next(m for m in got if m["type"] == "tool")
    assert outputs[0]["tool_call_id"] == "c1" and outputs[0]["name"] == "start_game"
    assert json.loads(outputs[0]["output"]) == tool_msg["result"]
    reminder = next(e["event"]["clientContent"] for e in received if "clientContent" in e.get("event", {}))
    assert reminder["turnComplete"] is False

    assert [m["text"] for m in got if m["type"] == "user_text"] == ["play the ordering game"]  # final not repeated
    assert next(m for m in got if m["type"] == "audio")["rate"] == 24000
    assert next(m for m in got if m["type"] == "ai_done")["text"] == "Put the cup first."
    assert any(e.get("type") == "stop" for e in received)


def test_backboard_name_only_session_has_no_memory(monkeypatch):
    received = []
    port = serve(fake_backboard, received)
    use_backboard(monkeypatch, port)
    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live?name=Ann&games=faces") as ws:
        collect(ws)
        finish(c, ws)
    assert received[0]["memory"] == "off" and "assistant_id" not in received[0]


def test_backboard_first_session_creates_assistant(monkeypatch):
    received, seeded = [], []
    port = serve(fake_backboard, received)
    use_backboard(monkeypatch, port)

    async def fake_ensure(store, participant, with_seed=True):
        assert with_seed is False
        return "new1"

    async def fake_seed(aid, profile):
        seeded.append((aid, bool(profile)))
    monkeypatch.setattr(memory, "ensure_assistant", fake_ensure)
    monkeypatch.setattr(memory, "seed", fake_seed)

    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live?participantId=demo-rose&games=faces") as ws:
        collect(ws)
        finish(c, ws)
    assert received[0]["assistant_id"] == "new1" and received[0]["memory"] == "Readonly"
    assert seeded == [("new1", True)]


def test_backboard_refusal_falls_back_to_gemini(monkeypatch):
    bb_received, gem_received = [], []
    use_backboard(monkeypatch, serve(refusing_backboard, bb_received))
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{serve(fake_gemini, gem_received)}")
    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live?name=Ann&games=faces") as ws:
        got = collect(ws)
        finish(c, ws)
    assert bb_received and bb_received[0]["provider"] == "google"  # tried Backboard first
    assert "setup" in gem_received[0] and not any(m["type"] == "error" for m in got)


def test_backboard_refusal_without_gemini_key_reports_why(monkeypatch):
    use_backboard(monkeypatch, serve(refusing_backboard, []))
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with TestClient(main.app) as c, c.websocket_connect("/api/voice/live?name=Ann") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error" and "insufficient_credits" in msg["message"]


async def test_backboard_resumes_thread_after_session_cap(monkeypatch):
    from app.voice.upstreams import BackboardUpstream
    received = []
    port = serve(fake_backboard, received, True)
    use_backboard(monkeypatch, port)
    up = BackboardUpstream({"provider": "google", "model": "m", "assistant_id": "a1", "memory": "Auto"})
    await up.connect()
    events = up.events()
    assert (await anext(events)).kind == "ready"
    ev = await asyncio.wait_for(anext(events), 5)  # first session ends -> reconnect -> resumed session speaks
    setups = [e for e in received if "provider" in e]
    assert len(setups) == 2 and setups[1]["thread_id"] == "t1" and "assistant_id" not in setups[1]
    assert (ev.kind, ev.text) == ("ai_text", "Where were we?")
    await up.close()
