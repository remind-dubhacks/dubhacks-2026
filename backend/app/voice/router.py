import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..config import settings
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
    # never start on a tool result or model turn: providers reject a history that doesn't open with the user
    while history and not (history[0].get("role") == "user" and (isinstance(history[0].get("content"), str) or any("text" in p for p in history[0].get("parts", [])))):
        history.pop(0)
    return {"reply": reply, "toolCalls": calls, "state": state.view()}


@router.post("/reset")
async def reset(body: dict) -> dict:
    SESSIONS.pop(str(body.get("sessionId", "")), None)
    return {"ok": True}


@router.get("/games")
async def games() -> list[dict]:
    return [{"id": k, **v} for k, v in GAMES.items()]


@router.get("/status")
async def status() -> dict:
    """Which brain and voice are active, so the UI can show it."""
    provider = agent.provider()
    return {"provider": provider, "tts": bool(settings.elevenlabs_api_key)}


class TtsIn(BaseModel):
    text: str


@router.post("/tts")
async def tts(body: TtsIn) -> Response:
    """ElevenLabs text-to-speech. 503 if no key, so the browser falls back to its own voice."""
    if not settings.elevenlabs_api_key:
        raise HTTPException(503, "ELEVENLABS_API_KEY not set")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                headers={"xi-api-key": settings.elevenlabs_api_key},
                params={"output_format": "mp3_44100_64"},
                json={"text": body.text[:600], "model_id": settings.elevenlabs_model},
            )
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"ElevenLabs failed: {e}") from e
    return Response(r.content, media_type="audio/mpeg")
