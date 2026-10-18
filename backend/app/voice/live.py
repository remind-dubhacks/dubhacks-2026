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
from .prompts.voice_system_prompt import VOICE_SYSTEM_PROMPT
from .tools import GAMES, GameState, run_tool

log = logging.getLogger("remind.live")

GREETING = ("({name} has just sat down. Call show_message with a short greeting that uses their name, then greet them warmly out loud "
            "in one short sentence, say you are ReMind, and offer one of today's games.)")
GOODBYE = "(The person stopped the session. Say a brief, kind goodbye in one sentence.)"
NUDGE = "(It has been quiet for a while. Gently carry on: talk about the item, move to the next one, offer a game, or warmly check in.)"
NUDGE_AFTER_S = 25.0  # silence before a nudge
MAX_NUDGES = 3  # in a row with no reply; then rest the screen and wait for the person
REMINDER = "Reminder: keep replies to one or two short sentences and respond directly to what the user just said."

# Voice activity detection, chosen by GEMINI_LIVE_VAD. Slow, pausing speakers need a long silence before end of turn.
VAD_PRESETS = {
    "default": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 1200, "prefixPaddingMs": 100},
    "fast": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 600, "prefixPaddingMs": 100},
    "legacy": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 1200},  # before 2026-10-18
}

GAME_NAMES = {"faces": "famous faces", "proverbs": "sayings", "sounds": "sounds", "reorder": "the robot ordering game"}


def available() -> bool:
    return bool(settings.gemini_api_key)


def build_setup(name: str, games: list[str], *, prompt: str = VOICE_SYSTEM_PROMPT, vad: str | None = None,
                temperature: float | None = None, max_output_tokens: int | None = None) -> dict:
    """The one setup message for every Live connection. None means "use settings"; a negative temperature
    or a max_output_tokens of 0 leaves that field out (server default)."""
    vad = vad or settings.gemini_live_vad
    if vad not in VAD_PRESETS:
        raise ValueError(f"unknown GEMINI_LIVE_VAD preset {vad!r}; expected one of {sorted(VAD_PRESETS)}")
    temperature = settings.gemini_live_temperature if temperature is None else temperature
    max_output_tokens = settings.gemini_live_max_output_tokens if max_output_tokens is None else max_output_tokens
    gen = {
        "responseModalities": ["AUDIO"],
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.gemini_live_voice}}},
    }
    if temperature >= 0:
        gen["temperature"] = temperature
    if max_output_tokens > 0:
        gen["maxOutputTokens"] = max_output_tokens
    return {"setup": {
        "model": f"models/{settings.gemini_live_model}",
        "generationConfig": gen,
        "systemInstruction": {"parts": [{"text": prompt.format(name=name, games=", ".join(GAME_NAMES[g] for g in games))}]},
        "tools": [{"functionDeclarations": GEMINI_DECLS}],
        "realtimeInputConfig": {"automaticActivityDetection": dict(VAD_PRESETS[vad])},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }}


def reminder_message() -> dict:
    """Adds the brevity reminder to context. turnComplete=False: the model should not reply to it."""
    return {"clientContent": {"turns": [{"role": "user", "parts": [{"text": REMINDER}]}], "turnComplete": False}}


def should_remind(user_turns: int, last_reminded_turn: int, recent_words: list[int]) -> bool:
    every, limit = settings.gemini_live_remind_every, settings.gemini_live_remind_words
    periodic = every > 0 and user_turns > 0 and user_turns % every == 0 and user_turns != last_reminded_turn
    wordy = len(recent_words) >= 2 and all(w > limit for w in recent_words[-2:])
    return periodic or wordy


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
    user_turns = last_reminded_turn = 0
    recent_words: list[int] = []  # output word counts of recent model turns, for the brevity reminder
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
            nonlocal user_buf, user_turns
            if user_buf.strip():
                user_turns += 1
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

        await to_gem(build_setup(name, games))

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
            nonlocal user_buf, ai_buf, stopped, last_activity, nudges, recent_words, last_reminded_turn
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
                        recent_words = (recent_words + [len(ai_buf.split())])[-2:]
                    ai_buf = ""
                    if sc.get("turnComplete"):
                        stopped = False  # ready for the next stop request
                        if should_remind(user_turns, last_reminded_turn, recent_words):
                            last_reminded_turn, recent_words = user_turns, []
                            await to_gem(reminder_message())

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
