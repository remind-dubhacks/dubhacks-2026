"""Live voice relay: continuous, interruptible speech-to-speech with tool calling.

Browser <-> this server <-> Backboard Realtime -> Gemini Live. (Gemini Live directly is switched off during
development, see transport() and connect_upstream(); the code stays in voice/upstreams.py.) The server holds the
API keys and runs the tools; the model never touches the robot directly.
Browser sends PCM16 mono 16 kHz; replies are PCM16 (24 kHz unless the provider says otherwise).
Docs: https://ai.google.dev/gemini-api/docs/live, https://docs.backboard.io

Long-term memory: each patient has their own Backboard assistant, resolved once at the start of a call
(memory.ensure_assistant) and used for everything in that call, so nothing is read from or saved to anyone else's.
What is remembered goes into the prompt at the start (and Backboard's memory="Readonly" may retrieve more). New
facts are saved in the background, never delaying a reply: when the model calls the remember tool, and after the
call (memory.digest_session) for anything it missed.
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket

from ..alerts import normalize_phone, send_alert
from ..config import settings
from ..tasks import background
from . import memory
from .agent import GEMINI_DECLS, STOP_RE
from .prompts.voice_system_prompt import VOICE_SYSTEM_PROMPT, render_profile
from .tools import GAMES, TOOL_SCHEMAS, GameState, check_motors, run_tool, session_summary, watch_table
from .upstreams import BackboardUpstream, GeminiUpstream, context_message

log = logging.getLogger("remind.live")

GREETING = ("({name} has just sat down. Call show_message with a short greeting that uses their name, then greet them warmly out loud "
            "in one short sentence, say you are ReMind, and offer one of today's games.{extra})")
GREETING_INTEREST = " You might mention that you were thinking about {interest} today."
GOODBYE = "(The person stopped the session. Say a brief, kind goodbye in one sentence.)"
NUDGE = "(It has been quiet for a while. Gently carry on: talk about the item, move to the next one, offer a game, or warmly check in.)"
NUDGE_AFTER_S = 25.0  # silence before a nudge
SLOW_NUDGE_AFTER_S = 45.0  # for slow speakers (care profile)
TABLE_SAY = "(The table camera noticed something. Say exactly this to the person, warmly, and nothing else: {say})"
TABLE_EVERY_S = 1.2  # how often the table is checked while Remember the Order is waiting for the person
MAX_NUDGES = 3  # in a row with no reply; then rest the screen and wait for the person
REMINDER = "Reminder: keep replies to one or two short sentences and respond directly to what the user just said."

# Voice activity detection, chosen by GEMINI_LIVE_VAD. Slow, pausing speakers need a long silence before end of turn.
VAD_PRESETS = {
    "default": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 1200, "prefixPaddingMs": 100},
    "fast": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 600, "prefixPaddingMs": 100},
    "legacy": {"endOfSpeechSensitivity": "END_SENSITIVITY_LOW", "silenceDurationMs": 1200},  # before 2026-10-18
}
# Laid over the preset when the care profile says they stutter, lose words or speak slowly: they pause mid-sentence.
SLOW_VAD = {"silenceDurationMs": 2200, "prefixPaddingMs": 300}

GAME_NAMES = {"faces": "famous faces", "proverbs": "sayings", "sounds": "sounds", "reorder": "the robot ordering game",
              "order_memory": "remember the order (the shuffle game with the robot)", "find_remember": "find and remember"}


def transport() -> str:
    """Always backboard during development. With direct Gemini back on: backboard | gemini, VOICE_TRANSPORT wins,
    otherwise Backboard whenever its key is set."""
    # DEV: Backboard only. Un-comment to allow VOICE_TRANSPORT=gemini and direct Gemini without a Backboard key.
    # t = settings.voice_transport.strip().lower()
    # if t in ("backboard", "gemini"):
    #     return t
    # return "backboard" if settings.backboard_api_key else "gemini"
    return "backboard"


def available() -> bool:
    return bool(settings.backboard_api_key if transport() == "backboard" else settings.gemini_api_key)


def needs_slow_pacing(profile: dict | None) -> bool:
    p = profile or {}
    return p.get("pace") == "slow" or bool({"stutter", "aphasia", "word_finding"} & set(p.get("speech", [])))


def gemini_config(name: str, games: list[str], *, prompt: str = VOICE_SYSTEM_PROMPT, vad: str | None = None,
                  temperature: float | None = None, max_output_tokens: int | None = None,
                  profile: dict | None = None, memories: list[str] | None = None) -> dict:
    """Native Gemini Live config shared by both transports. None means "use settings"; a negative temperature
    or a max_output_tokens of 0 leaves that field out (server default). `profile` (models.CareProfile) and
    `memories` add an ABOUT section to the prompt, and slow speakers get SLOW_VAD."""
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
    return {
        "generationConfig": gen,
        "systemInstruction": {"parts": [{"text": prompt.format(name=name, games=", ".join(GAME_NAMES[g] for g in games))
                                         + render_profile(name, profile, memories)}]},
        "realtimeInputConfig": {"automaticActivityDetection": {**VAD_PRESETS[vad], **(SLOW_VAD if needs_slow_pacing(profile) else {})}},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }


def build_setup(name: str, games: list[str], **kw) -> dict:
    """Setup message for a direct Gemini Live connection (keyword arguments as gemini_config)."""
    return {"setup": {"model": f"models/{settings.gemini_live_model}", **gemini_config(name, games, **kw),
                      "tools": [{"functionDeclarations": GEMINI_DECLS}]}}


def backboard_setup(name: str, games: list[str], *, assistant_id: str | None, memory_mode: str, **kw) -> dict:
    """Backboard Realtime setup frame. The prompt goes in system_prompt; the rest of the Gemini config is passed
    through untouched as provider_options. A new thread per session; memory lives on the patient's assistant."""
    cfg = gemini_config(name, games, **kw)
    frame = {
        "provider": "google", "model": settings.backboard_realtime_model, "memory": memory_mode,
        "system_prompt": cfg.pop("systemInstruction")["parts"][0]["text"],
        "tools": TOOL_SCHEMAS, "provider_options": cfg,
    }
    if assistant_id:
        frame["assistant_id"] = assistant_id
    return frame


def reminder_message() -> dict:
    """Adds the brevity reminder to context. turnComplete=False: the model should not reply to it."""
    return context_message(REMINDER)


def should_remind(user_turns: int, last_reminded_turn: int, recent_words: list[int]) -> bool:
    every, limit = settings.gemini_live_remind_every, settings.gemini_live_remind_words
    periodic = every > 0 and user_turns > 0 and user_turns % every == 0 and user_turns != last_reminded_turn
    wordy = len(recent_words) >= 2 and all(w > limit for w in recent_words[-2:])
    return periodic or wordy


def can_remember(participant: dict) -> bool:
    return bool(participant.get("consentFlags", {}).get("rememberPreferences"))


async def open_upstream(ws: WebSocket, name: str, games: list[str], participant: dict):
    """Pick the transport and build its setup. Backboard: resolve this patient's own assistant (created on their
    first session) and put what it remembers in the prompt; memory="Readonly" may retrieve more. Gemini: read
    memories once. The upstream's assistant_id is the only one run() uses for this call."""
    profile = participant.get("careProfile") or {}
    if transport() == "backboard":
        assistant_id = None
        if can_remember(participant):
            assistant_id = await memory.ensure_assistant(ws.app.state.store, participant, with_seed=False)
        memories = await memory.recall(assistant_id)
        log.info("call for %s: assistant %s, %d memories in the prompt", participant.get("_id") or name, assistant_id, len(memories))
        mode = "Readonly" if assistant_id else "off"
        up = BackboardUpstream(backboard_setup(name, games, assistant_id=assistant_id, memory_mode=mode, profile=profile,
                                               memories=memories))
        up.assistant_id, up.memories = assistant_id, memories
        return up
    return await gemini_upstream(name, games, participant)


async def gemini_upstream(name: str, games: list[str], participant: dict) -> GeminiUpstream:
    profile = participant.get("careProfile") or {}
    assistant_id = participant.get("backboardAssistantId") if can_remember(participant) else None
    memories = await memory.recall(assistant_id, " ".join(profile.get("interests", [])))
    up = GeminiUpstream(build_setup(name, games, profile=profile, memories=memories))
    up.assistant_id, up.memories = assistant_id, memories
    return up


async def connect_upstream(ws: WebSocket, name: str, games: list[str], participant: dict):
    """Connected upstream, or None after telling the browser why (e.g. Backboard refused: no credits for realtime
    audio). With the Gemini fallback back on, a refused Backboard session carries on directly with Gemini."""
    up = await open_upstream(ws, name, games, participant)
    try:
        await up.connect()
        return up
    except Exception as e:  # noqa: BLE001
        log.warning("could not reach %s: %r", up.label, e)
        error = f"Could not reach {up.label}: {e}"[:300]
    # DEV: Backboard only. Un-comment to fall back to Gemini Live directly when Backboard refuses.
    # if isinstance(up, BackboardUpstream) and settings.gemini_api_key:
    #     log.warning("falling back to Gemini Live directly")
    #     up = await gemini_upstream(name, games, participant)
    #     try:
    #         await up.connect()
    #         return up
    #     except Exception as e:
    #         error = f"Could not reach {up.label}: {type(e).__name__}"
    await ws.send_json({"type": "error", "message": error})
    await ws.close()
    return None


async def run(ws: WebSocket) -> None:
    await ws.accept()
    if not available():
        key = "BACKBOARD_API_KEY" if transport() == "backboard" else "GEMINI_API_KEY"
        await ws.send_json({"type": "error", "message": f"{key} is not set on the backend"})
        await ws.close()
        return

    participant = await load_participant(ws)
    profile = participant.get("careProfile") or {}
    name = (ws.query_params.get("name") or profile.get("preferredName") or participant.get("alias") or "").strip()[:40] or "friend"
    games = [g for g in (ws.query_params.get("games") or "").split(",") if g in GAMES] or list(GAMES)
    phone = normalize_phone(ws.query_params.get("phone") or "")
    state = GameState(patient_name=name, enabled_games=games, caregiver_phone=phone, session_id=uuid.uuid4().hex)
    nudge_after = SLOW_NUDGE_AFTER_S if needs_slow_pacing(profile) else NUDGE_AFTER_S
    started_at = datetime.now(timezone.utc)
    user_buf = ai_buf = ""
    stopped = False
    last_activity = time.monotonic()
    nudges = 0
    user_turns = last_reminded_turn = 0
    recent_words: list[int] = []  # output word counts of recent model turns, for the brevity reminder
    said: list[str] = []  # the person's finished turns, for memory.digest_session; never stored
    remembered: list[str] = []  # facts saved during the call with the remember tool

    up = await connect_upstream(ws, name, games, participant)
    if up is None:
        return
    assistant_id = getattr(up, "assistant_id", None)  # this patient's own memory; fixed for the whole call

    def remember(fact: str) -> dict:
        fact = fact.strip()[:300]
        if not fact:
            return {"ok": False, "error": "No fact given."}
        if not assistant_id:
            return {"ok": False, "error": "Memories are not kept for this person."}
        if memory.is_known(fact, up.memories + remembered, name):
            return {"ok": True, "note": "Already remembered."}
        remembered.append(fact)
        background(if_still_remembering(ws, participant, memory.add(assistant_id, fact, kind="session")))
        log.info("remember for %s -> assistant %s: %r", participant.get("_id"), assistant_id, fact[:80])
        return {"ok": True}

    async def tool(name: str, args: dict) -> dict:
        res = remember(str(args.get("fact", ""))) if name == "remember" else await run_tool(state, name, args, None)
        await ws.send_json({"type": "tool", "name": name, "args": args, "result": res, "state": state.view()})
        return res

    async def finalize_user() -> None:
        nonlocal user_buf, user_turns
        if user_buf.strip():
            user_turns += 1
            said.append(user_buf.strip())
            await ws.send_json({"type": "user_text", "text": user_buf.strip()})
        user_buf = ""

    async def finish_ai() -> None:
        nonlocal ai_buf, recent_words
        if ai_buf.strip():
            await ws.send_json({"type": "ai_done", "text": ai_buf.strip()})
            recent_words = (recent_words + [len(ai_buf.split())])[-2:]
        ai_buf = ""

    async def hard_stop(say_goodbye: bool = True) -> None:
        nonlocal stopped, nudges
        if stopped:
            return
        stopped = True
        nudges = MAX_NUDGES  # no nudging after a stop until the person speaks again
        await tool("stop", {})
        await ws.send_json({"type": "interrupt"})
        if say_goodbye:
            await up.say(GOODBYE)

    async def from_browser() -> None:
        nonlocal last_activity
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes"):
                await up.send_audio(msg["bytes"])
            elif msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "stop":
                    await hard_stop()
                elif data.get("type") == "text" and data.get("text", "").strip():  # typed input or page events
                    last_activity = time.monotonic()
                    await up.say(data["text"])

    async def nudger() -> None:
        """The model only speaks when spoken to; after a long silence, prompt it to carry the conversation on."""
        nonlocal last_activity, nudges
        while True:
            await asyncio.sleep(1)
            if nudges >= MAX_NUDGES or time.monotonic() - last_activity < nudge_after:
                continue
            last_activity = time.monotonic()
            nudges += 1
            if nudges < MAX_NUDGES:
                await up.say(NUDGE)
            else:  # no reply to repeated nudges: note it, rest the screen, wait for the person
                await tool("note_response", {"engagement": "withdrawn", "note": "No reply to several gentle prompts."})
                await tool("end_game", {})

    async def table_watcher() -> None:
        """Remember the Order: follow the table with the robot's camera while the person restores the row,
        and have the companion speak the cue at the right moment (decided by games/table_watch.py)."""
        nonlocal last_activity
        ticks = 0
        last_robot = None
        while True:
            await asyncio.sleep(TABLE_EVERY_S)
            ticks += 1
            if state.game == "order_memory" and ticks % 25 == 0:  # ~every 30 s: motor temperatures
                if await check_motors(state):
                    await ws.send_json({"type": "tool", "name": "alert_caregiver", "args": {}, "result": {"ok": True}, "state": state.view()})
            ex = state.view().get("exercise") or {}
            if state.game != "order_memory" or not (ex.get("watching") or state.pending_say or (state.robot or {}).get("status") == "moving"):
                continue
            try:
                res = await watch_table(state)
            except Exception:  # noqa: BLE001 - the camera must never break the call
                log.exception("table watch failed")
                continue
            robot_now = (state.robot or {}).get("last"), (state.robot or {}).get("status")
            if res.get("events") or robot_now != last_robot:  # keep the patient screen's table live
                await ws.send_json({"type": "tool", "name": "watch_table", "args": {}, "result": {"events": res.get("events")}, "state": state.view()})
                last_robot = robot_now
            if res.get("events"):
                last_activity = time.monotonic()  # the person is busy at the table: don't nudge
            if res.get("say"):
                last_activity = time.monotonic()
                await ws.send_json({"type": "tool", "name": "watch_table", "args": {}, "result": res, "state": state.view()})
                await up.say(TABLE_SAY.format(say=res["say"]))

    async def from_model() -> None:
        nonlocal user_buf, ai_buf, stopped, last_activity, nudges, recent_words, last_reminded_turn
        greeted = False
        async for ev in up.events():
            last_activity = time.monotonic()
            if ev.kind == "ready":
                if not greeted:
                    greeted = True
                    interests = profile.get("interests") or []
                    extra = GREETING_INTEREST.format(interest=interests[0]) if interests else ""
                    await up.say(GREETING.format(name=name, extra=extra))
            elif ev.kind == "tool_calls":
                await finalize_user()
                await up.send_tool_results([(c, await tool(c["name"], c["args"])) for c in ev.calls])
            elif ev.kind == "user_text":
                user_buf += ev.text
                nudges = 0
                await ws.send_json({"type": "user_partial", "text": user_buf})
                if not stopped and STOP_RE.search(user_buf):  # deterministic stop, independent of the model
                    await hard_stop()
            elif ev.kind == "ai_text":
                await finalize_user()
                ai_buf += ev.text
                await ws.send_json({"type": "ai_delta", "text": ev.text})
            elif ev.kind == "audio":
                await finalize_user()
                await ws.send_json({"type": "audio", "delta": ev.data, "rate": ev.rate})
            elif ev.kind == "interrupted":
                await ws.send_json({"type": "interrupt"})
                await finish_ai()
            elif ev.kind == "turn_done":
                await finish_ai()
                stopped = False  # ready for the next stop request
                if should_remind(user_turns, last_reminded_turn, recent_words):
                    last_reminded_turn, recent_words = user_turns, []
                    await up.add_context(REMINDER)
            elif ev.kind == "error":
                await ws.send_json({"type": "error", "message": ev.text})

    tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_model()), asyncio.create_task(nudger()),
             asyncio.create_task(table_watcher())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for d in done:
            if d.exception():
                log.warning("live session ended: %r", d.exception())
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)  # the reader must be gone before close() reads
        if user_buf.strip():  # cut off mid-turn; the browser may be gone, so just keep it for the digest
            said.append(user_buf.strip())
        await save_record(ws, state, started_at, participant.get("_id"))
        summary = session_summary(state)
        if summary and state.caregiver_phone:  # Photon: the caregiver hears how it went without asking
            background(send_alert("session_summary", state.session_id, summary, to=state.caregiver_phone, patient=state.patient_name))
        background(close_quietly(up))  # Backboard's stop handshake can take a moment; don't hold the handler
        if assistant_id:
            background(if_still_remembering(ws, participant, memory.digest_session(assistant_id, name, said, remembered)))
        else:
            log.info("not saving memories: %s", "no resident picked" if not participant
                     else "no consent to remember" if not can_remember(participant) else "Backboard assistant unavailable")


async def if_still_remembering(ws: WebSocket, participant: dict, write) -> None:
    """Run a memory write only if consent is still on: a nurse may turn it off during the call, so it is read
    again from the store before every save."""
    store, pid = getattr(ws.app.state, "store", None), participant.get("_id")
    try:
        fresh = await store.get("participants", pid) if store is not None and pid else None
    except Exception as e:  # noqa: BLE001
        log.warning("could not re-check consent for %s: %r", pid, e)
        fresh = None
    if fresh and can_remember(fresh):
        await write
    else:
        write.close()  # never awaited: nothing is sent
        log.info("not saving memory for %s: consent to remember is off now", pid)


async def close_quietly(up) -> None:
    try:
        await up.close()
    except Exception as e:  # noqa: BLE001
        log.warning("closing %s: %r", up.label, e)


async def load_participant(ws: WebSocket) -> dict:
    """The participant picked on the setup card (?participantId=), or {} for a name-only session."""
    store, pid = getattr(ws.app.state, "store", None), ws.query_params.get("participantId")
    if store is None or not pid:
        return {}
    try:
        return await store.get("participants", pid) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("could not load participant %s: %r", pid, e)
        return {}


async def save_record(ws: WebSocket, state: GameState, started_at: datetime, participant_id: str | None = None) -> None:
    """Session summary for the nurse screen. We keep no raw transcripts (Backboard keeps its own thread history)."""
    store = getattr(ws.app.state, "store", None)
    if store is None:
        return
    try:
        await store.insert("companion_sessions", {
            "_id": uuid.uuid4().hex, "participantId": participant_id, "patientName": state.patient_name,
            "startedAt": started_at, "endedAt": datetime.now(timezone.utc),
            "gamesPlayed": state.games_played, "observations": state.observations, "alerts": state.alerts,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("could not save companion session: %r", e)
