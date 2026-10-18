"""Tools the voice agent may call. Everything the model can *do* is listed here; it never sends motor
commands. Game ids are checked against GAMES, and the robot step goes through one function (`shuffle`).

Screen games (faces, proverbs, sounds) follow the Cognitive Stimulation Therapy session themes
(Woods et al., Cochrane 2023). They only change `screen`, which the patient page renders as-is."""
import asyncio
import logging
from dataclasses import dataclass, field

from ..alerts import send_alert
from ..games import faces, proverbs, sounds
from ..games.reorder import MAX_TRIALS, evaluate, shuffled
from ..vision.checker import read_order

GAMES = {
    "reorder": {"name": "Reorder", "description": "The robot mixes up three objects and you put them back in order.", "enabled": True},
    "faces": {"name": "Famous faces", "description": "Look at a photo of a famous person and talk about them.", "enabled": True},
    "proverbs": {"name": "Sayings", "description": "Finish a well-known saying.", "enabled": True},
    "sounds": {"name": "Sounds", "description": "Listen to an everyday sound and talk about it.", "enabled": True},
}
SCREEN_GAMES = {"faces": faces.ITEMS, "proverbs": proverbs.ITEMS, "sounds": sounds.ITEMS}
MAX_MESSAGE_WORDS = 12  # design.md: a message is 12 words at most
REST = {"kind": "rest"}

TARGET = ["cup", "apple", "book"]  # placeholder prop set


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

    def view(self) -> dict:
        return {
            "game": self.game, "phase": self.phase, "attempt": self.attempt, "maxTrials": MAX_TRIALS,
            "target": self.target, "shuffledOrder": self.shuffled_order, "shuffleId": self.shuffle_id,
            "feedback": self.feedback, "result": self.result, "helpRequested": self.help_requested, "alerts": self.alerts,
            "itemIndex": self.item_index, "screen": self.screen, "sound": self.sound, "observations": self.observations,
        }


TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": "list_games", "description": "List the games that can be played.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "start_game", "description": "Start a game. For reorder the robot shuffles the objects; the others show a photo, a saying or play a sound. Only call when the person agrees to play.",
        "parameters": {"type": "object", "properties": {"game_id": {"type": "string", "enum": list(GAMES)}}, "required": ["game_id"]}}},
    {"type": "function", "function": {"name": "check_arrangement", "description": "Look at the table with the camera and judge the order. Call when the person says they are done.", "parameters": {"type": "object", "properties": {}}}},
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
]


# What the UI shows in the Tools menu. status: real | mock | placeholder
TOOL_INFO = {
    "list_games": {"status": "real", "example": "What games can we play?", "does": "Lists the game catalog."},
    "start_game": {"status": "mock", "example": "Let's play the ordering game.", "does": "Starts a game. Screen games are real; the Reorder robot shuffle is simulated in software for now."},
    "check_arrangement": {"status": "mock", "example": "I'm done.", "does": "Judges the order, counts tries (max 3), explains mistakes. No camera yet, so it always reads the table as correct."},
    "alert_caregiver": {"status": "real", "example": "I need help.", "does": "Records a short summary for the nurse and texts the caregiver (Photon) if a phone number was entered."},
    "stop": {"status": "real", "example": "Stop.", "does": "Ends the game. Also triggered directly by the word 'stop', without the AI."},
    "next_item": {"status": "real", "example": "Let's see the next one.", "does": "Moves a screen game to its next item; clears the screen after the last."},
    "reveal": {"status": "real", "example": "Who is it?", "does": "Shows the name, the full saying, or what the sound was."},
    "play_sound": {"status": "real", "example": "Play it again.", "does": "Replays the current sound on the patient screen."},
    "show_message": {"status": "real", "example": "(Greeting)", "does": "Shows one short sentence on the patient screen (12 words max)."},
    "end_game": {"status": "real", "example": "Let's stop this one.", "does": "Ends a screen game and returns the screen to rest."},
    "note_response": {"status": "real", "example": "(After each item)", "does": "Records engagement and a short note in the session record for the nurse."},
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


async def run_tool(state: GameState, name: str, args: dict, table_order: list[str] | None) -> dict:
    if name == "list_games":
        return {"games": [{"id": k, **v} for k, v in GAMES.items() if k in state.enabled_games]}

    if name == "start_game":
        gid = args.get("game_id")
        game = GAMES.get(gid)
        if not game:
            return {"ok": False, "error": "unknown game"}
        if not game["enabled"] or gid not in state.enabled_games:
            return {"ok": False, "error": f"{game['name']} is not available today"}
        if state.phase == "awaiting":
            return {"ok": False, "error": "a game is already running"}
        state.game, state.attempt, state.result, state.feedback, state.sound = gid, 0, "none", "", None
        state.games_played.append(gid)
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
        return {"ok": True}

    return {"ok": False, "error": "unknown tool"}
