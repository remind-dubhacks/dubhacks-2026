"""Tools the voice agent may call. Everything the model can *do* is listed here; it never sends motor
commands. Game ids are checked against GAMES, and the robot step goes through one function (`shuffle`)."""
from dataclasses import dataclass, field

from ..games.reorder import MAX_TRIALS, evaluate, shuffled
from ..vision.checker import read_order

GAMES = {
    "reorder": {"name": "Reorder", "description": "The robot mixes up three objects and you put them back in order.", "enabled": True},
    "memory_match": {"name": "Memory match", "description": "Coming soon", "enabled": False},
    "sort_by_colour": {"name": "Sort by colour", "description": "Coming soon", "enabled": False},
}

TARGET = ["cup", "apple", "book"]  # placeholder prop set


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

    def view(self) -> dict:
        return {
            "game": self.game, "phase": self.phase, "attempt": self.attempt, "maxTrials": MAX_TRIALS,
            "target": self.target, "shuffledOrder": self.shuffled_order, "shuffleId": self.shuffle_id,
            "feedback": self.feedback, "result": self.result, "helpRequested": self.help_requested, "alerts": self.alerts,
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


async def shuffle(state: GameState) -> None:
    """Prototype: shuffles in software. Replace with a robot worker job (`POST /jobs` with actionId=shuffle)."""
    state.shuffled_order = shuffled(state.target)
    state.shuffle_id += 1


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
        if state.phase == "awaiting":
            return {"ok": False, "error": "a game is already running"}
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
        return {"ok": True}

    return {"ok": False, "error": "unknown tool"}
