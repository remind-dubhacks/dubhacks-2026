"""Tools the voice agent may call. Everything the model can *do* is listed here; it never sends motor
commands. Game ids are checked against GAMES, and the robot step goes through one function (`shuffle`).

Screen games (faces, proverbs, sounds) follow the Cognitive Stimulation Therapy session themes
(Woods et al., Cochrane 2023). They only change `screen`, which the patient page renders as-is.
Table games (Remember the Order, Find & Remember) use real objects, the robot arm and the camera."""
import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import robot_client
from ..alerts import send_alert
from ..config import settings
from ..games import faces, proverbs, sounds
from ..games.find_remember import FindRemember
from ..games.order_memory import OrderMemory, order_from_detections
from ..games.shuffles import CAMERA_NAMES, ROBOT_START, fix_for
from ..games.table_watch import TableWatch
from ..games.reorder import MAX_TRIALS, evaluate, shuffled
from ..vision.checker import read_order

GAMES = {
    "reorder": {"name": "Reorder", "description": "The robot mixes up three objects and you put them back in order.", "enabled": True},
    "order_memory": {"name": "Remember the Order", "description": "Look at a row of objects, watch them get mixed up, then put them back the way they were.", "enabled": True},
    "find_remember": {"name": "Find & Remember", "description": "Follow one object as it moves, find it, then share a memory about it.", "enabled": True},
    "faces": {"name": "Famous faces", "description": "Look at a photo of a famous person and talk about them.", "enabled": True},
    "proverbs": {"name": "Sayings", "description": "Finish a well-known saying.", "enabled": True},
    "sounds": {"name": "Sounds", "description": "Listen to an everyday sound and talk about it.", "enabled": True},
}
SCREEN_GAMES = {"faces": faces.ITEMS, "proverbs": proverbs.ITEMS, "sounds": sounds.ITEMS}
MAX_MESSAGE_WORDS = 12  # design.md: a message is 12 words at most
REST = {"kind": "rest"}

TARGET = ["cup", "apple", "book"]  # placeholder prop set

# Find & Remember props (must be names known to games/find_remember.OBJECTS) and who moves them:
# simulated (prototype: instant), caregiver (agent asks a caregiver to move them), robot (needs a trained skill).
FR_OBJECTS = [o.strip() for o in os.getenv("FIND_REMEMBER_OBJECTS", "blue keychain,lipstick,white keycap").split(",") if o.strip()]
FR_MOVER = os.getenv("FIND_REMEMBER_MOVER", "simulated")
DISTRESS_RE = re.compile(r"\b(upset|scared|frightened|tired|sad|don'?t like this|want to stop|leave me)\b", re.I)


@dataclass
class GameState:
    game: str | None = None
    phase: str = "idle"  # idle | awaiting | playing | complete | reveal | stopped
    attempt: int = 0
    target: list[str] = field(default_factory=list)
    shuffled_order: list[str] = field(default_factory=list)
    shuffle_id: int = 0  # bumps on each shuffle so the UI knows to reset its table
    feedback: str = ""
    result: str = "none"  # none | correct | gave_up | finished | stopped
    help_requested: bool = False
    alerts: list[str] = field(default_factory=list)
    # Patient screen and screen games
    patient_name: str = ""
    caregiver_phone: str = ""  # E.164; alerts are texted here when set
    session_id: str = ""
    enabled_games: list[str] = field(default_factory=lambda: list(GAMES))
    item_index: int = 0
    screen: dict = field(default_factory=lambda: dict(REST))  # {kind: rest|message|photo|photo_caption, text?, photo?, caption?}
    sound: dict | None = None  # {src, id}; id bumps so the page replays the same clip
    sound_id: int = 0
    games_played: list[str] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    # Table games (Remember the Order, Find & Remember)
    fr: Any = None  # FindRemember engine while that game runs
    fr_step: dict = field(default_factory=dict)  # last step the engine produced
    watch: Any = None  # TableWatch while the person restores the row
    robot: dict = field(default_factory=dict)  # {status: moving|done|failed, purpose, error}
    pending_say: list[str] = field(default_factory=list)  # said by the app when a robot move finishes
    overheat_alerted: bool = False
    objects: list[str] = field(default_factory=list)  # props for table games ("" = FIND_REMEMBER_OBJECTS)
    feed: list[dict] = field(default_factory=list)  # live log for the playground: robot, camera and companion
    mover: str = ""  # who moves the objects in this session: robot | simulated | caregiver ("" = FIND_REMEMBER_MOVER)

    def view(self) -> dict:
        v = {
            "game": self.game, "phase": self.phase, "attempt": self.attempt, "maxTrials": MAX_TRIALS,
            "target": self.target, "shuffledOrder": self.shuffled_order, "shuffleId": self.shuffle_id,
            "feedback": self.feedback, "result": self.result, "helpRequested": self.help_requested, "alerts": self.alerts,
            "itemIndex": self.item_index, "screen": self.screen, "sound": self.sound, "observations": self.observations,
        }
        if isinstance(self.fr, OrderMemory):
            v["exercise"] = {
                "step": self.fr_step, "row": self.fr.current, "answer": self.fr.original,  # answer: caregiver view only
                "level": self.fr.level, "round": self.fr.round, "mover": mover_of(self), "summary": self.fr.summary(),
                "robot": self.robot, "watching": self.watch is not None and not self.watch.done,
                "say": self.fr_step.get("say", ""), "options": self.fr_step.get("options", []), "phase": self.fr.phase,
            }
            if self.phase == "exercise":
                v["screen"] = table_screen(self)
        elif self.fr is not None:
            v["exercise"] = {
                "step": self.fr_step, "layout": self.fr.layout, "tray": self.fr.tray, "target": self.fr.target,
                "level": self.fr.level, "round": self.fr.round, "mover": FR_MOVER, "summary": self.fr.summary(),
            }
        return v


def mover_of(state: "GameState") -> str:
    return state.mover or FR_MOVER


# Live patient sessions (voice/live.py registers them) so the playground can follow the real game.
LIVE: dict[str, "GameState"] = {}
_robot_ready = {"ok": False, "t": 0.0}


def log_feed(state: "GameState", who: str, text: str = "", **data) -> None:
    state.feed.append({"t": time.time(), "who": who, "text": text, **data})
    del state.feed[:-120]


async def robot_ready(max_age_s: float = 15.0) -> bool:
    """Is the robot arm ready? Cached briefly: the worker's health check can take ~20 s in perceptron mode."""
    if time.monotonic() - _robot_ready["t"] < max_age_s:
        return _robot_ready["ok"]
    try:
        ok = bool((await robot_client.health()).get("ready"))
    except Exception:  # noqa: BLE001
        ok = False
    _robot_ready.update(ok=ok, t=time.monotonic())
    return ok


ROBOT_STATUS = {
    "moving": "The robot is mixing them up. Hands on your lap, please.",
    "paused_for_hand": "The robot is waiting for the table to be clear.",
    "checking": "The robot is checking the row.",
}


def table_screen(state: "GameState") -> dict:
    """What the patient screen shows during Remember the Order: the row as the game knows it, what the
    robot is doing, and the current prompt with its choices (tap or say)."""
    om: OrderMemory = state.fr
    robot = state.robot or {}
    if robot.get("status") == "moving":
        status = ROBOT_STATUS.get(robot.get("last") or "moving", ROBOT_STATUS["moving"])
    elif robot.get("status") == "failed":
        status = "A caregiver is coming to help with the objects."
    elif om.phase == "restore":
        status = "Your turn: put them back the way they were."
    elif om.phase == "study":
        status = "Let's look at the row together."
    else:
        status = ""
    show_answer = om.phase in ("study", "reminisce", "recall", "done")
    return {"kind": "table", "row": list(om.original if show_answer else om.current), "status": status,
            "say": state.fr_step.get("say", ""), "options": state.fr_step.get("options", []), "phase": om.phase}


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "list_games", "description": "List the games that can be played.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "start_game", "description": "Start a game. For reorder the robot shuffles the objects; the others show a photo, a saying or play a sound. Only call when the person agrees to play.",
        "parameters": {"type": "object", "properties": {"game_id": {"type": "string", "enum": list(GAMES)}}, "required": ["game_id"]}}},
    {"type": "function", "function": {"name": "check_arrangement", "description": "Look at the table with the camera and judge the order. Call when the person says they are done.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "exercise_step", "description": "Find & Remember / Remember the Order: pass the person's exact words; returns the next thing to say.",
        "parameters": {"type": "object", "properties": {"said": {"type": "string"}}, "required": ["said"]}}},
    {"type": "function", "function": {"name": "alert_caregiver", "description": "Text the caregiver. Use when the person says anything concerning: asks for help, pain, a fall, feeling unwell, fear, distress, confusion about where they are, wanting to leave, or hurting themselves. reason = a short plain summary of what they said and why it is concerning (one or two sentences, no diagnosis).", "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {"name": "stop", "description": "Stop the game and the robot.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "next_item", "description": "Screen games: move on to the next photo, saying or sound. Call after you have talked about the current one.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "reveal", "description": "Screen games: show the answer on screen (the person's name, the full saying, or what the sound was). Use when the person is unsure or has answered.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "play_sound", "description": "Sounds game: play the current sound again.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "show_message", "description": "Show one short, warm sentence on screen (12 words at most), e.g. 'Good morning, Margaret.'",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "end_game", "description": "Finish the current screen game and clear the screen.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "note_response", "description": "Quietly note how the person engaged with the current item, for the nurse. Never a score.",
        "parameters": {"type": "object", "properties": {
            "engagement": {"type": "string", "enum": ["engaged", "some", "withdrawn"]},
            "note": {"type": "string", "description": "One short sentence, e.g. 'Talked about seeing Elvis films with her sister.'"}},
            "required": ["engagement"]}}},
    {"type": "function", "function": {
        "name": "remember", "description": "Save one short, lasting fact about the person for future sessions: people in their life, places, work, favourites, stories they enjoy. Use when they share something worth keeping, and always when they ask you to remember something. Never health details.",
        "parameters": {"type": "object", "properties": {
            "fact": {"type": "string", "description": "One short sentence in the third person with their name, e.g. 'Rose's favourite food is hot dogs.'"}},
            "required": ["fact"]}}},
]


# What the UI shows in the Tools menu. status: real | mock | placeholder
TOOL_INFO = {
    "list_games": {"status": "real", "example": "What games can we play?", "does": "Lists the game catalog."},
    "start_game": {"status": "mock", "example": "Let's play the ordering game.", "does": "Starts a game. Screen games are real; the Reorder robot shuffle is simulated in software for now."},
    "check_arrangement": {"status": "mock", "example": "I'm done.", "does": "Judges the order, counts tries (max 3), explains mistakes. No camera yet, so it always reads the table as correct."},
    "exercise_step": {"status": "real", "example": "The keycap, then the lipstick.", "does": "Runs the next turn of Find & Remember or Remember the Order."},
    "alert_caregiver": {"status": "real", "example": "I need help.", "does": "Records a short summary for the nurse and texts the caregiver (Photon) if a phone number was entered."},
    "stop": {"status": "real", "example": "Stop.", "does": "Ends the game. Also triggered directly by the word 'stop', without the AI."},
    "next_item": {"status": "real", "example": "Let's see the next one.", "does": "Moves a screen game to its next item; clears the screen after the last."},
    "reveal": {"status": "real", "example": "Who is it?", "does": "Shows the name, the full saying, or what the sound was."},
    "play_sound": {"status": "real", "example": "Play it again.", "does": "Replays the current sound on the patient screen."},
    "show_message": {"status": "real", "example": "(Greeting)", "does": "Shows one short sentence on the patient screen (12 words max)."},
    "end_game": {"status": "real", "example": "Let's stop this one.", "does": "Ends a screen game and returns the screen to rest."},
    "note_response": {"status": "real", "example": "(After each item)", "does": "Records engagement and a short note in the session record for the nurse."},
    "remember": {"status": "real", "example": "Remember that my favourite food is hot dogs.", "does": "Saves a lasting fact to this resident's own Backboard memory, straight away."},
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


def _message(text: str) -> dict:
    return {"kind": "message", "text": " ".join(str(text).split()[:MAX_MESSAGE_WORDS])}


def _show_item(state: GameState) -> dict:
    """Put the current screen-game item on screen and return what the model needs to talk about it."""
    item = SCREEN_GAMES[state.game][state.item_index]
    out = {"ok": True, "item": state.item_index + 1, "of": len(SCREEN_GAMES[state.game]), "talking_points": item["talking_points"]}
    if state.game == "faces":
        state.screen = {"kind": "photo", "photo": item["photo"]}
        return {**out, "person": item["name"],
                "note": "The photo is on screen. Ask what they notice or whether the face reminds them of anything. Do not say the name yet."}
    if state.game == "proverbs":
        state.screen = _message(item["shown"])
        return {**out, "shown": item["shown"], "full": item["full"],
                "note": "The saying is on screen with the last word missing. Read it aloud slowly and invite them to finish it."}
    state.sound_id += 1
    state.sound = {"src": item["src"], "id": state.sound_id}
    state.screen = _message("Listen.")
    return {**out, "answer": item["answer"],
            "note": "The sound plays as soon as you stop speaking. Say only 'Have a listen.' and then wait quietly."}


_log = logging.getLogger("remind.alerts")
_tasks: set[asyncio.Task] = set()


def _bg(coro) -> None:
    """Fire and forget: texting must never slow down or break the conversation."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(lambda t: (_tasks.discard(t), t.exception() and _log.warning("alert send failed: %r", t.exception())))


def _moves_note(step, mover: str | None = None) -> str:
    """How the moves in a step get done, as words for the person/caregiver."""
    mover = mover or FR_MOVER
    real = [m for m in step.moves if m.get("from")]
    if not real or mover == "simulated":
        return ""
    pairs = {(m["object"], m["from"], m["to"]) for m in real[::2]}
    what = "; ".join(f"move the {o} from the {a} to the {b}" for o, a, b in pairs)
    who = "Caregiver" if mover == "caregiver" else "Robot (caregiver, if the robot skill isn't trained yet)"
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


# What the companion says when the robot reports something mid-move (worker job events).
ROBOT_EVENT_SAY = {
    "paused_for_hand": "I'll wait until the table is clear, then carry on.",
    "resumed": "Thank you. Carrying on now.",
}
OVERHEAT_C = float(os.getenv("ROBOT_ALERT_TEMP_C", "60"))


async def robot_shuffle(sid: str, on_event=None) -> dict:
    """Run one trained shuffle on the robot worker and wait for it. The worker guards every motion
    and checks the row with its camera afterwards. `on_event` gets each live job event once."""
    job_id = f"om-{uuid.uuid4().hex[:10]}"
    await robot_client.submit(job_id, "shuffle", sid)
    end = time.monotonic() + ROBOT_TIMEOUT_S
    seen = 0
    while time.monotonic() < end:
        await asyncio.sleep(0.5)
        job = await robot_client.status(job_id)
        events = job.get("events") or []
        if on_event:
            for e in events[seen:]:
                on_event(e)
        seen = len(events)
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

    def on_event(e: dict) -> None:
        kind = e.get("kind")
        state.robot = {**state.robot, "last": kind}
        log_feed(state, "robot", kind=kind)
        if kind in ROBOT_EVENT_SAY:
            state.pending_say.append(ROBOT_EVENT_SAY[kind])

    async def go() -> None:
        om: OrderMemory = state.fr
        try:
            job = await robot_shuffle(sid, on_event=on_event)
        except robot_client.RobotWorkerError as e:
            job = {"status": "failed", "errorCode": "worker_unreachable", "error": str(e)}
        ok = job["status"] in ("succeeded", "verifying")
        log_feed(state, "robot", f"{purpose} {'finished' if ok else 'needs help'}", check=(job.get("check") or {}).get("verdict"),
                 tone="ok" if ok else "warn")
        state.robot = {"status": "done" if ok else "failed", "purpose": purpose, "shuffle": sid,
                       "check": job.get("check"), "error": job.get("errorCode")}
        if not ok:
            msg = f"The robot arm needs help during Remember the Order ({purpose}: {job.get('errorCode')}). Please sort the objects."
            state.alerts.append(msg)
            state.help_requested = True
            _bg(send_alert("needs_staff", state.session_id, msg, to=state.caregiver_phone, patient=state.patient_name))
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


async def check_motors(state: GameState) -> str | None:
    """Text the caregiver once per session if a robot motor runs hot (the servos shut down at 65 C)."""
    if getattr(state, "overheat_alerted", False):
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.robot_worker_url}/studio/health")
        follower = r.json().get("follower") or {}
    except Exception:  # noqa: BLE001
        return None
    hot = {m: v.get("tempC") for m, v in follower.items() if isinstance(v, dict) and (v.get("tempC") or 0) >= OVERHEAT_C}
    if not hot:
        return None
    state.overheat_alerted = True
    worst = max(hot, key=hot.get)
    msg = f"The robot arm is running hot ({worst} at {hot[worst]} C). Please let it rest before more robot games."
    state.alerts.append(msg)
    _bg(send_alert("needs_staff", state.session_id, msg, to=state.caregiver_phone, patient=state.patient_name))
    return msg


def session_summary(state: GameState) -> str:
    """A short, plain end-of-session text for the caregiver: what was done and how it went. Facts only,
    never a score."""
    if not state.games_played and not state.observations:
        return ""
    names = [GAMES.get(g, {}).get("name", g) for g in dict.fromkeys(state.games_played)]
    parts = [f"Session ended. Played: {', '.join(names)}." if names else "Session ended."]
    eng = [o.get("engagement") for o in state.observations]
    if eng:
        parts.append(f"Engaged {eng.count('engaged')}, some {eng.count('some')}, withdrawn {eng.count('withdrawn')}.")
    if isinstance(state.fr, OrderMemory) and state.fr.log:
        sm = state.fr.summary()
        parts.append(f"Remember the Order: {sm['rounds']} rows ({sm['restoredAlone']} alone, "
                     f"{sm['restoredWithChoice']} with a choice, {sm['restoredTogether']} together).")
    notes = [o["note"] for o in state.observations if o.get("note")]
    if notes:
        parts.append(f'Note: "{notes[-1][:120]}"')
    if state.alerts:
        parts.append(f"{len(state.alerts)} alert(s) during the session.")
    return " ".join(parts)


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
        log_feed(state, "agent", say)
        return {"say": say, "events": [], "robot": state.robot}
    om = state.fr
    if not isinstance(om, OrderMemory) or om.phase != "restore" or state.watch is None or state.robot.get("status") == "moving":
        return {"say": None, "events": [], "robot": state.robot}
    reading = reading or await camera_row()
    if reading is None:
        return {"say": None, "events": [], "camera": False}
    events = [e.to_dict() for e in state.watch.feed(reading, time.monotonic() if now is None else now)]
    for e in events:
        log_feed(state, "camera", event=e)
    step = om.live(events) if events else None
    if step is None:
        return {"say": None, "events": events}
    state.fr_step = step.to_dict()
    log_feed(state, "agent", step.say)
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
        if mover_of(state) == "robot" and om.last_shuffle_id:
            _robot_task(state, om.last_shuffle_id, "shuffle")  # after_shuffle comes when the robot is done
        elif mover_of(state) == "simulated":
            nxt = om.after_shuffle()
            step.say, step.expect, step.phase = f"{step.say} {nxt.say}", nxt.expect, nxt.phase
            _start_watch(state)
        else:
            step.say += _moves_note(step, mover_of(state))
    elif phase == "shuffle":
        if state.robot.get("status") == "moving":
            return {"ok": True, "say": "The robot is still mixing them up. Hands on your lap for a moment.", "expect": "moved", "phase": "shuffle", "moves": []}
        step = om.after_shuffle()
        _start_watch(state)
    elif phase == "restore" and om.offered_show and mover_of(state) == "robot" and YES_RE.search(said):
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
            log_feed(state, "player", str(args.get("said", "")))
            res = await _om_advance(state, str(args.get("said", "")), table_order)
            if res.get("say"):
                log_feed(state, "agent", res["say"])
            return res
        return _fr_advance(state, str(args.get("said", "")))

    if name == "list_games":
        return {"games": [{"id": k, **v} for k, v in GAMES.items() if k in state.enabled_games]}

    if name == "start_game":
        gid = args.get("game_id")
        game = GAMES.get(gid)
        if not game:
            return {"ok": False, "error": "unknown game"}
        if not game["enabled"] or gid not in state.enabled_games:
            return {"ok": False, "error": f"{game['name']} is not available today"}
        if state.phase in ("awaiting", "exercise"):
            return {"ok": False, "error": "a game is already running"}
        state.game, state.attempt, state.result, state.feedback, state.sound = gid, 0, "none", "", None
        state.games_played.append(gid)
        if gid in ("find_remember", "order_memory"):
            if gid == "find_remember":
                state.fr = FindRemember(objects=FR_OBJECTS)
            else:  # the robot's trained skill starts from one layout, so robot rounds start there
                if mover_of(state) == "robot" and not await robot_ready():
                    state.mover = "caregiver"  # robot offline: a caregiver moves the keyrings; the camera still follows
                    log_feed(state, "robot", "offline: a caregiver will move the keyrings this time", tone="warn")
                objects = state.objects or FR_OBJECTS
                state.fr = OrderMemory(objects=objects, fixed_start=ROBOT_START if mover_of(state) == "robot" else None,
                                       all_objects=set(objects) == set(ROBOT_START))  # the three keycaps: always all three
            state.watch, state.robot, state.pending_say = None, {}, []
            state.phase = "exercise"
            step = state.fr.start()
            state.fr_step = step.to_dict()
            return {"ok": True, "say": step.say, "expect": step.expect, "phase": step.phase, "moves": step.moves,
                    "note": "Say the 'say' text. The app runs every later turn of this game itself."}
        if gid in SCREEN_GAMES:
            state.phase, state.item_index = "playing", 0
            return _show_item(state)
        state.phase, state.target = "awaiting", list(TARGET)
        await shuffle(state)
        state.screen = _message(", ".join(state.target).capitalize() + ".")
        return {"ok": True, "target_order": state.target, "note": "Robot has mixed them up. Tell the person the target order and ask them to say 'done' when finished."}

    if name in ("next_item", "reveal", "play_sound"):
        if state.phase != "playing" or state.game not in SCREEN_GAMES:
            return {"ok": False, "error": "no screen game is running"}
        item = SCREEN_GAMES[state.game][state.item_index]
        if name == "next_item":
            state.sound = None
            if state.item_index + 1 >= len(SCREEN_GAMES[state.game]):
                state.phase, state.result, state.screen = "complete", "finished", dict(REST)
                return {"ok": True, "finished": True, "note": "That was the last one. Thank them warmly and offer another game or a chat."}
            state.item_index += 1
            return _show_item(state)
        if name == "reveal":
            if state.game == "faces":
                state.screen = {"kind": "photo_caption", "photo": item["photo"], "caption": item["caption"]}
            elif state.game == "proverbs":
                state.screen = _message(item["full"])
            else:
                state.screen = _message(item["reveal"])
            return {"ok": True, "shown": state.screen}
        if state.game != "sounds":
            return {"ok": False, "error": "only the sounds game has sounds"}
        state.sound_id += 1
        state.sound = {"src": item["src"], "id": state.sound_id}
        return {"ok": True, "note": "Say only 'Have another listen.' and then wait quietly."}

    if name == "show_message":
        state.screen = _message(args.get("text", ""))
        return {"ok": True, "shown": state.screen["text"]}

    if name == "end_game":
        if state.phase == "awaiting":
            return {"ok": False, "error": "the robot game is waiting for the person; use stop to end it"}
        state.phase, state.screen, state.sound = "idle", dict(REST), None
        return {"ok": True}

    if name == "note_response":
        item = SCREEN_GAMES[state.game][state.item_index]["id"] if state.game in SCREEN_GAMES else None
        engagement = args.get("engagement") if args.get("engagement") in ("engaged", "some", "withdrawn") else "some"
        state.observations.append({"game": state.game, "item": item, "engagement": engagement, "note": str(args.get("note", ""))[:200]})
        return {"ok": True}

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
        reason = str(args.get("reason", "help requested"))[:300]
        state.alerts.append(reason[:200])
        if not state.caregiver_phone:
            return {"ok": True, "note": "Recorded for the nurse. No caregiver phone is set, so no text was sent."}
        _bg(send_alert("help_requested", state.session_id, reason, to=state.caregiver_phone, patient=state.patient_name))
        return {"ok": True, "note": "A caregiver is being texted."}

    if name == "stop":
        state.phase, state.result, state.screen, state.sound = "stopped", "stopped", dict(REST), None
        if state.fr is not None:
            state.fr_step = state.fr.finish().to_dict()
        return {"ok": True}

    if name == "remember":  # handled by the live relay (voice/live.py), which knows whose memory it is
        return {"ok": False, "error": "Memories are not kept in this mode."}

    return {"ok": False, "error": "unknown tool"}
