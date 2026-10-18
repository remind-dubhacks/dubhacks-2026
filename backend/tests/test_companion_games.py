"""Screen games (faces, proverbs, sounds), the patient-screen state they drive, nudges and the session record."""
import asyncio
import json
import threading

import websockets
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.games import faces, proverbs, sounds
from app.voice import live
from app.voice.tools import MAX_MESSAGE_WORDS, GameState, run_tool


def run(state, name, args=None):
    return asyncio.run(run_tool(state, name, args or {}, None))


def test_faces_flow():
    s = GameState()
    r = run(s, "start_game", {"game_id": "faces"})
    assert r["ok"] and r["person"] == "Elvis Presley" and r["of"] == 3
    assert s.screen == {"kind": "photo", "photo": "/games/faces/elvis.jpg"}
    run(s, "reveal")
    assert s.screen["kind"] == "photo_caption" and s.screen["caption"] == "This is Elvis Presley."
    run(s, "next_item")
    assert s.screen["photo"] == faces.ITEMS[1]["photo"]
    run(s, "next_item")
    r = run(s, "next_item")
    assert r["finished"] and s.screen == {"kind": "rest"} and s.phase == "complete"


def test_proverbs_show_gap_then_full():
    s = GameState()
    run(s, "start_game", {"game_id": "proverbs"})
    assert s.screen == {"kind": "message", "text": proverbs.ITEMS[0]["shown"]}
    assert "____" in s.screen["text"] and proverbs.ITEMS[0]["missing"] not in s.screen["text"]
    run(s, "reveal")
    assert s.screen["text"] == proverbs.ITEMS[0]["full"]


def test_proverbs_fit_message_limit():
    assert all(len(p["full"].split()) <= MAX_MESSAGE_WORDS for p in proverbs.ITEMS)


def test_sounds_play_and_replay():
    s = GameState()
    r = run(s, "start_game", {"game_id": "sounds"})
    assert r["answer"] == sounds.ITEMS[0]["answer"]
    assert s.sound["src"] == sounds.ITEMS[0]["src"] and s.screen["kind"] == "message"
    first = s.sound["id"]
    run(s, "play_sound")
    assert s.sound["id"] == first + 1
    run(s, "next_item")
    assert s.sound["src"] == sounds.ITEMS[1]["src"]


def test_play_sound_only_in_sounds_game():
    s = GameState()
    run(s, "start_game", {"game_id": "faces"})
    assert not run(s, "play_sound")["ok"]


def test_show_message_is_capped():
    s = GameState()
    run(s, "show_message", {"text": " ".join(["word"] * 20)})
    assert len(s.screen["text"].split()) == MAX_MESSAGE_WORDS


def test_end_game_and_stop_rest_the_screen():
    s = GameState()
    run(s, "start_game", {"game_id": "faces"})
    run(s, "end_game")
    assert s.screen == {"kind": "rest"} and s.phase == "idle"
    run(s, "start_game", {"game_id": "sounds"})
    run(s, "stop")
    assert s.screen == {"kind": "rest"} and s.sound is None


def test_disabled_game_rejected():
    s = GameState(enabled_games=["faces"])
    assert not run(s, "start_game", {"game_id": "sounds"})["ok"]
    assert [g["id"] for g in run(s, "list_games")["games"]] == ["faces"]


def test_note_response_recorded():
    s = GameState()
    run(s, "start_game", {"game_id": "faces"})
    run(s, "note_response", {"engagement": "engaged", "note": "Sang a bit of Hound Dog."})
    run(s, "note_response", {"engagement": "bogus"})
    assert s.observations[0] == {"game": "faces", "item": "elvis", "engagement": "engaged", "note": "Sang a bit of Hound Dog."}
    assert s.observations[1]["engagement"] == "some"


def test_reorder_still_works():
    s = GameState()
    r = run(s, "start_game", {"game_id": "reorder"})
    assert r["ok"] and s.phase == "awaiting" and s.screen["kind"] == "message"


def silent_gemini(port_holder: list, received: list):
    """Fake Gemini Live that never speaks, so the relay's nudges are all that happen."""
    async def handler(ws):
        async for raw in ws:
            ev = json.loads(raw)
            received.append(ev)
            if "setup" in ev:
                await ws.send(json.dumps({"setupComplete": {}}))
            elif "toolResponse" in ev:
                await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))

    async def main_():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port_holder.append(server.sockets[0].getsockname()[1])
            await asyncio.Future()

    asyncio.run(main_())


def test_nudges_then_rest_and_session_record(monkeypatch):
    port, received = [], []
    threading.Thread(target=silent_gemini, args=(port, received), daemon=True).start()
    for _ in range(50):
        if port:
            break
        threading.Event().wait(0.05)
    monkeypatch.setattr(settings, "gemini_api_key", "test")
    monkeypatch.setattr(settings, "gemini_live_url", f"ws://127.0.0.1:{port[0]}")
    monkeypatch.setattr(live, "NUDGE_AFTER_S", 0.1)

    with TestClient(main.app) as c:
        with c.websocket_connect("/api/voice/live?name=Margaret&games=faces,sounds") as ws:
            tools = []
            while not any(t["name"] == "end_game" for t in tools):
                m = ws.receive_json()
                if m["type"] == "tool":
                    tools.append(m)
            assert tools[0]["name"] == "note_response" and tools[0]["state"]["observations"][0]["engagement"] == "withdrawn"
        setup = received[0]["setup"]["systemInstruction"]["parts"][0]["text"]
        assert "Margaret" in setup and "famous faces, sounds" in setup
        texts = [e["realtimeInput"]["text"] for e in received if "text" in e.get("realtimeInput", {})]
        assert "Margaret" in texts[0] and texts.count(live.NUDGE) == live.MAX_NUDGES - 1

        for _ in range(50):
            recs = c.get("/api/voice/sessions").json()
            if recs:
                break
            threading.Event().wait(0.05)
        assert recs[0]["patientName"] == "Margaret" and recs[0]["observations"][0]["engagement"] == "withdrawn"
