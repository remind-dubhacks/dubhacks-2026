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

import websockets
from fastapi import WebSocket

from ..config import settings
from .agent import GEMINI_DECLS, STOP_RE
from .tools import GameState, run_tool

log = logging.getLogger("remind.live")

INSTRUCTIONS = """You are ReMind, a warm, patient companion for a person living with dementia, in a care home. A caregiver is supervising.
You are speaking out loud: use one or two SHORT, simple sentences, a calm pace, and never lists. Never shame, quiz or correct personal memories. No medical advice.
You run games by calling tools. Never claim the robot did something unless a tool result says so.
- When the person asks to play a game, call start_game, then tell them the RIGHT order to put the objects in (target_order from the tool result; never call it the starting order) and ask them to say "done" when finished.
- When they say they are done, call check_arrangement. If wrong, say kindly it is not quite right and explain with the tool's reason, then invite another try. If attempts_left is 0, gently reveal the correct order. If correct, praise them.
- If they ask for help or seem upset or confused, call alert_caregiver and reassure them.
- If they ask what games exist, call list_games. If they want to stop, call stop.
Be patient: people may speak slowly and pause. Do not rush them."""

GREETING = "(The person has just sat down. Greet them warmly in one short sentence, say you are ReMind, and ask if they would like to play a game.)"
GOODBYE = "(The person stopped the session. Say a brief, kind goodbye in one sentence.)"


def available() -> bool:
    return bool(settings.gemini_api_key)


def _setup() -> dict:
    return {"setup": {
        "model": f"models/{settings.gemini_live_model}",
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.gemini_live_voice}}},
        },
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
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

    state = GameState()
    user_buf = ai_buf = ""
    stopped = False
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
            nonlocal stopped
            if stopped:
                return
            stopped = True
            await tool("stop", {})
            await ws.send_json({"type": "interrupt"})
            if say_goodbye:
                await to_gem({"realtimeInput": {"text": GOODBYE}})

        async def notify(text: str) -> None:  # the robot finished: make the agent speak without a user turn
            await to_gem({"realtimeInput": {"text": text}})
            await ws.send_json({"type": "state", "state": state.view()})

        state.notify = notify
        await to_gem(_setup())

        async def from_browser() -> None:
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
                    elif data.get("type") == "text" and data.get("text", "").strip():  # typed input
                        await to_gem({"realtimeInput": {"text": data["text"]}})

        async def from_gem() -> None:
            nonlocal user_buf, ai_buf, stopped
            greeted = False
            async for raw in gem:
                ev = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                if "setupComplete" in ev and not greeted:
                    greeted = True
                    await to_gem({"realtimeInput": {"text": GREETING}})
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

        tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_gem())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for d in done:
                if d.exception():
                    log.warning("live session ended: %r", d.exception())
        finally:
            for t in tasks:
                t.cancel()
