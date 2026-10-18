"""Rule-based agent for the original tap/typed Sort & Share flow (the voice agent lives in app/voice/).
The result is only a *proposal*: the orchestrator validates intent and objectId before anything reaches the robot."""

import re

from .catalog import OBJECTS
from .models import AgentTurn

STOP_WORDS = ("stop", "quit", "end", "no more", "i'm done", "im done", "finish")
HELP_WORDS = ("help", "don't know", "dont know", "not sure", "confused", "caregiver")
REPEAT_WORDS = ("repeat", "again", "say that", "pardon", "what did you say")
SKIP_WORDS = ("skip", "pass", "rather not", "next")
YES_WORDS = ("yes", "sure", "okay", "ok", "alright", "let's", "lets", "please")

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


async def agent_turn(text: str, activity: dict, participant: dict | None) -> AgentTurn:
    return rule_turn(text, activity)


def welcome(activity: dict, participant: dict | None) -> str:
    alias = (participant or {}).get("alias")
    return (f"Hello, {alias}. " if alias else "Hello. ") + activity["prompts"]["welcome"]
