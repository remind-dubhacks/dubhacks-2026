"""Grok Voice (realtime speech-to-speech) relay.

Browser <-> this server <-> wss://api.x.ai/v1/realtime. The server holds the API key, runs the tools
locally and never lets the model drive the robot directly. Audio is PCM16 mono 24 kHz both ways.
Docs: https://docs.x.ai/docs/guides/voice/agent
"""
import asyncio
import base64
import json
import logging


import websockets
from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings
from .agent import STOP_RE
from .tools import TOOL_SCHEMAS, GameState, run_tool

log = logging.getLogger("remind.realtime")

INSTRUCTIONS = """You are ReMind, a warm, patient companion for a person living with dementia, in a care home. A caregiver is supervising.
You are speaking out loud: use one or two SHORT, simple sentences, a calm pace, and never use lists. Never shame, quiz or correct personal memories. No medical advice.
You run games by calling tools. Never claim the robot did something unless a tool result says so.
- When the person asks to play a game, call start_game, then say the target order (from the tool result) and ask them to say "done" when finished.
- When they say they are done, call check_arrangement. If wrong, say kindly it is not quite right and explain with the tool's reason, then invite another try. If attempts_left is 0, gently reveal the correct order. If correct, praise them.
- If they ask for help or seem upset or confused, call alert_caregiver and reassure them.
- If they ask what games exist, call list_games. If they want to stop, call stop."""

GREETING_PROMPT = "(The person has just sat down. Greet them warmly in one short sentence by saying you are ReMind, and ask if they would like to play a game.)"

# The realtime API takes flat tool definitions, not the chat-completions {"type","function":{...}} wrapper.
REALTIME_TOOLS = [{"type": "function", **t["function"]} for t in TOOL_SCHEMAS]


def available() -> bool:
    return bool(settings.xai_api_key)


async def run(ws: WebSocket) -> None:
    await ws.accept()
    if not available():
        await ws.send_json({"type": "error", "message": "XAI_API_KEY is not set on the backend"})
        await ws.close()
        return

    state = GameState()
    table: list[str] | None = None
    need_response = False
    url = f"{settings.xai_voice_url}?model={settings.xai_voice_model}"

    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {settings.xai_api_key}"}, max_size=None) as xai:

        async def to_xai(obj: dict) -> None:
            await xai.send(json.dumps(obj))

        async def tool(name: str, args: dict) -> dict:
            res = await run_tool(state, name, args, table)
            await ws.send_json({"type": "tool", "name": name, "args": args, "result": res, "state": state.view()})
            return res

        await to_xai({"type": "session.update", "session": {
            "voice": settings.xai_voice,
            "instructions": INSTRUCTIONS,
            "turn_detection": {"type": "server_vad"},
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": 24000}, "transcription": {"model": "grok-transcribe"}},
                "output": {"format": {"type": "audio/pcm", "rate": 24000}},
            },
            "tools": REALTIME_TOOLS,
        }})
        await to_xai({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": GREETING_PROMPT}]}})
        await to_xai({"type": "response.create"})

        async def from_browser() -> None:
            nonlocal table
            try:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("bytes"):
                        await to_xai({"type": "input_audio_buffer.append", "audio": base64.b64encode(msg["bytes"]).decode()})
                    elif msg.get("text"):
                        data = json.loads(msg["text"])
                        if data.get("type") == "table":
                            table = data.get("order")
                        elif data.get("type") == "stop":
                            await emergency_stop()
            except WebSocketDisconnect:
                return

        async def emergency_stop() -> None:
            await to_xai({"type": "response.cancel"})
            await tool("stop", {})
            await ws.send_json({"type": "interrupt"})

        async def from_xai() -> None:
            nonlocal need_response
            async for raw in xai:
                ev = json.loads(raw)
                t = ev.get("type", "")
                if t == "response.output_audio.delta":
                    await ws.send_json({"type": "audio", "delta": ev.get("delta", "")})
                elif t == "response.output_audio_transcript.delta":
                    await ws.send_json({"type": "ai_delta", "text": ev.get("delta", "")})
                elif t == "response.output_audio_transcript.done":
                    await ws.send_json({"type": "ai_done", "text": ev.get("transcript", "")})
                elif t == "input_audio_buffer.speech_started":
                    await ws.send_json({"type": "interrupt"})  # barge-in: drop queued playback
                elif t.startswith("conversation.item.input_audio_transcription"):
                    text = ev.get("transcript") or ev.get("text") or ""
                    final = t.endswith("completed")
                    await ws.send_json({"type": "user_text" if final else "user_partial", "text": text})
                    if final and STOP_RE.search(text):  # deterministic stop, independent of the model
                        await emergency_stop()
                elif t == "response.function_call_arguments.done":
                    try:
                        args = json.loads(ev.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    res = await tool(ev.get("name", ""), args)
                    await to_xai({"type": "conversation.item.create", "item": {
                        "type": "function_call_output", "call_id": ev.get("call_id"), "output": json.dumps(res)}})
                    need_response = True
                elif t == "response.done":
                    if need_response:  # send once, after every parallel tool output is in
                        need_response = False
                        await to_xai({"type": "response.create"})
                elif t == "error":
                    log.error("xAI error: %s", ev)
                    await ws.send_json({"type": "error", "message": json.dumps(ev.get("error", ev))[:300]})
                else:
                    log.debug("xAI event: %s", t)

        tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_xai())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for tk in tasks:
                tk.cancel()
