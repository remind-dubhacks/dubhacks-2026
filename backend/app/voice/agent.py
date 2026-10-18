"""Tool-calling loop. With an LLM key the model picks tools; without one a small rule-based parser
picks the same tools, so the prototype works offline. 'stop' is always handled before the model."""
import asyncio
import json
import logging
import re

import httpx

from ..config import settings
from .tools import TOOL_SCHEMAS, GameState, run_tool

# Gemini wants {name, description, parameters?} and rejects an empty properties object.
GEMINI_DECLS = [
    {k: v for k, v in t["function"].items() if not (k == "parameters" and not v.get("properties"))} for t in TOOL_SCHEMAS
]

log = logging.getLogger("remind.voice")

SYSTEM = """You are ReMind, a warm, patient companion for a person living with dementia, in a care home. A caregiver is supervising.
You talk by voice, so reply in one or two SHORT, simple sentences. Never shame, quiz or correct personal memories. No medical advice.
You run games by calling tools. Never claim the robot did something unless a tool result says so.
- When the person asks to play a game, call start_game, then tell them the RIGHT order to put the objects in (target_order from the tool result; never call it the starting order) and to say "done" when finished.
- When they say they are done, call check_arrangement. If wrong, say kindly it is not quite right and explain using the tool's reason, then invite another try. If attempts_left is 0, gently reveal the correct order. If correct, praise them.
- If they ask for help or seem upset, call alert_caregiver and reassure them.
- If they ask what games exist, call list_games.
Current game state: {state}"""

STOP_RE = re.compile(r"\b(stop|quit|end the game|no more)\b", re.I)


def rule_plan(text: str, state: GameState) -> list[tuple[str, dict]]:
    t = text.lower()
    if re.search(r"\bhelp|confused|don't know|dont know\b", t):
        return [("alert_caregiver", {"reason": f"Resident said: {text[:120]}"})]
    if re.search(r"what games|which games|list|options", t):
        return [("list_games", {})]
    if state.phase == "awaiting" and re.search(r"\b(done|finished|ready|check|that's it|thats it)\b", t):
        return [("check_arrangement", {})]
    if re.search(r"\b(play|start|game|order|sort|shuffle|again|yes|sure)\b", t):
        return [("start_game", {"game_id": "reorder"})]
    return []


def rule_reply(text: str, calls: list[tuple[str, dict, dict]], state: GameState) -> str:
    if not calls:
        return "I can play a game with you. Just say play the ordering game, or say help."
    name, _, res = calls[-1]
    if name == "start_game":
        if not res.get("ok"):
            return res.get("error", "I couldn't start that.")
        order = ", then the ".join(res["target_order"])
        return f"Let's play. I've mixed them up. Put them in this order: the {order}. Say done when you're finished."
    if name == "check_arrangement":
        if not res.get("ok", True):
            return res["error"]
        if res.get("correct"):
            return "That's right. Well done! Would you like to play again?"
        if res.get("attempts_left") == 0:
            order = ", then the ".join(res["correct_order"])
            return f"Good try. The right order is the {order}. Would you like to try again?"
        return f"Not quite. {res['reason']} Would you like to try again?"
    if name == "alert_caregiver":
        return "That's okay. I've let a caregiver know. They'll be with you soon."
    if name == "list_games":
        return "I can play the ordering game. More games are coming soon."
    return "Okay."


def provider() -> str:
    if settings.gemini_api_key:
        return "gemini"
    return "rules"


async def _gemini(contents: list[dict], system: str) -> dict:
    """Try the main model, then the fallback, when Google is busy (503) or the free tier is throttled (429)."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "tools": [{"functionDeclarations": GEMINI_DECLS}],
        "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
    }
    last: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for model in dict.fromkeys([settings.gemini_model, settings.gemini_fallback_model]):
            for attempt in range(2):
                last = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json=body,
                )
                if last.status_code not in (429, 503):
                    last.raise_for_status()
                    return last.json()["candidates"][0]["content"]
                await asyncio.sleep(0.7)
    assert last is not None
    last.raise_for_status()
    raise RuntimeError("Gemini unavailable")


async def _gemini_turn(state: GameState, history: list[dict], text: str, table_order: list[str] | None) -> tuple[str, list[dict]] | None:
    """Gemini picks the tools. Returns None on any API failure (history is rolled back) so rules can answer."""
    start = len(history)
    made: list[dict] = []
    history.append({"role": "user", "parts": [{"text": text}]})
    system = SYSTEM.format(state=json.dumps(state.view()))
    try:
        for _ in range(4):
            content = await _gemini(history, system)
            history.append(content)
            parts = content.get("parts", [])
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                reply = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                return reply or "I'm here.", made
            responses = []
            for c in calls:
                res = await run_tool(state, c["name"], c.get("args") or {}, table_order)
                made.append({"name": c["name"], "args": c.get("args") or {}, "result": res})
                responses.append({"functionResponse": {"name": c["name"], "response": {"result": res}}})
            history.append({"role": "user", "parts": responses})
        return "Let me try that again in a moment.", made
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini turn failed, using rules: %s", e)
        del history[start:]
        return None


async def turn(state: GameState, history: list[dict], text: str, table_order: list[str] | None) -> tuple[str, list[dict]]:
    """Returns (reply, tool_calls_made). Gemini picks the tools; the keyword rules answer if there is no key or the call fails."""
    made: list[dict] = []

    if STOP_RE.search(text):  # safety first: never depends on the model
        res = await run_tool(state, "stop", {}, table_order)
        made.append({"name": "stop", "args": {}, "result": res})
        return "Okay, we've stopped. Thank you for spending time with me.", made

    if provider() == "gemini":
        out = await _gemini_turn(state, history, text, table_order)
        if out is not None:
            return out

    # Rule-based fallback (no key, or the LLM failed before answering)
    done = []
    for name, args in rule_plan(text, state):
        res = await run_tool(state, name, args, table_order)
        made.append({"name": name, "args": args, "result": res})
        done.append((name, args, res))
    reply = rule_reply(text, done, state)
    if provider() == "gemini":  # keep the model's view of the conversation complete
        history += [{"role": "user", "parts": [{"text": text}]}, {"role": "model", "parts": [{"text": reply}]}]
    return reply, made
