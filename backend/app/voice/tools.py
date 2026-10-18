"""Tools the voice agent may call. Everything the model can *do* is listed here; it never sends motor
commands. Game ids are checked against GAMES, and the robot step goes through one function (`shuffle`)."""
import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..config import settings
from ..games.find_remember import FindRemember
from .. import robot_client
from ..games.order_memory import OrderMemory, order_from_detections
from ..games.shuffles import CAMERA_NAMES, ROBOT_START, fix_for
from ..games.table_watch import TableWatch
from ..games.reorder import MAX_TRIALS, evaluate, shuffled
from ..vision.checker import read_order

GAMES = {
    "reorder": {"name": "Reorder", "description": "The robot mixes up three objects and you put them back in order.", "enabled": True},
    "order_memory": {"name": "Remember the Order", "description": "Look at a row of objects, watch them get mixed up, then put them back the way they were.", "enabled": True},
    "find_remember": {"name": "Find & Remember", "description": "Follow one object as it moves, find it, then share a memory about it.", "enabled": True},
    "memory_match": {"name": "Memory match", "description": "Coming soon", "enabled": False},
    "sort_by_colour": {"name": "Sort by colour", "description": "Coming soon", "enabled": False},
}

TARGET = ["cup", "apple", "book"]  # placeholder prop set

# Find & Remember props (must be names known to games/find_remember.OBJECTS) and who moves them:
# simulated (prototype: instant), caregiver (agent asks a caregiver to move them), robot (needs a trained skill).
FR_OBJECTS = [o.strip() for o in os.getenv("FIND_REMEMBER_OBJECTS", "blue keychain,lipstick,white keycap").split(",") if o.strip()]
FR_MOVER = os.getenv("FIND_REMEMBER_MOVER", "simulated")
DISTRESS_RE = re.compile(r"\b(upset|scared|frightened|tired|sad|don'?t like this|want to stop|leave me)\b", re.I)


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
    fr: Any = None  # FindRemember engine while that game runs
    fr_step: dict = field(default_factory=dict)  # last step the engine produced
    watch: Any = None  # TableWatch while the person restores the row
    robot: dict = field(default_factory=dict)  # {status: moving|done|failed, purpose, error}
    pending_say: list[str] = field(default_factory=list)  # said by the app when a robot move finishes

    def view(self) -> dict:
        v = {
            "game": self.game, "phase": self.phase, "attempt": self.attempt, "maxTrials": MAX_TRIALS,
            "target": self.target, "shuffledOrder": self.shuffled_order, "shuffleId": self.shuffle_id,
            "feedback": self.feedback, "result": self.result, "helpRequested": self.help_requested, "alerts": self.alerts,
        }
        if isinstance(self.fr, OrderMemory):
            v["exercise"] = {
                "step": self.fr_step, "row": self.fr.current, "answer": self.fr.original,  # answer: caregiver view only
                "level": self.fr.level, "round": self.fr.round, "mover": FR_MOVER, "summary": self.fr.summary(),
                "robot": self.robot, "watching": self.watch is not None and not self.watch.done,
            }
        elif self.fr is not None:
            v["exercise"] = {
                "step": self.fr_step, "layout": self.fr.layout, "tray": self.fr.tray, "target": self.fr.target,
                "level": self.fr.level, "round": self.fr.round, "mover": FR_MOVER, "summary": self.fr.summary(),
            }
        return v


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "list_games", "description": "List the games that can be played.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "start_game", "description": "Start a game. The robot shuffles the objects. Only call when the person asks to play.",
        "parameters": {"type": "object", "properties": {"game_id": {"type": "string", "enum": list(GAMES)}}, "required": ["game_id"]}}},
    {"type": "function", "function": {"name": "check_arrangement", "description": "Look at the table with the camera and judge the order. Call when the person says they are done.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "exercise_step", "description": "Find & Remember / Remember the Order: pass the person's exact words; returns the next thing to say.",
        "parameters": {"type": "object", "properties": {"said": {"type": "string"}}, "required": ["said"]}}},
    {"type": "function", "function": {"name": "alert_caregiver", "description": "Message a caregiver. Use if the person asks for help, seems upset or confused.", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {"name": "stop", "description": "Stop the game and the robot.", "parameters": {"type": "object", "properties": {}}}},
]


# What the UI shows in the Tools menu. status: real | mock | placeholder
TOOL_INFO = {
    "list_games": {"status": "real", "example": "What games can we play?", "does": "Lists the game catalog."},
    "start_game": {"status": "mock", "example": "Let's play the ordering game.", "does": "Starts Reorder. The robot shuffle is simulated in software for now."},
    "check_arrangement": {"status": "mock", "example": "I'm done.", "does": "Judges the order, counts tries (max 3), explains mistakes. No camera yet, so it always reads the table as correct."},
    "exercise_step": {"status": "real", "example": "The keycap, then the lipstick.", "does": "Runs the next turn of Find & Remember or Remember the Order."},
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
    """Prototype: shuffles in software. Replace with a robot worker job (`POST /jobs` with actionId=shuffle)."""
    state.shuffled_order = shuffled(state.target)
    state.shuffle_id += 1


def _moves_note(step) -> str:
    """How the moves in a step get done, as words for the person/caregiver."""
    real = [m for m in step.moves if m.get("from")]
    if not real or FR_MOVER == "simulated":
        return ""
    pairs = {(m["object"], m["from"], m["to"]) for m in real[::2]}
    what = "; ".join(f"move the {o} from the {a} to the {b}" for o, a, b in pairs)
    who = "Caregiver" if FR_MOVER == "caregiver" else "Robot (caregiver, if the robot skill isn't trained yet)"
    return f" ({who}: please {what}, slowly. Say 'moved' when done.)"


def _fr_advance(state: GameState, said: str) -> dict:
    fr: FindRemember = state.fr
    phase = fr.phase
    if phase == "choose":
        step = fr.choose(said)
        if FR_MOVER == "simulated":  # prototype: the move happens on screen right away
            nxt = fr.after_move()
            step.say, step.expect, step.phase = f"{step.say} {nxt.say}", nxt.expect, nxt.phase
        else:
            step.say += _moves_note(step)
    elif phase == "watch":
        step = fr.after_move()
    elif phase == "find":
        step = fr.answer(said)
    elif phase == "act":
        step = fr.did_task(confirmed=not re.search(r"\b(no|can'?t|cannot|later|not now)\b", said.lower()))
    elif phase == "reminisce":
        step = fr.shared(said)
    elif phase == "recall":
        step = fr.recall(said)
    else:
        step = fr.finish()
    state.fr_step = step.to_dict()
    if step.phase == "done":
        state.phase, state.result = "complete", "correct"
    return {"ok": True, "say": step.say, "expect": step.expect, "phase": step.phase, "moves": step.moves}


async def camera_order(objects: list[str]) -> list[str] | None:
    """Left-to-right order of the objects from the robot worker's live detection, if it's running."""
    side = os.getenv("SIDE_CAMERA_INDEX", "0")
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{settings.robot_worker_url}/studio/vision/detections", params={"camera": side})
        return order_from_detections(r.json()["detections"], objects) if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- robot moves + live table watching

ROBOT_TIMEOUT_S = float(os.getenv("ROBOT_SHUFFLE_TIMEOUT_S", "90"))
YES_RE = re.compile(r"\b(yes|yeah|yep|please|ok(ay)?|sure|show)\b", re.I)


async def robot_shuffle(sid: str) -> dict:
    """Run one trained shuffle on the robot worker and wait for it. The worker guards every motion
    and checks the row with its camera afterwards."""
    job_id = f"om-{uuid.uuid4().hex[:10]}"
    await robot_client.submit(job_id, "shuffle", sid)
    end = time.monotonic() + ROBOT_TIMEOUT_S
    while time.monotonic() < end:
        await asyncio.sleep(0.5)
        job = await robot_client.status(job_id)
        if job["status"] not in ("queued", "running"):
            return job
    await robot_client.stop()
    return {"status": "failed", "errorCode": "timeout"}


def _start_watch(state: GameState) -> None:
    om: OrderMemory = state.fr
    state.watch = TableWatch(original=list(om.original), row=list(om.current), t0=time.monotonic())


def _robot_task(state: GameState, sid: str, purpose: str) -> None:
    """Run a robot move in the background; the person hears the result through pending_say."""
    state.robot = {"status": "moving", "purpose": purpose, "shuffle": sid}

    async def go() -> None:
        om: OrderMemory = state.fr
        try:
            job = await robot_shuffle(sid)
        except robot_client.RobotWorkerError as e:
            job = {"status": "failed", "errorCode": "worker_unreachable", "error": str(e)}
        ok = job["status"] in ("succeeded", "verifying")
        state.robot = {"status": "done" if ok else "failed", "purpose": purpose, "shuffle": sid,
                       "check": job.get("check"), "error": job.get("errorCode")}
        if not ok:
            state.alerts.append(f"Robot {purpose} failed ({job.get('errorCode')}). Please help with the objects.")
            state.pending_say.append("The robot needs a little help. A caregiver will come and sort the objects with us.")
            return
        if purpose == "shuffle":
            step = om.after_shuffle()
            _start_watch(state)
        else:  # show: the robot put the row back
            step = om.robot_showed()
            state.watch = None
        state.fr_step = step.to_dict()
        state.pending_say.append(step.say)

    asyncio.get_running_loop().create_task(go())


async def camera_row() -> dict | None:
    """Live keyring row + hands from the robot worker, in game object names."""
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{settings.robot_worker_url}/studio/vision/row")
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception:  # noqa: BLE001
        return None
    name = lambda n: CAMERA_NAMES.get(n) if n else None  # noqa: E731
    return {"order": [name(n) for n in d["order"]], "seen": [name(n) for n in d["seen"]], "hands": d["hands"]}


async def watch_table(state: GameState, reading: dict | None = None, now: float | None = None) -> dict:
    """One tick of live watching. Returns {'say': text or None, 'events': [...]} for the app to speak."""
    if state.pending_say:
        say = " ".join(state.pending_say)
        state.pending_say.clear()
        return {"say": say, "events": [], "robot": state.robot}
    om = state.fr
    if not isinstance(om, OrderMemory) or om.phase != "restore" or state.watch is None or state.robot.get("status") == "moving":
        return {"say": None, "events": [], "robot": state.robot}
    reading = reading or await camera_row()
    if reading is None:
        return {"say": None, "events": [], "camera": False}
    events = [e.to_dict() for e in state.watch.feed(reading, time.monotonic() if now is None else now)]
    step = om.live(events) if events else None
    if step is None:
        return {"say": None, "events": events}
    state.fr_step = step.to_dict()
    if om.phase != "restore":
        state.watch = None
        if step.phase == "done":
            state.phase, state.result = "complete", "correct"
    return {"say": step.say, "events": events}


async def _om_advance(state: GameState, said: str, table_order: list[str] | None) -> dict:
    om: OrderMemory = state.fr
    phase = om.phase
    if phase == "study":
        step = om.say_back(said)
        if FR_MOVER == "robot" and om.last_shuffle_id:
            _robot_task(state, om.last_shuffle_id, "shuffle")  # after_shuffle comes when the robot is done
        elif FR_MOVER == "simulated":
            nxt = om.after_shuffle()
            step.say, step.expect, step.phase = f"{step.say} {nxt.say}", nxt.expect, nxt.phase
            _start_watch(state)
        else:
            step.say += _moves_note(step)
    elif phase == "shuffle":
        if state.robot.get("status") == "moving":
            return {"ok": True, "say": "The robot is still mixing them up. Hands on your lap for a moment.", "expect": "moved", "phase": "shuffle", "moves": []}
        step = om.after_shuffle()
        _start_watch(state)
    elif phase == "restore" and om.offered_show and FR_MOVER == "robot" and YES_RE.search(said):
        row = await camera_row()
        current = row["order"] if row and all(row["order"]) else om.current
        sid = fix_for(current, om.original)
        if sid is None:
            step = om.check(said, current if all(current) else None)
        else:
            _robot_task(state, sid, "show")
            return {"ok": True, "say": "Let's watch together. Hands on your lap, please.", "expect": "moved", "phase": "restore", "moves": []}
    elif phase == "restore":
        observed = table_order or await camera_order(om.original)
        step = om.check(said, observed)
    elif phase == "reminisce":
        step = om.shared(said)
    elif phase == "recall":
        step = om.recall(said)
    else:
        step = om.finish()
    state.fr_step = step.to_dict()
    if step.phase == "done":
        state.phase, state.result = "complete", "correct"
    return {"ok": True, "say": step.say, "expect": step.expect, "phase": step.phase, "moves": step.moves}


async def run_tool(state: GameState, name: str, args: dict, table_order: list[str] | None) -> dict:
    if name == "exercise_step":
        if state.game not in ("find_remember", "order_memory") or state.fr is None or state.phase != "exercise":
            return {"ok": False, "error": "no memory activity is running"}
        if state.game == "order_memory":
            return await _om_advance(state, str(args.get("said", "")), table_order)
        return _fr_advance(state, str(args.get("said", "")))

    if name == "list_games":
        return {"games": [{"id": k, **v} for k, v in GAMES.items()]}

    if name == "start_game":
        gid = args.get("game_id")
        game = GAMES.get(gid)
        if not game:
            return {"ok": False, "error": "unknown game"}
        if not game["enabled"]:
            return {"ok": False, "error": f"{game['name']} is coming soon; only Reorder is available"}
        if state.phase in ("awaiting", "exercise"):
            return {"ok": False, "error": "a game is already running"}
        if gid in ("find_remember", "order_memory"):
            if gid == "find_remember":
                state.fr = FindRemember(objects=FR_OBJECTS)
            else:  # the robot's trained skill starts from one layout, so robot rounds start there
                state.fr = OrderMemory(objects=FR_OBJECTS, fixed_start=ROBOT_START if FR_MOVER == "robot" else None)
            state.watch, state.robot, state.pending_say = None, {}, []
            state.game, state.phase, state.result, state.feedback = gid, "exercise", "none", ""
            step = state.fr.start()
            state.fr_step = step.to_dict()
            return {"ok": True, "say": step.say, "expect": step.expect, "phase": step.phase, "moves": step.moves,
                    "note": "Say the 'say' text. The app runs every later turn of this game itself."}
        state.game, state.phase, state.attempt, state.result = gid, "awaiting", 0, "none"
        state.target, state.feedback = list(TARGET), ""
        await shuffle(state)
        return {"ok": True, "target_order": state.target, "note": "Robot has mixed them up. Tell the person the target order and ask them to say 'done' when finished."}

    if name == "check_arrangement":
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
        state.phase, state.result = "stopped", "stopped"
        if state.fr is not None:
            state.fr_step = state.fr.finish().to_dict()
        return {"ok": True}

    return {"ok": False, "error": "unknown tool"}
