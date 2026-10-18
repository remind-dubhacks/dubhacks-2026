"""Step-by-step check of patient memory against the real Backboard, to see exactly where remembering breaks.

Uses the same code as a call (app.voice.memory), with backend/.env. Prints every Backboard request with its status
and timing, and stops at the first step that fails.

    uv run python -m scripts.memory_check                    # demo resident (Rose)
    uv run python -m scripts.memory_check <participant_id>
    uv run python -m scripts.memory_check --dry-run          # everything except saving the test fact

Without --dry-run it saves one real memory ("<name>'s favourite food is hot dogs.") to that resident.
"""
import argparse
import asyncio
import sys
import time

import httpx

from app.config import settings
from app.db import connect
from app.main import DEMO_PARTICIPANT
from app.voice import memory

SAID = "My favourite food is hot dogs. Please remember that."


class Trace(httpx.AsyncHTTPTransport):
    """Prints each Backboard request: method, path, status, time and the start of the reply."""
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        t = time.perf_counter()
        try:
            r = await super().handle_async_request(request)
        except httpx.HTTPError as e:
            print(f"      {request.method} {request.url.path} -> {type(e).__name__} after {time.perf_counter() - t:.1f}s")
            raise
        body = (await r.aread()).decode(errors="replace").replace("\n", " ")
        print(f"      {request.method} {request.url.path} -> {r.status_code} in {time.perf_counter() - t:.1f}s  {body[:160]}")
        return r


def step(n: int, title: str) -> None:
    print(f"\n{n}. {title}")


def fail(why: str) -> None:
    print(f"   FAIL: {why}")
    sys.exit(1)


def ok(what: str) -> None:
    print(f"   ok: {what}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("participant_id", nargs="?", default=DEMO_PARTICIPANT["_id"])
    ap.add_argument("--dry-run", action="store_true", help="do not save the test fact")
    args = ap.parse_args()
    memory._transport = Trace()

    step(1, "Settings")
    if not settings.backboard_api_key:
        fail("BACKBOARD_API_KEY is not set in backend/.env")
    print(f"   backboard_url={settings.backboard_url}  timeouts: read {settings.backboard_timeout_s}s, "
          f"write {settings.backboard_write_timeout_s}s  digest model: {settings.backboard_digest_model or '(Backboard default)'}")
    store = await connect()
    print(f"   store: {'MongoDB' if store.persistent else 'in-memory (resets on restart; set MONGODB_URI)'}")

    step(2, "Resident")
    p = await store.get("participants", args.participant_id)
    if not p and args.participant_id == DEMO_PARTICIPANT["_id"]:
        p = dict(DEMO_PARTICIPANT)
        await store.insert("participants", p)
    if not p:
        fail(f"no participant {args.participant_id!r} in the store")
    name = (p.get("careProfile") or {}).get("preferredName") or p.get("alias") or "resident"
    print(f"   {p['_id']} ({name}); stored assistant: {p.get('backboardAssistantId')}")
    if not p.get("consentFlags", {}).get("rememberPreferences"):
        fail("consentFlags.rememberPreferences is off: nothing is remembered for this resident")
    ok("consent to remember")

    step(3, f"Their own assistant (named {memory.assistant_name(p)!r})")
    aid = await memory.ensure_assistant(store, p)
    if not aid:
        fail("no assistant: Backboard could not be reached or refused (see the request lines above)")
    info = await memory._call("GET", f"/assistants/{aid}")
    if not isinstance(info, dict) or info.get("name") != memory.assistant_name(p):
        fail(f"assistant {aid} is named {(info or {}).get('name')!r}, not {memory.assistant_name(p)!r}: wrong person")
    ok(f"assistant {aid}, name matches")

    step(4, "What it remembers now")
    before = await memory.list_all(aid, timeout_s=settings.backboard_write_timeout_s)
    for m in before:
        print(f"      - {m['content']}")
    ok(f"{len(before)} memories")

    step(5, f"Extract facts from: {SAID!r}")
    facts = await memory.extract_facts(aid, name, [SAID], [m["content"] for m in before])
    print(f"   extracted: {facts}")
    if not facts:
        print("   WARN: no facts extracted (see the /threads/messages line above); the after-call digest would save nothing."
              " The remember tool does not depend on this step.")
    mid = await memory.list_all(aid, timeout_s=settings.backboard_write_timeout_s)
    if len(mid) != len(before):
        fail(f"extraction itself changed the memories ({len(before)} -> {len(mid)}): it must run with memory off")
    ok("extraction did not write any memories")

    fact = next((f for f in facts if "hot dog" in f.lower()), f"{name}'s favourite food is hot dogs.")
    if args.dry_run:
        print("\n(dry run: not saving)")
        return
    step(6, f"Save {fact!r} (what the remember tool does)")
    if memory.is_known(fact, [m["content"] for m in before], name):
        ok("already remembered; not saved again")
    elif not await memory.add(aid, fact, kind="session"):
        fail("Backboard did not save it (see the request line above: a timeout means raise BACKBOARD_WRITE_TIMEOUT_S)")
    else:
        ok("saved")

    step(7, "Read it back")
    after = [m["content"] for m in await memory.list_all(aid, timeout_s=settings.backboard_write_timeout_s)]
    if not any("hot dog" in c.lower() for c in after):
        fail("not in the memory list yet (Backboard may still be processing it; run this again in a minute)")
    ok("in the memory list")
    found = await memory.recall(aid, "favourite food")
    print(f"   search 'favourite food': {found}")
    prompt = await memory.recall(aid)
    if not any("hot dog" in c.lower() for c in prompt):
        fail(f"not among the {memory.RECALL_LIMIT} memories a call puts in its prompt")
    ok("a new call would have it in its prompt")
    print("\nAll good: start a call as this resident and ask about their favourite food.")


if __name__ == "__main__":
    asyncio.run(main())
