"""Tools the voice agent may call. Everything the model can *do* is listed here; it never sends motor
commands. Game ids are checked against GAMES, and the robot step goes through one function (`shuffle`)."""
import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .. import robot_client
from ..config import settings

from ..games.reorder import MAX_TRIALS, evaluate, shuffled
from ..vision.checker import read_order

GAMES = {
    "reorder": {"name": "Reorder", "description": "The robot mixes up three objects and you put them back in order.", "enabled": True},
    "memory_match": {"name": "Memory match", "description": "Coming soon", "enabled": False},
    "sort_by_colour": {"name": "Sort by colour", "description": "Coming soon", "enabled": False},
}

TARGET = ["cup", "apple", "book"]  # placeholder prop set


log = logging.getLogger("remind.tools")
SHUFFLE_TIMEOUT_S = 120


@dataclass
class GameState:
    game: str | None = None
    phase: str = "idle"  # idle | awaiting | complete | reveal | stopped
    attempt: int = 0
    target: list[str] = field(default_factory=list)
    shuffled_order: list[str] = field(default_factory=list)
    shuffle_id: int = 0  # bumps on each shuffle so the UI knows to reset its table
    feedback: str = ""
    result: str = "none"  # none | correct | gave_up | stopped
    help_requested: bool = False
    alerts: list[str] = field(default_factory=list)
    job_id: str | None = None
    watcher: asyncio.Task | None = None
    # Set by the voice channel so the agent can speak up when the robot finishes (no user turn needed).
    notify: Callable[[str], Awaitable[None]] | None = None
    pending_note: str | None = None  # for channels with no push (chat): the UI picks this up and sends it as a system turn
    seq: int = 0  # bumps on every state change so clients know to refresh

    def view(self) -> dict:
        return {
            "game": self.game, "phase": self.phase, "attempt": self.attempt, "maxTrials": MAX_TRIALS,
            "target": self.target, "shuffledOrder": self.shuffled_order, "shuffleId": self.shuffle_id,
            "feedback": self.feedback, "result": self.result, "helpRequested": self.help_requested, "alerts": self.alerts,
            "jobId": self.job_id, "seq": self.seq, "pendingNote": self.pending_note,
        }


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "list_games", "description": "List the games that can be played.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "start_game", "description": "Start a game. The robot shuffles the objects. Only call when the person asks to play.",
        "parameters": {"type": "object", "properties": {"game_id": {"type": "string", "enum": list(GAMES)}}, "required": ["game_id"]}}},
    {"type": "function", "function": {"name": "check_arrangement", "description": "Look at the table with the camera and judge the order. Call when the person says they are done.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "alert_caregiver", "description": "Message a caregiver. Use if the person asks for help, seems upset or confused.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {"name": "stop", "description": "Stop the game and the robot.", "parameters": {"type": "object", "properties": {}}}},
]


# What the UI shows in the Tools menu. status: real | mock | placeholder
TOOL_INFO = {
    "list_games": {"status": "real", "example": "What games can we play?", "does": "Lists the game catalog."},
    "start_game": {"status": "mock", "example": "Let's play the ordering game.", "does": "Starts Reorder and sends a shuffle job to the robot worker (mock arm for now). Returns at once; the agent speaks again when the robot finishes."},
    "check_arrangement": {"status": "mock", "example": "I'm done.", "does": "Judges the order, counts tries (max 3), explains mistakes. No camera yet, so it always reads the table as correct."},
    "alert_caregiver": {"status": "placeholder", "example": "I need help.", "does": "Flags that help is needed. Recorded only; no message is sent yet."},
    "stop": {"status": "real", "example": "Stop.", "does": "Ends the game. Also triggered directly by the word 'stop', without the AI."},
}


def tool_catalog() -> list[dict]:
    out = []
    for t in TOOL_SCHEMAS:
        f = t["function"]
        out.append({"name": f["name"], "description": f["description"], "params": list(f.get("parameters", {}).get("properties", {})), **TOOL_INFO[f["name"]]})
    return out


async def shuffle(state: GameState) -> None:
    """Pick the intended order. With a real arm the camera should confirm it afterwards (not built yet)."""
    state.shuffled_order = shuffled(state.target)
    state.shuffle_id += 1


async def _watch_job(state: GameState, job_id: str) -> None:
    """Poll the robot worker until the shuffle ends, then move the game on and tell the agent."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SHUFFLE_TIMEOUT_S
    outcome, note = "failed", ""
    try:
        while loop.time() < deadline:
            await asyncio.sleep(0.7)
            job = await robot_client.status(job_id)
            if job["status"] in ("succeeded", "verifying"):
                outcome = "ok"
                break
            if job["status"] in ("failed", "stopped"):
                outcome = job["status"]
                break
    except asyncio.CancelledError:
        return
    except Exception as e:  # noqa: BLE001
        log.warning("lost the robot worker while shuffling: %s", e)

    if state.phase != "shuffling":  # stopped or restarted meanwhile
        return
    if outcome == "ok":
        state.phase = "awaiting"
        note = (f"(System: the robot has finished mixing the objects. Now tell the person the right order, "
                f"{', then '.join(state.target)}, and ask them to say 'done' when they have finished.)")
    elif outcome == "stopped":
        state.phase, state.result = "stopped", "stopped"
        note = "(System: the robot was stopped. Tell the person kindly that we have paused.)"
    else:
        state.phase = "needs_staff"
        state.help_requested = True
        state.alerts.append("The robot could not finish the shuffle")
        note = "(System: the robot had a problem and stopped. Tell the person kindly to wait a moment; a caregiver is coming. Do not start the game.)"
    state.seq += 1
    if state.notify:
        try:
            await state.notify(note)
        except Exception as e:  # noqa: BLE001
            log.warning("could not notify the agent: %s", e)
    else:
        state.pending_note = note


async def start_shuffle(state: GameState) -> dict:
    """Software shuffle, or a real worker job. Returns a tool result for the model."""
    await shuffle(state)
    if not settings.use_robot_worker:
        state.phase = "awaiting"
        return {"ok": True, "target_order": state.target,
                "note": "The objects are mixed up. Tell the person the right order and ask them to say 'done' when finished."}
    try:
        health = await robot_client.health()
        if not health.get("ready") or health.get("busy"):
            state.phase = "idle"
            return {"ok": False, "error": "The robot is not ready right now. Tell the person kindly and offer to try again in a moment."}
        job_id = uuid.uuid4().hex
        await robot_client.submit(job_id, "shuffle", "reorder_set")
    except robot_client.RobotWorkerError as e:
        log.warning("robot worker unavailable: %s", e)
        state.phase = "idle"
        return {"ok": False, "error": "The robot is not available right now. Tell the person kindly; a caregiver can help."}
    state.phase, state.job_id = "shuffling", job_id
    state.watcher = asyncio.create_task(_watch_job(state, job_id))
    return {"ok": True, "status": "shuffling",
            "note": "The robot is now mixing up the objects. Tell the person to watch. Do NOT say the order yet; you will be told when the robot has finished."}


async def run_tool(state: GameState, name: str, args: dict, table_order: list[str] | None) -> dict:
    if name == "list_games":
        return {"games": [{"id": k, **v} for k, v in GAMES.items()]}

    if name == "start_game":
        gid = args.get("game_id")
        game = GAMES.get(gid)
        if not game:
            return {"ok": False, "error": "unknown game"}
        if not game["enabled"]:
            return {"ok": False, "error": f"{game['name']} is coming soon; only Reorder is available"}
        if state.phase in ("awaiting", "shuffling"):
            return {"ok": False, "error": "a game is already running"}
        state.game, state.attempt, state.result = gid, 0, "none"
        state.target, state.feedback = list(TARGET), ""
        res = await start_shuffle(state)
        state.seq += 1
        return res

    if name == "check_arrangement":
        if state.phase == "shuffling":
            return {"ok": False, "error": "The robot is still moving the objects. Ask the person to wait until it has finished."}
        if state.phase != "awaiting":
            return {"ok": False, "error": "no game is waiting for an answer"}
        state.attempt += 1
        reading = await read_order(state.target, mock_order=table_order)  # mock vision reads the demo table
        if reading.confidence < 0.6:
            state.attempt -= 1
            return {"ok": False, "error": "camera could not see clearly; ask the person to adjust the objects"}
        r = evaluate(state.target, reading.order)
        if r["correct"]:
            state.phase, state.result, state.feedback = "complete", "correct", "Correct"
            return {"correct": True, "attempts_used": state.attempt}
        left = MAX_TRIALS - state.attempt
        if left <= 0:
            state.phase, state.result, state.feedback = "reveal", "gave_up", r["reason"]
            return {"correct": False, "reason": r["reason"], "attempts_left": 0, "correct_order": state.target,
                    "note": "No tries left. Kindly reveal the correct order and offer another round."}
        state.feedback = r["reason"]
        return {"correct": False, "reason": r["reason"], "attempts_left": left}

    if name == "alert_caregiver":
        state.help_requested = True
        state.alerts.append(str(args.get("reason", "help requested"))[:200])
        return {"ok": True, "note": "A caregiver has been notified."}

    if name == "stop":
        was_shuffling = state.phase == "shuffling"
        state.phase, state.result = "stopped", "stopped"
        state.seq += 1
        if state.watcher:
            state.watcher.cancel()
        if was_shuffling or state.job_id:
            try:
                await robot_client.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("could not reach the robot to stop it: %s", e)
        return {"ok": True}

    return {"ok": False, "error": "unknown tool"}
