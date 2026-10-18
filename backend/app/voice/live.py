"""Gemini Live relay: continuous, interruptible speech-to-speech with tool calling.

Browser <-> this server <-> Gemini Live (WebSocket). The server holds the API key and runs the tools;
the model never touches the robot directly. Browser sends PCM16 mono 16 kHz; replies are PCM16
(24 kHz unless the chunk's mime type says otherwise). Docs: https://ai.google.dev/gemini-api/docs/live
"""
import asyncio
import base64
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

import websockets
from fastapi import WebSocket

from ..config import settings
from .agent import GEMINI_DECLS, STOP_RE
from .tools import GAMES, GameState, run_tool

log = logging.getLogger("remind.live")

INSTRUCTIONS = """You are ReMind, a warm, patient companion for {name}, a person living with dementia, in a care home. A nurse set this up and is nearby.
You are speaking out loud: use one or two SHORT, simple sentences, a calm pace, and never lists. No medical advice.
There is a screen in front of {name}. It shows only what your tools put there: a photo, a few words, or nothing. Never mention buttons or ask them to touch anything.

How to talk (Cognitive Stimulation Therapy principles):
- Ask for opinions and feelings rather than facts: "What do you think of...", "Does this remind you of anything?"
- Use memories as a way into the here and now. Follow what interests {name} and let them lead.
- Never test, quiz or correct. Any answer is a good answer. If they are unsure, give a gentle hint, then reveal warmly.
- Keep it fun and relaxed. Offer choices. Use their name now and then.
- Keep the conversation moving: after talking about an item for a little while, move on yourself. After a game, offer another one.

Games available today: {games}.
- Famous faces (faces): call start_game. Ask what they notice and what the face brings to mind, then hint, then call reveal and chat about the person. Then call next_item.
- Sayings (proverbs): call start_game, read the saying slowly and let them finish it. Call reveal to show the whole saying, chat about what it means to them, then next_item.
- Sounds (sounds): call start_game and say only "Have a listen." then wait. When told the sound has finished, ask what it sounded like and what it reminds them of. Call reveal, chat, then next_item. Use play_sound if they want to hear it again.
- Reorder (reorder): call start_game, then tell them the RIGHT order to put the objects in (target_order from the tool result; never call it the starting order) and ask them to say "done" when finished. When they are done, call check_arrangement. If wrong, kindly explain with the tool's reason and invite another try. If attempts_left is 0, gently reveal the correct order. If correct, praise them. Never claim the robot did something unless a tool result says so.
After each item, call note_response with how engaged they were and one short note about what they shared.
Use show_message for a short greeting or a warm sentence worth seeing. When a game ends, call end_game.
If they ask for help, seem upset, frightened or unwell, call alert_caregiver and reassure them. If they want to stop, call stop.
Be patient: people may speak slowly and pause. Do not rush them."""

GREETING = ("({name} has just sat down. Call show_message with a short greeting that uses their name, then greet them warmly out loud "
            "in one short sentence, say you are ReMind, and offer one of today's games.)")
GOODBYE = "(The person stopped the session. Say a brief, kind goodbye in one sentence.)"
NUDGE = "(It has been quiet for a while. Gently carry on: talk about the item, move to the next one, offer a game, or warmly check in.)"
NUDGE_AFTER_S = 25.0  # silence before a nudge
MAX_NUDGES = 3  # in a row with no reply; then rest the screen and wait for the person

GAME_NAMES = {"faces": "famous faces", "proverbs": "sayings", "sounds": "sounds", "reorder": "the robot ordering game"}


def available() -> bool:
    return bool(settings.gemini_api_key)


def _setup(name: str, games: list[str]) -> dict:
    return {"setup": {
        "model": f"models/{settings.gemini_live_model}",
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.gemini_live_voice}}},
        },
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS.format(name=name, games=", ".join(GAME_NAMES[g] for g in games))}]},
        "tools": [{"functionDeclarations": GEMINI_DECLS}],
        # Slow, pausing speakers: wait longer before deciding the turn is over.
        "realtimeInputConfig": {"automaticActivityDetection": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 1200}},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }}


async def run(ws: WebSocket) -> None:
    await ws.accept()
    if not available():
        await ws.send_json({"type": "error", "message": "GEMINI_API_KEY is not set on the backend"})
        await ws.close()
        return

    name = (ws.query_params.get("name") or "").strip()[:40] or "friend"
    games = [g for g in (ws.query_params.get("games") or "").split(",") if g in GAMES] or list(GAMES)
    state = GameState(patient_name=name, enabled_games=games)
    started_at = datetime.now(timezone.utc)
    user_buf = ai_buf = ""
    stopped = False
    last_activity = time.monotonic()
    nudges = 0
    url = f"{settings.gemini_live_url}?key={settings.gemini_api_key}"

    try:
        gem = await websockets.connect(url, max_size=None)
    except Exception as e:  # noqa: BLE001
        await ws.send_json({"type": "error", "message": f"Could not reach Gemini Live: {type(e).__name__}"})
        await ws.close()
        return

    async with gem:
        async def to_gem(obj: dict) -> None:
            await gem.send(json.dumps(obj))

        async def tool(name: str, args: dict) -> dict:
            res = await run_tool(state, name, args, None)
            await ws.send_json({"type": "tool", "name": name, "args": args, "result": res, "state": state.view()})
            return res

        async def finalize_user() -> None:
            nonlocal user_buf
            if user_buf.strip():
                await ws.send_json({"type": "user_text", "text": user_buf.strip()})
            user_buf = ""

        async def hard_stop(say_goodbye: bool = True) -> None:
            nonlocal stopped, nudges
            if stopped:
                return
            stopped = True
            nudges = MAX_NUDGES  # no nudging after a stop until the person speaks again
            await tool("stop", {})
            await ws.send_json({"type": "interrupt"})
            if say_goodbye:
                await to_gem({"realtimeInput": {"text": GOODBYE}})

        await to_gem(_setup(name, games))

        async def from_browser() -> None:
            nonlocal last_activity
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    await to_gem({"realtimeInput": {"audio": {"data": base64.b64encode(msg["bytes"]).decode(), "mimeType": "audio/pcm;rate=16000"}}})
                elif msg.get("text"):
                    data = json.loads(msg["text"])
                    if data.get("type") == "stop":
                        await hard_stop()
                    elif data.get("type") == "text" and data.get("text", "").strip():  # typed input or page events
                        last_activity = time.monotonic()
                        await to_gem({"realtimeInput": {"text": data["text"]}})

        async def nudger() -> None:
            """Gemini only speaks when spoken to; after a long silence, prompt it to carry the conversation on."""
            nonlocal last_activity, nudges
            while True:
                await asyncio.sleep(1)
                if nudges >= MAX_NUDGES or time.monotonic() - last_activity < NUDGE_AFTER_S:
                    continue
                last_activity = time.monotonic()
                nudges += 1
                if nudges < MAX_NUDGES:
                    await to_gem({"realtimeInput": {"text": NUDGE}})
                else:  # no reply to repeated nudges: note it, rest the screen, wait for the person
                    await tool("note_response", {"engagement": "withdrawn", "note": "No reply to several gentle prompts."})
                    await tool("end_game", {})

        async def from_gem() -> None:
            nonlocal user_buf, ai_buf, stopped, last_activity, nudges
            greeted = False
            async for raw in gem:
                ev = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                last_activity = time.monotonic()
                if "setupComplete" in ev and not greeted:
                    greeted = True
                    await to_gem({"realtimeInput": {"text": GREETING.format(name=name)}})
                    continue

                if "toolCall" in ev:
                    await finalize_user()
                    responses = []
                    for fc in ev["toolCall"].get("functionCalls", []):
                        res = await tool(fc["name"], fc.get("args") or {})
                        responses.append({"id": fc.get("id"), "name": fc["name"], "response": {"result": res}})
                    await to_gem({"toolResponse": {"functionResponses": responses}})
                    continue

                sc = ev.get("serverContent")
                if not sc:
                    if "error" in ev:
                        await ws.send_json({"type": "error", "message": json.dumps(ev["error"])[:300]})
                    continue

                if "inputTranscription" in sc:
                    user_buf += sc["inputTranscription"].get("text", "")
                    nudges = 0
                    await ws.send_json({"type": "user_partial", "text": user_buf})
                    if not stopped and STOP_RE.search(user_buf):  # deterministic stop, independent of the model
                        await hard_stop()
                if "outputTranscription" in sc:
                    await finalize_user()
                    t = sc["outputTranscription"].get("text", "")
                    ai_buf += t
                    await ws.send_json({"type": "ai_delta", "text": t})
                for part in (sc.get("modelTurn") or {}).get("parts", []):
                    inline = part.get("inlineData")
                    if inline and inline.get("data"):
                        await finalize_user()
                        m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
                        await ws.send_json({"type": "audio", "delta": inline["data"], "rate": int(m.group(1)) if m else 24000})
                if sc.get("interrupted"):
                    await ws.send_json({"type": "interrupt"})
                if sc.get("interrupted") or sc.get("turnComplete"):
                    if ai_buf.strip():
                        await ws.send_json({"type": "ai_done", "text": ai_buf.strip()})
                    ai_buf = ""
                    if sc.get("turnComplete"):
                        stopped = False  # ready for the next stop request

        tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_gem()), asyncio.create_task(nudger())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                if d.exception():
                    log.warning("live session ended: %r", d.exception())
        finally:
            for t in tasks:
                t.cancel()
            await save_record(ws, state, started_at)


async def save_record(ws: WebSocket, state: GameState, started_at: datetime) -> None:
    """Session summary for the nurse screen. No raw transcripts are kept."""
    store = getattr(ws.app.state, "store", None)
    if store is None:
        return
    try:
        await store.insert("companion_sessions", {
            "_id": uuid.uuid4().hex, "patientName": state.patient_name, "startedAt": started_at, "endedAt": datetime.now(timezone.utc),
            "gamesPlayed": state.games_played, "observations": state.observations, "alerts": state.alerts,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("could not save companion session: %r", e)
