"""A/B eval of the Gemini Live companion: legacy prompt/config (A) vs current (B).

Sends a fixed list of patient turns as text to a real Live session and compares reply length,
question count and truncation. Needs GEMINI_API_KEY (backend/.env).

    uv run python -m scripts.eval_live                   # A/B table
    uv run python -m scripts.eval_live --check-reminder  # does the brevity reminder stay silent?
    uv run python -m scripts.eval_live --latency gemini      # time to first reply audio, direct
    uv run python -m scripts.eval_live --latency backboard   # ... through Backboard Realtime (BACKBOARD_API_KEY)
    uv run python -m scripts.eval_live --latency backboard --assistant <id>   # with memory="Auto" on that assistant
"""
import argparse
import asyncio
import json
import statistics
import sys
import textwrap
import time

import websockets

from app.config import settings
from app.voice.live import backboard_setup, build_setup, reminder_message
from app.voice.prompts.voice_system_prompt import LEGACY_PROMPT, VOICE_SYSTEM_PROMPT
from app.voice.upstreams import BackboardUpstream, GeminiUpstream
from app.voice.tools import GameState, run_tool

NAME = "Margaret"
GAMES = ["faces", "proverbs", "sounds"]  # reorder needs the robot
TURNS = [
    "Hello there. Who are you?",
    "My father used to take me fishing on the lake every summer when I was a girl.",
    "Could we look at some famous faces?",
    "Who is that?",
    "Oh, that hat reminds me, my sister Joan had one just like it. She wore it to church every Sunday.",
    "I'm not sure. I can't remember.",
    "What day is it today?",
    "Well you know, back then we didn't have much, but we had each other, and my mother would bake bread on "
    "Saturdays and the whole street could smell it, and the neighbours' children would come round asking for a slice.",
    "I'm a bit tired today.",
    "Can we do the sayings instead?",
]
TURN_TIMEOUT_S = 30
RUNS = {
    "A legacy": dict(prompt=LEGACY_PROMPT, vad="legacy", temperature=-1, max_output_tokens=0),
    "B current": dict(prompt=VOICE_SYSTEM_PROMPT),
}


async def connect(setup: dict):
    gem = await websockets.connect(f"{settings.gemini_live_url}?key={settings.gemini_api_key}", max_size=None)
    await gem.send(json.dumps(setup))
    while "setupComplete" not in json.loads(await gem.recv()):
        pass
    return gem


async def one_turn(gem, state: GameState, text: str) -> str:
    """Send one user turn; answer tool calls; return the output transcription once the model's turn completes."""
    await gem.send(json.dumps({"realtimeInput": {"text": text}}))
    out, tools = "", []
    while True:
        ev = json.loads(await asyncio.wait_for(gem.recv(), TURN_TIMEOUT_S))
        if "toolCall" in ev:
            responses = []
            for fc in ev["toolCall"].get("functionCalls", []):
                tools.append(fc["name"])
                res = await run_tool(state, fc["name"], fc.get("args") or {}, None)
                responses.append({"id": fc.get("id"), "name": fc["name"], "response": {"result": res}})
            await gem.send(json.dumps({"toolResponse": {"functionResponses": responses}}))
            continue
        sc = ev.get("serverContent") or {}
        out += (sc.get("outputTranscription") or {}).get("text", "")
        if sc.get("turnComplete"):
            if out.strip():
                return out.strip()
            if not tools:  # a tool-only turn completes before the spoken reply; otherwise the model said nothing
                return "<no speech>"


async def run_suite(label: str, opts: dict) -> list[str]:
    """Runs TURNS in one session; if the server drops the session, notes it and carries on in a fresh one."""
    state = GameState(patient_name=NAME, enabled_games=GAMES)
    replies = []
    gem = await connect(build_setup(NAME, GAMES, **opts))
    try:
        for t in TURNS:
            try:
                replies.append(await one_turn(gem, state, t))
            except asyncio.TimeoutError:
                replies.append("<timeout>")
            except websockets.ConnectionClosed as e:
                replies.append(f"<session closed: {e.rcvd.code if e.rcvd else '?'} {e.rcvd.reason if e.rcvd else ''}>")
                gem = await connect(build_setup(NAME, GAMES, **opts))
            print(f"  {label}: turn {len(replies)}/{len(TURNS)}", flush=True)
    finally:
        await gem.close()
    return replies


def metrics(reply: str) -> dict:
    return {"words": len(reply.split()), "questions": reply.count("?"), "truncated": not reply.rstrip().endswith((".", "!", "?", '"'))}


def report(results: dict[str, list[str]]) -> None:
    labels = list(results)
    for i, turn in enumerate(TURNS):
        print(f"\n[{i + 1}] USER: {turn}")
        for lb in labels:
            r = results[lb][i]
            m = metrics(r)
            flags = f"{m['words']}w {m['questions']}q" + (" TRUNCATED?" if m["truncated"] else "")
            print(textwrap.indent(textwrap.fill(f"{lb} ({flags}): {r}", 110), "    "))
    print("\nSUMMARY")
    for lb in labels:
        ms = [metrics(r) for r in results[lb]]
        words = [m["words"] for m in ms]
        print(f"  {lb}: mean {statistics.mean(words):.1f} words, max {max(words)}, "
              f"<=1 question {sum(m['questions'] <= 1 for m in ms)}/{len(ms)}, truncated {sum(m['truncated'] for m in ms)}")


async def check_reminder() -> None:
    """Send the reminder with turnComplete=False and watch for any model output."""
    state = GameState(patient_name=NAME, enabled_games=GAMES)
    async with await connect(build_setup(NAME, GAMES)) as gem:
        print("warm-up reply:", await one_turn(gem, state, TURNS[1]))
        await gem.send(json.dumps(reminder_message()))
        spoke = []
        try:
            while True:
                ev = json.loads(await asyncio.wait_for(gem.recv(), 4))
                sc = ev.get("serverContent") or {}
                if sc.get("modelTurn") or sc.get("outputTranscription") or "toolCall" in ev:
                    spoke.append((sc.get("outputTranscription") or {}).get("text", "<audio/tool>"))
        except asyncio.TimeoutError:
            pass
        print("PASS: model stayed silent after the reminder" if not spoke else f"FAIL: model responded to the reminder: {''.join(spoke)!r}")
        print("next reply:", await one_turn(gem, state, TURNS[8]))


async def latency(transport: str, assistant_id: str | None) -> None:
    """Time from sending a turn to the first reply audio, through the same adapters the relay uses."""
    if transport == "backboard":
        up = BackboardUpstream(backboard_setup(NAME, GAMES, assistant_id=assistant_id, memory_mode="Auto" if assistant_id else "off"))
    else:
        up = GeminiUpstream(build_setup(NAME, GAMES))
    state = GameState(patient_name=NAME, enabled_games=GAMES)
    t0 = time.perf_counter()
    await up.connect()
    events = up.events()
    assert (await anext(events)).kind == "ready"
    print(f"{up.label}: connected in {(time.perf_counter() - t0) * 1000:.0f} ms")
    firsts = []
    try:
        for i, turn in enumerate(TURNS[:6], 1):
            t0, first = time.perf_counter(), None
            await up.say(turn)
            try:
                while True:
                    ev = await asyncio.wait_for(anext(events), TURN_TIMEOUT_S)
                    if ev.kind == "tool_calls":
                        await up.send_tool_results([(c, await run_tool(state, c["name"], c["args"], None)) for c in ev.calls])
                    elif ev.kind == "audio" and first is None:
                        first = time.perf_counter() - t0
                    elif ev.kind == "turn_done" and first is not None:
                        break
            except asyncio.TimeoutError:
                pass
            print(f"  turn {i}: " + (f"{first * 1000:.0f} ms to first audio" if first else "no audio (timeout)"), flush=True)
            if first:
                firsts.append(first)
    finally:
        await up.close()
    if firsts:
        print(f"{up.label}: median {statistics.median(firsts) * 1000:.0f} ms, max {max(firsts) * 1000:.0f} ms over {len(firsts)} turns")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-reminder", action="store_true")
    ap.add_argument("--latency", choices=["gemini", "backboard"])
    ap.add_argument("--assistant", help="Backboard assistant id: measure with memory=Auto")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # transcripts can hold non-cp1252 characters on Windows
    if args.latency:
        key = settings.backboard_api_key if args.latency == "backboard" else settings.gemini_api_key
        if not key:
            raise SystemExit(f"{'BACKBOARD' if args.latency == 'backboard' else 'GEMINI'}_API_KEY is not set (backend/.env)")
        await latency(args.latency, args.assistant)
        return
    if not settings.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set (backend/.env)")
    if args.check_reminder:
        await check_reminder()
        return
    results = {}
    for label, opts in RUNS.items():
        results[label] = await run_suite(label, opts)
    report(results)


if __name__ == "__main__":
    asyncio.run(main())
