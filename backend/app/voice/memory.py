"""Long-term patient memory in Backboard (https://docs.backboard.io). One Backboard assistant per participant,
because memories are scoped to an assistant. The care profile (models.CareProfile) stays in our store; Backboard
holds what grows over time: stories, people, favourites, what engaged them.

During a call, Backboard Realtime (voice/upstreams.py, memory="Readonly") retrieves memories but saves none: with
memory="Auto" it saves facts before replying, which delayed turns where the person shared something by 1-2 s
(once 10 s), and it stored each retelling of a story again. Instead, after the call, digest_session extracts the
new facts from what the person said (through Backboard's text API, so every model call goes through Backboard),
drops any already remembered, and saves the rest. This module also manages assistants, seeds them from the care
profile, and reads memories for the nurse and for the direct-Gemini fallback.

Each assistant is named after the participant's id (assistant_name), and ensure_assistant looks it up by that name
before creating one. So a patient's memories survive even if our store loses the id it saved (an in-memory store
after a restart, or a wiped database), and are never split across two assistants.

Best effort throughout: with no BACKBOARD_API_KEY, or on a timeout or HTTP error, calls log and return an empty
result, so a session never fails or waits longer than BACKBOARD_TIMEOUT_S because of memory."""
import json
import logging
import re

import httpx

from .. import tasks
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
DIGEST_PROMPT = FACT_PROMPT + (
    " You are given what the person said in today's session and the facts already remembered about them. Return a "
    "JSON array of the new facts only, each one short sentence in the third person using their name. Leave out "
    "anything already remembered, even if worded differently. Return [] if there is nothing new."
)
DIGEST_TIMEOUT_S = 30.0  # runs after the session, so no one waits for it
ASSISTANT_PREFIX = "ReMind memory: "
SAME_FACT = 0.6  # word overlap (Jaccard) at which a new fact counts as already remembered
_STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "her", "his", "their", "she",
              "he", "they", "is", "was", "are", "has", "had", "who", "that", "which", "as", "by", "from", "it", "s"}
_transport: httpx.AsyncBaseTransport | None = None  # tests swap in httpx.MockTransport


def enabled() -> bool:
    return bool(settings.backboard_api_key)


async def _call(method: str, path: str, timeout_s: float | None = None, **kw) -> dict | list | None:
    if not enabled():
        return None
    try:
        async with httpx.AsyncClient(base_url=settings.backboard_url, timeout=timeout_s or settings.backboard_timeout_s,
                                     transport=_transport, headers={"X-API-Key": settings.backboard_api_key}) as client:
            r = await client.request(method, path, **kw)
            r.raise_for_status()
            return r.json() if r.content else {}
    except (httpx.HTTPError, ValueError) as e:
        log.warning("backboard %s %s failed: %r", method, path, e)
        return None


def assistant_name(participant: dict) -> str:
    """Stable, unique per participant: their id, not their alias (two residents can share a first name)."""
    return f"{ASSISTANT_PREFIX}{participant['_id']}"[:255]


async def find_assistant(name: str) -> str | None:
    """The assistant Backboard already has under this exact name, if any."""
    res = await _call("GET", "/assistants", params={"name": name, "limit": 1})
    found = [a for a in res if a.get("name") == name] if isinstance(res, list) else []
    return found[0].get("assistant_id") if found else None


async def create_assistant(name: str) -> str | None:
    res = await _call("POST", "/assistants", json={
        "name": name[:255],
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


def _words(text: str, ignore: set[str]) -> set[str]:
    return {w.removesuffix("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS | ignore}


def is_known(fact: str, known: list[str], patient: str = "") -> bool:
    """Backstop to the model's de-duplication: the fact shares most of its words with a remembered one. The patient's
    name is in nearly every fact, so it does not count."""
    ignore = set(re.findall(r"[a-z0-9]+", patient.lower()))
    words = _words(fact, ignore)
    if not words:
        return True
    return any(len(words & k) / len(words | k) >= SAME_FACT for k in (_words(f, ignore) for f in known))


def _digest_model() -> dict:
    """BACKBOARD_DIGEST_MODEL as provider/model (e.g. google/<a model from Backboard's GET /models>); unset = the
    assistant's default model."""
    provider, _, model = settings.backboard_digest_model.partition("/")
    return {"llm_provider": provider, "model_name": model} if model else {}


async def extract_facts(assistant_id: str, patient: str, utterances: list[str], known: list[str]) -> list[str]:
    """New facts from what the person said, by the model behind Backboard's text API in JSON mode, on a thread of the
    patient's own assistant with memory off (we choose what to save). [] on any failure: memory is best effort."""
    said = "\n".join(f"- {u}" for u in utterances)
    remembered = "\n".join(f"- {k}" for k in known) or "(nothing yet)"
    res = await _call("POST", "/threads/messages", timeout_s=DIGEST_TIMEOUT_S, json={
        "assistant_id": assistant_id, "system_prompt": DIGEST_PROMPT, "memory": "off", "json_output": True,
        "stream": False, **_digest_model(),
        "content": f"Person: {patient}\n\nWhat they said today:\n{said}\n\nAlready remembered:\n{remembered}",
    })
    if not isinstance(res, dict):
        return []
    messages = res.get("messages") or [res]  # ChatMessagesResponse, or the older single-message shape
    text = next((m.get("content") for m in reversed(messages) if m.get("content")), "")
    try:
        facts = json.loads(text)
    except ValueError:
        log.warning("fact extraction returned non-JSON: %r", text[:200])
        return []
    if isinstance(facts, dict):  # json_output asks for an object; accept {"facts": [...]} as well as a bare array
        facts = next((v for v in facts.values() if isinstance(v, list)), [])
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()] if isinstance(facts, list) else []

    # DEV: Backboard only. Direct Gemini extraction, kept for when the Gemini fallback is turned back on.
    # if not settings.gemini_api_key:
    #     return []
    # body = {
    #     "systemInstruction": {"parts": [{"text": DIGEST_PROMPT}]},
    #     "contents": [{"role": "user", "parts": [{"text": f"Person: {patient}\n\nWhat they said today:\n{said}\n\nAlready remembered:\n{remembered}"}]}],
    #     "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    # }
    # for model in dict.fromkeys([settings.memory_digest_model, settings.gemini_model]):
    #     try:
    #         async with httpx.AsyncClient(timeout=DIGEST_TIMEOUT_S, transport=_transport) as client:
    #             r = await client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    #                                   headers={"x-goog-api-key": settings.gemini_api_key}, json=body)
    #             r.raise_for_status()
    #             parts = r.json()["candidates"][0]["content"]["parts"]
    #             facts = json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))
    #             return [f.strip() for f in facts if isinstance(f, str) and f.strip()]
    #     except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
    #         log.warning("fact extraction with %s failed: %r", model, e)
    # return []


async def digest_session(assistant_id: str | None, patient: str, utterances: list[str]) -> list[str]:
    """After a session: save what the person told us that is not already remembered. Returns the facts saved."""
    if not assistant_id or not utterances:
        log.info("nothing to remember for %s: %s", patient, "no Backboard assistant" if not assistant_id else "they said nothing")
        return []
    known = [m["content"] for m in await list_all(assistant_id)]
    saved: list[str] = []
    for fact in await extract_facts(assistant_id, patient, utterances, known):
        if not is_known(fact, known + saved, patient) and await add(assistant_id, fact, kind="session"):
            saved.append(fact)
    log.info("saved %d new memories for assistant %s", len(saved), assistant_id)
    return saved


def profile_memories(profile: dict) -> list[str]:
    """Care-sheet lines worth seeding as memories, so search can surface them alongside what is learnt later."""
    return [*profile.get("lifeStory", []), *(f"Enjoys talking about {i}." for i in profile.get("interests", []))]


async def seed(assistant_id: str, profile: dict) -> None:
    for line in profile_memories(profile):
        await add(assistant_id, line, kind="care_profile")


async def ensure_assistant(store, participant: dict, with_seed: bool = True) -> str | None:
    """The participant's assistant id: the one stored on the participant, else the one Backboard already has under
    their name (re-linked, not re-seeded), else a new one seeded from the care profile. The id is saved on the
    participant. With with_seed=False a new assistant is seeded in the background, so a first session does not
    wait for it."""
    if participant.get("backboardAssistantId") or not enabled():
        return participant.get("backboardAssistantId")
    name = assistant_name(participant)
    aid = await find_assistant(name)
    created = aid is None
    if created:
        aid = await create_assistant(name)
    if not aid:
        return None
    participant["backboardAssistantId"] = aid
    await store.update("participants", participant["_id"], {"backboardAssistantId": aid})
    log.info("%s Backboard assistant %s for %s", "created" if created else "re-linked", aid, participant["_id"])
    if created:
        profile = participant.get("careProfile") or {}
        if with_seed:
            await seed(aid, profile)
        else:
            tasks.background(seed(aid, profile))
    return aid


async def provision(store) -> None:
    """Make sure every participant who agreed to be remembered has an assistant (at startup, in the background)."""
    if not enabled():
        log.warning("BACKBOARD_API_KEY not set: no long-term memory")
        return
    for p in await store.find("participants"):
        if p.get("consentFlags", {}).get("rememberPreferences"):
            await ensure_assistant(store, p)
