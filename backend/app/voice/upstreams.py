"""Where the live relay's audio goes: straight to Gemini Live, or to Gemini Live through Backboard Realtime.

Both adapters take the same calls and turn their provider's messages into the same `Event`s, so live.run never
knows which one it is talking to. Backboard (https://docs.backboard.io, /api/threads/realtime) adds automatic
long-term memory (memory="Auto"): it retrieves and saves facts per assistant, i.e. per patient.

    send_audio(pcm16)       raw 16 kHz mic audio
    say(text)               text the model should answer (greeting, nudges, page events)
    add_context(text)       text the model should absorb silently (brevity reminder)
    send_tool_results(...)  answers to a `tool_calls` event
    events()                ready | user_text | ai_text | audio | tool_calls | interrupted | turn_done | error
"""
import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass, field

import websockets

from ..config import settings

log = logging.getLogger("remind.upstream")


@dataclass
class Event:
    kind: str
    text: str = ""
    data: str = ""  # base64 PCM16 (audio)
    rate: int = 24000
    calls: list[dict] = field(default_factory=list)  # [{id, name, args}]


def context_message(text: str) -> dict:
    """Gemini Live: add text to context without asking for a reply."""
    return {"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": False}}


class GeminiUpstream:
    label = "Gemini Live"

    def __init__(self, setup: dict):
        self.setup = setup  # live.build_setup()

    async def connect(self) -> None:
        self.ws = await websockets.connect(f"{settings.gemini_live_url}?key={settings.gemini_api_key}", max_size=None)
        await self._send(self.setup)

    async def close(self) -> None:
        await self.ws.close()

    async def _send(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj))

    async def send_audio(self, pcm: bytes) -> None:
        await self._send({"realtimeInput": {"audio": {"data": base64.b64encode(pcm).decode(), "mimeType": "audio/pcm;rate=16000"}}})

    async def say(self, text: str) -> None:
        await self._send({"realtimeInput": {"text": text}})

    async def add_context(self, text: str) -> None:
        await self._send(context_message(text))

    async def send_tool_results(self, results: list[tuple[dict, dict]]) -> None:
        await self._send({"toolResponse": {"functionResponses": [
            {"id": c["id"], "name": c["name"], "response": {"result": res}} for c, res in results]}})

    async def events(self):
        async for raw in self.ws:
            ev = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            if "setupComplete" in ev:
                yield Event("ready")
                continue
            if "toolCall" in ev:
                yield Event("tool_calls", calls=[{"id": fc.get("id"), "name": fc["name"], "args": fc.get("args") or {}}
                                                 for fc in ev["toolCall"].get("functionCalls", [])])
                continue
            sc = ev.get("serverContent")
            if not sc:
                if "error" in ev:
                    yield Event("error", text=json.dumps(ev["error"])[:300])
                continue
            if "inputTranscription" in sc:
                yield Event("user_text", text=sc["inputTranscription"].get("text", ""))
            if "outputTranscription" in sc:
                yield Event("ai_text", text=sc["outputTranscription"].get("text", ""))
            for part in (sc.get("modelTurn") or {}).get("parts", []):
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
                    yield Event("audio", data=inline["data"], rate=int(m.group(1)) if m else 24000)
            if sc.get("interrupted"):
                yield Event("interrupted")
            if sc.get("turnComplete"):
                yield Event("turn_done")


class BackboardUpstream:
    """Gemini Live via Backboard Realtime. Native Gemini messages (realtimeInput text, clientContent) go through
    `provider.event`, so greetings, nudges and the silent reminder behave exactly as with GeminiUpstream.
    Sessions are capped at 30 minutes; on `session.ended` we reconnect to the same thread, which resumes history."""
    label = "Backboard Realtime"
    MAX_RECONNECTS = 2
    STOP_WAIT_S = 3.0  # on close, give Backboard a moment to finish saving memories

    def __init__(self, setup: dict):
        self.setup = setup  # live.backboard_setup()
        self.thread_id: str | None = None
        self.closing = False

    async def connect(self) -> None:
        """Opens the socket, sends setup and waits for session.begin (Backboard wants no audio before it)."""
        self.ws = await websockets.connect(settings.backboard_realtime_url, max_size=None,
                                           additional_headers={"X-API-Key": settings.backboard_api_key})
        setup = dict(self.setup)
        if self.thread_id:  # resuming after the session cap: the thread carries the assistant
            setup.pop("assistant_id", None)
            setup["thread_id"] = self.thread_id
        await self.ws.send(json.dumps(setup))
        while True:
            ev = json.loads(await self.ws.recv())
            if ev.get("type") == "session.begin":
                self.thread_id = ev.get("thread_id") or self.thread_id
                return
            if ev.get("type") == "error":  # e.g. insufficient_credits: realtime audio needs paid credits
                await self.ws.close()
                raise ConnectionError(f"{ev.get('code')}: {ev.get('message')}")

    async def close(self) -> None:
        self.closing = True
        try:
            await self.ws.send(json.dumps({"type": "stop"}))
            async with asyncio.timeout(self.STOP_WAIT_S):
                async for raw in self.ws:
                    if isinstance(raw, str) and json.loads(raw).get("type") == "session.ended":
                        break
        except (TimeoutError, websockets.ConnectionClosed):
            pass
        await self.ws.close()

    async def _provider(self, event: dict) -> None:
        await self.ws.send(json.dumps({"type": "provider.event", "event": event}))

    async def send_audio(self, pcm: bytes) -> None:
        try:
            await self.ws.send(pcm)
        except websockets.ConnectionClosed:
            if self.closing:
                raise  # otherwise we are mid-reconnect: drop the frame

    async def say(self, text: str) -> None:
        await self._provider({"realtimeInput": {"text": text}})

    async def add_context(self, text: str) -> None:
        await self._provider(context_message(text))

    async def send_tool_results(self, results: list[tuple[dict, dict]]) -> None:
        await self.ws.send(json.dumps({"type": "tool.outputs", "outputs": [
            {"tool_call_id": c["id"], "name": c["name"], "output": json.dumps(res)} for c, res in results]}))

    async def events(self):
        yield Event("ready")  # connect() already waited for session.begin
        reconnects = 0
        streamed: set[str] = set()  # transcript items that arrived as deltas, so their .final is not repeated
        while True:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                ev = json.loads(raw)
                t = ev.get("type")
                if t == "audio.delta" and ev.get("data"):
                    yield Event("audio", data=ev["data"], rate=int(ev.get("sample_rate") or 24000))
                elif t in ("transcript.delta", "transcript.final"):
                    item = ev.get("item_id") or ""
                    if t == "transcript.delta":
                        streamed.add(item)
                    elif item in streamed:
                        continue
                    yield Event("user_text" if ev.get("role") == "user" else "ai_text", text=ev.get("text", ""))
                elif t == "tool.call" and not ev.get("hosted"):
                    args = ev.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args) if args.strip() else {}
                        except ValueError:
                            args = {}
                    yield Event("tool_calls", calls=[{"id": ev.get("tool_call_id"), "name": ev.get("name", ""), "args": args}])
                elif t == "interrupted":
                    yield Event("interrupted")
                elif t == "response.done":
                    yield Event("turn_done")
                elif t == "error":
                    yield Event("error", text=f"{ev.get('code', '')}: {ev.get('message', '')}"[:300])
                elif t == "session.ended":
                    break
            if self.closing or reconnects >= self.MAX_RECONNECTS:
                return
            reconnects += 1
            log.info("backboard session ended; resuming thread %s", self.thread_id)
            await self.connect()
