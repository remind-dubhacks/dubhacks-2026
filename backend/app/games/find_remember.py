"""Find & Remember: an object-based memory activity built on evidence-informed dementia-care methods.

One round:
  1. Meet the objects  - name each object and where it is; the person CHOOSES which one to follow.
  2. Watch the move    - the robot (or caregiver) moves it slowly while the agent narrates.
  3. Find it           - "Where is the pen now?" with an errorless cueing ladder:
                         open question -> two-option choice -> show-and-tell. Never "wrong".
  4. Do something      - "Could you pick it up and put it in the tray?" (hands-on, success-ending).
  5. Share a memory    - one optional reminiscence question about the object; any answer is welcome.
  6. Spaced recall     - later, "What did we put in the tray?" at growing intervals.

Methods (see docs/EXERCISE_FIND_AND_REMEMBER.md for references and limits):
  errorless learning, spaced retrieval, Cognitive Stimulation Therapy principles, reminiscence,
  Montessori-based activity design. This is an engagement activity, not a test or a treatment:
  nothing here produces a score, and response times are never recorded.

Pure logic: no I/O. The caller executes `moves` (robot or caregiver) and supplies what the person
said or what the camera saw."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

SPOTS_2 = ["left", "right"]
SPOTS_3 = ["left", "middle", "right"]

# Objects we have on the table. `use` is an opinion question (no right answer); `memories` are
# open, optional reminiscence prompts that never presume a fact about the person's life.
OBJECTS: dict[str, dict] = {
    "lipstick": {
        "short": "lipstick",
        "use": "What colour would you choose for a special day?",
        "memories": [
            "Did you have a favourite lipstick or perfume for special occasions?",
            "Who did you like to get ready with before going out?",
            "Was there a colour you always felt good wearing?",
        ],
    },
    "pink pen": {
        "short": "pen",
        "use": "What would you write with a pen like this?",
        "memories": [
            "Did you ever write letters or cards to someone special?",
            "Some people love writing lists, others love writing stories. What did you like to write?",
            "Did you have a favourite colour of ink?",
        ],
    },
    "blue keychain": {
        "short": "keychain",
        "use": "What would you keep on a keychain like this?",
        "memories": [
            "What keys did you carry with you most days?",
            "Was there a door you always loved coming home to?",
            "Some people collect keychains from places they visit. Did you ever bring one home from somewhere?",
        ],
    },
    "black keycap": {
        "short": "black one",
        "use": "This comes from a keyboard. What would you like to type?",
        "memories": [
            "Did you ever use a typewriter or a computer keyboard?",
            "Was there a desk or a room where you liked to write?",
        ],
    },
    "purple keycap": {
        "short": "purple one",
        "use": "What does this colour remind you of?",
        "memories": [
            "Is there a flower or a colour you have always loved?",
            "Did you have a favourite piece of clothing in a colour like this?",
        ],
    },
    "white keycap": {
        "short": "keycap",
        "use": "This comes from a keyboard. What would you like to type?",
        "memories": [
            "Did you ever use a typewriter or a computer keyboard?",
            "Is there a letter that is special to you, like the first letter of a name?",
            "What was something you enjoyed writing or typing?",
        ],
    },
    "tea box": {
        "short": "tea",
        "use": "How do you like your tea?",
        "memories": ["Did you enjoy tea with family or friends?", "Was there a favourite cup you liked to use?"],
    },
    "coffee box": {
        "short": "coffee",
        "use": "Do you like your coffee strong or mild?",
        "memories": ["Was there a place you liked to have coffee?", "Who did you like to share a coffee with?"],
    },
}

# Never used anywhere in spoken text (asserted in tests).
BANNED_WORDS = ("wrong", "incorrect", "mistake", "fail", "test", "score", "no,")

LEVELS = {  # difficulty grows only after easy successes, and drops at the first sign of effort
    1: {"objects": 2, "moves": 1},
    2: {"objects": 3, "moves": 1},
    3: {"objects": 3, "moves": 2},
}
SPACED_INTERVALS = [1, 2, 4]  # rounds until the next recall question; reset to 1 after a cue was needed


@dataclass
class Step:
    say: str
    expect: str  # what we wait for: choice | moved | spot | done | talk | recall | nothing
    phase: str
    moves: list[dict] = field(default_factory=list)  # [{object, from, to}] for robot/caregiver
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"say": self.say, "expect": self.expect, "phase": self.phase, "moves": self.moves, "options": self.options}


@dataclass
class RoundLog:
    target: str
    level: int
    cue: int = 0  # 0 open answer, 1 needed the choice, 2 needed to be shown
    did_task: bool = False
    shared_memory: bool = False


def at(spot: str) -> str:
    """'on the left', 'in the middle', 'on the right', 'in the tray'."""
    return f"in the {spot}" if spot in ("middle", "tray") else f"on the {spot}"


def spoken_join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def parse_spot(text: str, spots: list[str]) -> str | None:
    t = text.lower()
    hits = [s for s in spots if re.search(rf"\b{s}\b", t)]
    if not hits and "center" in t and "middle" in spots:
        hits = ["middle"]
    if not hits and re.search(r"\btray\b", t):
        hits = ["tray"]
    return hits[0] if len(hits) == 1 else None


def is_unsure(text: str) -> bool:
    return bool(re.search(r"don'?t know|not sure|no idea|can'?t remember|forgot|help|\bhmm\b|^\s*$", text.lower()))


class FindRemember:
    def __init__(self, objects: list[str] | None = None, max_rounds: int = 4, seed: int | None = None) -> None:
        self.pool = [o for o in (objects or ["blue keychain", "lipstick", "white keycap"]) if o in OBJECTS]
        if len(self.pool) < 2:
            raise ValueError("need at least two known objects")
        self.rng = random.Random(seed)
        self.max_rounds = max_rounds
        self.level = 1
        self.round = 0
        self.layout: dict[str, str] = {}  # spot -> object
        self.target: str | None = None
        self.phase = "idle"
        self.cue = 0
        self.log: list[RoundLog] = []
        self.tray: list[str] = []  # objects put in the tray, in order
        self.recall_due: int | None = None  # round number when the next spaced-recall question is due
        self.recall_step = 0
        self.memory_prompts_used: set[str] = set()

    # ------------------------------------------------------------ helpers

    @property
    def spots(self) -> list[str]:
        return SPOTS_3 if LEVELS[self.level]["objects"] == 3 else SPOTS_2

    def where(self, obj: str) -> str | None:
        return next((s for s, o in self.layout.items() if o == obj), None)

    def short(self, obj: str) -> str:
        return OBJECTS[obj]["short"]

    def neighbour(self, spot: str) -> str | None:
        i = self.spots.index(spot)
        for j in (i - 1, i + 1):
            if 0 <= j < len(self.spots) and self.spots[j] in self.layout:
                return self.layout[self.spots[j]]
        return None

    # ------------------------------------------------------------ 1. meet the objects

    def start(self) -> Step:
        self.round += 1
        n = min(LEVELS[self.level]["objects"], len(self.pool))
        chosen = self.rng.sample(self.pool, n)
        self.layout = dict(zip(self.spots[:n] if n == len(self.spots) else SPOTS_2, chosen))
        self.target, self.cue, self.phase = None, 0, "choose"
        intro = [f"the {o} {at(s)}" for s, o in self.layout.items()]
        greeting = "Let's look at a few things together." if self.round == 1 else "Here's our next round."
        return Step(
            say=f"{greeting} We have {spoken_join(intro)}. Which one would you like us to keep an eye on?",
            expect="choice",
            phase="choose",
            options=list(self.layout.values()),
            # Setup moves put this round's objects in place (caregiver or robot; nothing moves yet if already there).
            moves=[{"object": o, "from": None, "to": s} for s, o in self.layout.items()],
        )

    def choose(self, text: str) -> Step:
        """The person picks an object (any mention works); if unsure we pick for them, kindly."""
        t = text.lower()
        picked = next((o for o in self.layout.values() if o in t or self.short(o) in t), None)
        lead = ""
        if picked is None:
            picked = self.rng.choice(list(self.layout.values()))
            resting = next((o for o in OBJECTS if o not in self.layout.values() and (o in t or self.short(o) in t)), None)
            # Acknowledge their choice even when that object is off the table this round.
            lead = f"Good choice. The {self.short(resting)} is having a rest this round, so let's follow the {picked}. " if resting else f"Let's follow the {picked}. "
        self.target = picked
        return self.watch(lead + OBJECTS[picked]["use"] + " ")

    # ------------------------------------------------------------ 2. watch the move

    def watch(self, lead: str = "") -> Step:
        assert self.target
        moves: list[dict] = []
        for _ in range(LEVELS[self.level]["moves"]):
            src = self.where(self.target)
            dst = self.rng.choice([s for s in self.spots if s in self.layout and s != src])
            other = self.layout[dst]
            self.layout[src], self.layout[dst] = other, self.target  # swap
            moves += [{"object": self.target, "from": src, "to": dst}, {"object": other, "from": dst, "to": src}]
        narration = ". ".join(f"The {m['object']} goes to the {m['to']}" for m in moves[::2])
        self.phase = "watch"
        return Step(
            say=f"{lead}Now let's watch closely. Hands resting on your lap, please. {narration}.",
            expect="moved",
            phase="watch",
            moves=moves,
        )

    # ------------------------------------------------------------ 3. find it (errorless cueing)

    def after_move(self) -> Step:
        self.phase, self.cue = "find", 0
        return Step(say=f"Where is the {self.target} now?", expect="spot", phase="find", options=list(self.layout))

    def answer(self, text: str) -> Step:
        assert self.target
        right = self.where(self.target)
        said = None if is_unsure(text) else parse_spot(text, list(self.layout))
        if said == right:
            return self._found(f"Yes, the {self.target} is {at(right)}. Well spotted!")
        # Unsure, unclear, or a different spot: never say it was wrong; just give more support.
        self.cue += 1
        if self.cue == 1:
            other = self.rng.choice([s for s in self.layout if s != right])
            pair = sorted([right, other], key=self.spots.index)
            lead = "Let's look together. " if said else "That's okay. "
            return Step(say=f"{lead}Is the {self.target} {at(pair[0])}, or {at(pair[1])}?", expect="spot", phase="find", options=pair)
        nb = self.neighbour(right)
        beside = f", next to the {nb}" if nb else ""
        return self._found(f"Let's find it together. The {self.target} is {at(right)}{beside}. There it is.")

    def _found(self, praise: str) -> Step:
        assert self.target
        self.log.append(RoundLog(self.target, self.level, cue=min(self.cue, 2)))
        self.phase = "act"
        return Step(say=f"{praise} Could you pick up the {self.target} and put it in the tray?", expect="done", phase="act")

    # ------------------------------------------------------------ 4. do something

    def did_task(self, confirmed: bool = True) -> Step:
        assert self.target
        self.log[-1].did_task = confirmed
        if confirmed:
            self.tray.append(self.target)
            self.layout = {s: o for s, o in self.layout.items() if o != self.target}
        lead = "Lovely, thank you." if confirmed else "That's fine, we can leave it there."
        return self.reminisce(lead)

    # ------------------------------------------------------------ 5. share a memory (optional)

    def reminisce(self, lead: str) -> Step:
        assert self.target
        prompts = [p for p in OBJECTS[self.target]["memories"] if p not in self.memory_prompts_used] or OBJECTS[self.target]["memories"]
        q = self.rng.choice(prompts)
        self.memory_prompts_used.add(q)
        self.phase = "reminisce"
        return Step(say=f"{lead} {q} You can skip this one if you like.", expect="talk", phase="reminisce")

    def shared(self, text: str) -> Step:
        """Any reply is welcome; we never correct or question a personal memory."""
        skipped = bool(re.search(r"\b(skip|pass|no thanks|rather not|next)\b", text.lower())) or not text.strip()
        if self.log:
            self.log[-1].shared_memory = not skipped
        ack = "Of course, let's carry on." if skipped else "Thank you for sharing that with me."
        self._adapt()
        self._schedule_recall()
        return self.next_step(ack)

    # ------------------------------------------------------------ 6. spaced recall + flow

    def _schedule_recall(self) -> None:
        if self.recall_due is None and self.tray:
            self.recall_due = self.round + SPACED_INTERVALS[0]

    def next_step(self, lead: str) -> Step:
        if self.recall_due is not None and self.round >= self.recall_due and self.tray:
            self.phase, self.cue = "recall", 0
            return Step(say=f"{lead} Here's a little memory question. What was the first thing we put in the tray?", expect="recall", phase="recall")
        if self.round >= self.max_rounds or len(self.pool) < 2:
            return self.finish(lead)
        return Step(say=f"{lead} {self.start().say}", expect="choice", phase="choose", options=list(self.layout.values()), moves=[{"object": o, "from": None, "to": s} for s, o in self.layout.items()])

    def recall(self, text: str) -> Step:
        first = self.tray[0]
        t = text.lower()
        named = next((o for o in self.tray + list(self.layout.values()) if o in t or self.short(o) in t), None)
        if named == first:
            self.recall_step = min(self.recall_step + 1, len(SPACED_INTERVALS) - 1)
            self.recall_due = self.round + SPACED_INTERVALS[self.recall_step]
            return self.next_step(f"Yes, it was the {first}. What a good memory!")
        self.cue += 1
        if self.cue == 1:  # first miss or "not sure": offer a two-way choice
            options = list(dict.fromkeys([first] + [o for o in self.pool if o != first]))[:2]
            self.rng.shuffle(options)
            return Step(say=f"Let's think together. Was it the {options[0]}, or the {options[1]}?", expect="recall", phase="recall", options=options)
        # Show the answer and ask again sooner (spaced retrieval: shorten the interval after support).
        self.recall_step = 0
        self.recall_due = self.round + SPACED_INTERVALS[0]
        return self.next_step(f"It was the {first}. It's right there in the tray.")

    def _adapt(self) -> None:
        recent = [r.cue for r in self.log if r.level == self.level][-2:]
        if len(recent) == 2 and all(c == 0 for c in recent) and self.level < 3:
            self.level += 1
        elif self.log and self.log[-1].cue == 2 and self.level > 1:
            self.level -= 1

    def finish(self, lead: str = "") -> Step:
        self.phase = "done"
        found = spoken_join([f"the {r.target}" for r in self.log]) if self.log else "some lovely things"
        return Step(say=f"{lead} We found {found} together. Thank you, I really enjoyed that.".strip(), expect="nothing", phase="done")

    # ------------------------------------------------------------ caregiver summary (non-clinical)

    def summary(self) -> dict:
        return {
            "rounds": len(self.log),
            "level": self.level,
            "objects": [r.target for r in self.log],
            "foundWithoutHelp": sum(r.cue == 0 for r in self.log),
            "foundWithChoice": sum(r.cue == 1 for r in self.log),
            "foundTogether": sum(r.cue == 2 for r in self.log),
            "sharedMemories": sum(r.shared_memory for r in self.log),
            "note": "Engagement notes for the caregiver only. Not a clinical score or a measure of memory.",
        }
