"""Conversational agent. A rule-based parser handles every turn (the typed/tap fallback); Grok is
used for friendlier replies when XAI_API_KEY is set. Either way the result is only a *proposal*:
the orchestrator validates intent and objectId before anything reaches the robot."""

import json
import logging
import re

import httpx

from .catalog import OBJECTS
from .config import settings
from .models import AgentTurn

log = logging.getLogger(__name__)

STOP_WORDS = ("stop", "quit", "end", "no more", "i'm done", "im done", "finish")
HELP_WORDS = ("help", "don't know", "dont know", "not sure", "confused", "caregiver")
REPEAT_WORDS = ("repeat", "again", "say that", "pardon", "what did you say")
SKIP_WORDS = ("skip", "pass", "rather not", "next")
YES_WORDS = ("yes", "sure", "okay", "ok", "alright", "let's", "lets", "please")

SYSTEM_PROMPT = """You are ReMind, a warm, patient activity companion for a person living with dementia.
A caregiver is supervising. Rules:
- Ask one short question at a time. Use simple, kind language.
- Never shame, quiz, or correct personal memories. Never invent biographical facts.
- Never give medical advice, impersonate a clinician, or make health promises.
- Offer to pause or get a caregiver if the person seems upset or asks for help.
- Never say the robot has moved something; the system reports that separately.
Allowed objects (objectId: label): {objects}
Respond ONLY with JSON: {{"reply": str, "intent": one of ["begin","select_object","help","repeat","skip","stop","chat","unclear"],
"objectId": allowed objectId or null, "requestedAction": "move_known_object" or null, "needsConfirmation": bool}}"""


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def match_object(text: str, object_ids: list[str]) -> str | None:
    t = text.lower().strip()
    if t in object_ids:  # tap on a choice card sends the objectId directly
        return t
    hits = [oid for oid in object_ids if any(_has(t, (s,)) for s in OBJECTS[oid]["synonyms"])]
    return hits[0] if len(hits) == 1 else None


def rule_turn(text: str, activity: dict) -> AgentTurn:
    t = text.lower().strip()
    p = activity["prompts"]
    if _has(t, STOP_WORDS):
        return AgentTurn(reply=p["stopped"], intent="stop")
    if _has(t, HELP_WORDS):
        return AgentTurn(reply=p["help"], intent="help")
    if _has(t, REPEAT_WORDS):
        return AgentTurn(reply=p["choice"], intent="repeat")
    if _has(t, SKIP_WORDS):
        return AgentTurn(reply=p["skip"], intent="skip")
    oid = match_object(t, activity["objectIds"])
    if oid:
        label = OBJECTS[oid]["label"].lower()
        return AgentTurn(
            reply=f"Lovely, let's move the {label}.",
            intent="select_object",
            objectId=oid,
            requestedAction="move_known_object",
        )
    if _has(t, YES_WORDS):
        return AgentTurn(reply=p["choice"], intent="begin")
    return AgentTurn(reply=p["unclear"], intent="unclear")


async def llm_turn(text: str, activity: dict, participant: dict | None) -> AgentTurn | None:
    if not (settings.xai_api_key and settings.xai_model):
        return None
    objects = ", ".join(f"{o}: {OBJECTS[o]['label']}" for o in activity["objectIds"])
    interests = ", ".join((participant or {}).get("interestTags", [])) or "unknown"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"{settings.xai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.xai_api_key}"},
                json={
                    "model": settings.xai_model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT.format(objects=objects)},
                        {"role": "system", "content": f"Participant interests: {interests}"},
                        {"role": "user", "content": text},
                    ],
                },
            )
            r.raise_for_status()
            return AgentTurn.model_validate(json.loads(r.json()["choices"][0]["message"]["content"]))
    except Exception as e:  # noqa: BLE001
        log.warning("Grok turn failed, using rule-based agent: %s", e)
        return None


async def agent_turn(text: str, activity: dict, participant: dict | None) -> AgentTurn:
    rules = rule_turn(text, activity)
    # Safety-relevant intents from the deterministic parser always win over the LLM.
    if rules.intent in ("stop", "help", "select_object"):
        return rules
    llm = await llm_turn(text, activity, participant)
    if llm is None:
        return rules
    if llm.intent == "select_object":
        # Only trust an LLM selection if the user's own words name an allowed object.
        return rules if rules.intent == "select_object" else AgentTurn(reply=activity["prompts"]["unclear"], intent="unclear")
    return llm


def welcome(activity: dict, participant: dict | None) -> str:
    alias = (participant or {}).get("alias")
    return (f"Hello, {alias}. " if alias else "Hello. ") + activity["prompts"]["welcome"]
