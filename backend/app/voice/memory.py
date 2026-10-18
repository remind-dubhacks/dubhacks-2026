"""Long-term patient memory in Backboard (https://docs.backboard.io). One Backboard assistant per participant,
because memories are scoped to an assistant. The care profile (models.CareProfile) stays in our store; Backboard
holds what grows over time: stories, people, favourites, what engaged them.

During a call, Backboard Realtime (voice/upstreams.py, memory="Auto") retrieves and saves memories itself. This
module only manages assistants, seeds them from the care profile, and reads memories for the nurse and for the
direct-Gemini fallback.

Best effort throughout: with no BACKBOARD_API_KEY, or on a timeout or HTTP error, calls log and return an empty
result, so a session never fails or waits longer than BACKBOARD_TIMEOUT_S because of memory."""
import logging

import httpx

from ..config import settings

log = logging.getLogger("remind.memory")

FACT_PROMPT = (
    "You keep notes for a companion who talks with an older person living with dementia in a care home. "
    "Extract short, lasting facts about the person: people in their life (and whether living), places, work, "
    "favourites (films, stars, music, food), stories they enjoy telling, topics that upset them, and what engaged "
    "or tired them in a session. Ignore game mechanics, greetings and anything the companion said. "
    "Never record medications, diagnoses or test scores."
)
RECALL_LIMIT = 15
_transport: httpx.AsyncBaseTransport | None = None  # tests swap in httpx.MockTransport


def enabled() -> bool:
    return bool(settings.backboard_api_key)


async def _call(method: str, path: str, **kw) -> dict | None:
    if not enabled():
        return None
    try:
        async with httpx.AsyncClient(base_url=settings.backboard_url, timeout=settings.backboard_timeout_s, transport=_transport,
                                     headers={"X-API-Key": settings.backboard_api_key}) as client:
            r = await client.request(method, path, **kw)
            r.raise_for_status()
            return r.json() if r.content else {}
    except (httpx.HTTPError, ValueError) as e:
        log.warning("backboard %s %s failed: %r", method, path, e)
        return None


async def create_assistant(alias: str) -> str | None:
    res = await _call("POST", "/assistants", json={
        "name": f"ReMind memory: {alias}"[:255],
        "system_prompt": "You remember facts about one care-home resident for their companion.",
        "custom_fact_extraction_prompt": FACT_PROMPT,
    })
    return (res or {}).get("assistant_id")


async def add(assistant_id: str, content: str, kind: str = "fact") -> bool:
    return await _call("POST", f"/assistants/{assistant_id}/memories", json={"content": content, "metadata": {"kind": kind}}) is not None


async def recall(assistant_id: str | None, query: str = "") -> list[str]:
    """Facts for the system prompt: a relevance search when there is a query, else everything (newest first)."""
    if not assistant_id:
        return []
    if query:
        res = await _call("POST", f"/assistants/{assistant_id}/memories/search", json={"query": query, "limit": RECALL_LIMIT})
    else:
        res = await _call("GET", f"/assistants/{assistant_id}/memories", params={"page": 1, "page_size": RECALL_LIMIT})
    return [m["content"] for m in (res or {}).get("memories", []) if m.get("content")][:RECALL_LIMIT]


async def list_all(assistant_id: str) -> list[dict]:
    res = await _call("GET", f"/assistants/{assistant_id}/memories")
    return [{"id": m["id"], "content": m["content"]} for m in (res or {}).get("memories", [])]


def profile_memories(profile: dict) -> list[str]:
    """Care-sheet lines worth seeding as memories, so search can surface them alongside what is learnt later."""
    return [*profile.get("lifeStory", []), *(f"Enjoys talking about {i}." for i in profile.get("interests", []))]


async def seed(assistant_id: str, profile: dict) -> None:
    for line in profile_memories(profile):
        await add(assistant_id, line, kind="care_profile")


async def ensure_assistant(store, participant: dict, with_seed: bool = True) -> str | None:
    """The participant's assistant id, creating it on first use (stored on the participant). With with_seed=False
    the caller seeds it (live.py does so in the background, so a first session does not wait for it)."""
    if participant.get("backboardAssistantId") or not enabled():
        return participant.get("backboardAssistantId")
    aid = await create_assistant(participant.get("alias", "resident"))
    if not aid:
        return None
    participant["backboardAssistantId"] = aid
    await store.update("participants", participant["_id"], {"backboardAssistantId": aid})
    if with_seed:
        await seed(aid, participant.get("careProfile") or {})
    return aid
