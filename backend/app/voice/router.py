from fastapi import APIRouter
from pydantic import BaseModel

from . import agent
from .tools import GAMES, GameState

router = APIRouter(prefix="/api/voice", tags=["voice"])

SESSIONS: dict[str, tuple[GameState, list[dict]]] = {}  # prototype: in-memory only


class TurnIn(BaseModel):
    sessionId: str
    text: str
    tableOrder: list[str] | None = None  # prototype: what the demo table / camera currently shows


@router.post("/turn")
async def voice_turn(body: TurnIn) -> dict:
    state, history = SESSIONS.setdefault(body.sessionId, (GameState(), []))
    reply, calls = await agent.turn(state, history, body.text, body.tableOrder)
    del history[:-24]
    return {"reply": reply, "toolCalls": calls, "state": state.view()}


@router.post("/reset")
async def reset(body: dict) -> dict:
    SESSIONS.pop(str(body.get("sessionId", "")), None)
    return {"ok": True}


@router.get("/games")
async def games() -> list[dict]:
    return [{"id": k, **v} for k, v in GAMES.items()]
