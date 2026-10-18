"""Playground: run Remember the Order by tapping, without a voice call, and watch the robot, the camera
and the game's cues in real time. For staff demos and testing. The same engine and robot path the
companion uses (voice/tools.py); nothing here moves a motor directly."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import settings
from .games.shuffles import ROBOT_START
from .voice.tools import LIVE, GameState, log_feed, run_tool, watch_table

router = APIRouter(prefix="/api/play", tags=["play"])
SESSIONS: dict[str, GameState] = {}  # in memory; a playground session is short


class StartIn(BaseModel):
    sessionId: str
    mover: str = "simulated"  # simulated | robot


class SayIn(BaseModel):
    sessionId: str
    text: str


class WatchIn(BaseModel):
    sessionId: str
    reading: dict | None = None


def _state(sid: str) -> GameState:
    if sid not in SESSIONS:
        raise HTTPException(404, "no playground session; start one first")
    return SESSIONS[sid]


@router.post("/start")
async def start(body: StartIn) -> dict:
    if body.mover not in ("simulated", "robot"):
        raise HTTPException(422, "mover must be simulated or robot")
    # Always the three keycaps: they are what the camera can read and what the robot was trained on.
    state = GameState(mover=body.mover, objects=list(ROBOT_START), session_id=body.sessionId, patient_name="Playground")
    SESSIONS[body.sessionId] = state
    res = await run_tool(state, "start_game", {"game_id": "order_memory"}, None)
    if res.get("say"):
        log_feed(state, "agent", res["say"])
    return {"result": res, "state": state.view(), "feed": state.feed}


@router.post("/say")
async def say(body: SayIn) -> dict:
    state = _state(body.sessionId)
    res = await run_tool(state, "exercise_step", {"said": body.text}, None)
    return {"result": res, "state": state.view()}


@router.post("/watch")
async def watch(body: WatchIn) -> dict:
    state = _state(body.sessionId)
    out = await watch_table(state, body.reading)
    return {**out, "state": state.view()}


@router.get("/live")
async def live() -> dict:
    """The running patient session (most recent), so the playground can follow the real game read-only."""
    if not LIVE:
        return {"active": False}
    state = list(LIVE.values())[-1]
    return {"active": True, "name": state.patient_name, "game": state.game, "state": state.view(), "feed": state.feed[-80:]}


@router.post("/stop")
async def stop(body: dict) -> dict:
    state = SESSIONS.pop(str(body.get("sessionId", "")), None)
    if state is not None:
        await run_tool(state, "stop", {}, None)
    return {"ok": True}


@router.get("/robot")
async def robot() -> dict:
    """Robot mode, readiness and follower motor temperatures, for the playground's status panel."""
    out: dict = {"reachable": False}
    try:
        async with httpx.AsyncClient(base_url=settings.robot_worker_url, timeout=30) as c:
            out.update((await c.get("/health")).json(), reachable=True)
            follower = (await c.get("/studio/health")).json().get("follower") or {}
        out["motors"] = {k: {"ok": v.get("ok"), "tempC": v.get("tempC")} for k, v in follower.items() if isinstance(v, dict)}
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


@router.get("/camera.jpg")
async def camera() -> "Response":
    """The robot's side camera with keyrings, slots and hands drawn on (relayed from the robot worker, so
    only the backend needs to be reachable)."""
    from fastapi import Response

    try:
        async with httpx.AsyncClient(base_url=settings.robot_worker_url, timeout=6) as c:
            r = await c.get("/studio/vision/row.jpg")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"robot camera unreachable: {e}") from e
    if r.status_code != 200:
        raise HTTPException(503, r.text[:200])
    return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
