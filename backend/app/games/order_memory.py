"""Remember the Order: look at a row of familiar objects, say them together, watch them get mixed
up, then put them back the way they were.

One round:
  1. Study      - name the objects left to right and say them together once (rehearsal with
                  the person's own voice; a little story links them).
  2. Say back   - the person says the order; whatever they say, we say it together once more.
  3. Shuffle    - robot (or caregiver) mixes them up while hands rest on the lap.
  4. Restore    - "Can you put them back the way they were?" The camera (or caregiver) reads
                  the order left to right.
  5. Errorless  - right spots are praised; then a two-way choice for the first wrong spot;
                  then the full order is shown and restored together. Never "wrong".
  6. Memory     - one optional reminiscence question about an object.
  7. Recall     - later: "Which one was on the left at the very start?" (spaced retrieval).

Same evidence base, language rules and limits as Find & Remember (see
docs/EXERCISE_FIND_AND_REMEMBER.md). Pure logic, no I/O: the caller does the moves and passes
what the person said and what the camera saw."""

from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass, field

from .find_remember import OBJECTS, SPACED_INTERVALS, Step, at, is_unsure, spoken_join

LEVELS = {1: 2, 2: 3}  # objects per row


@dataclass
class OrderRound:
    order: list[str]
    help: int = 0  # 0 restored alone, 1 needed a choice, 2 restored together
    shared_memory: bool = False


def order_from_text(text: str, objects: list[str]) -> list[str]:
    """Objects named in the text, in the order they were said (short names work)."""
    t = text.lower()
    hits = []
    for o in objects:
        idx = [m.start() for name in {o, OBJECTS[o]["short"]} for m in re.finditer(re.escape(name), t)]
        if idx:
            hits.append((min(idx), o))
    return [o for _, o in sorted(hits)]


class OrderMemory:
    def __init__(self, objects: list[str] | None = None, max_rounds: int = 3, seed: int | None = None) -> None:
        self.pool = [o for o in (objects or ["lipstick", "blue keychain", "white keycap"]) if o in OBJECTS]
        if len(self.pool) < 2:
            raise ValueError("need at least two known objects")
        self.rng = random.Random(seed)
        self.max_rounds = max_rounds
        self.level = 1
        self.round = 0
        self.original: list[str] = []
        self.current: list[str] = []
        self.phase = "idle"
        self.help = 0
        self.log: list[OrderRound] = []
        self.first_left: str | None = None  # for the spaced recall question
        self.recall_due: int | None = None
        self.recall_step = 0
        self.memory_prompts_used: set[str] = set()
        self.last_pattern: tuple[int, ...] | None = None
        self.asked_words = False  # avoid repeating the same shuffle twice in a row

    def short(self, o: str) -> str:
        return OBJECTS[o]["short"]

    def names(self, order: list[str]) -> str:
        return spoken_join([f"the {o}" for o in order])

    @property
    def spots(self) -> list[str]:
        return ["left", "right"] if len(self.original) == 2 else ["left", "middle", "right"]

    # ------------------------------------------------------------ 1-2. study and say back

    def start(self) -> Step:
        self.round += 1
        n = min(LEVELS[self.level], len(self.pool))
        self.original = self.rng.sample(self.pool, n)
        self.current = list(self.original)
        self.first_left = self.first_left or self.original[0]
        self.help, self.phase = 0, "study"
        chant = ", ".join(self.short(o) for o in self.original)
        intro = "Here's a little memory game." if self.round == 1 else "Let's do another row."
        return Step(
            say=f"{intro} Let's look at these from left to right: {self.names(self.original)}. "
            f"Let's say them together: {chant}. Can you say them back to me?",
            expect="talk",
            phase="study",
            options=list(self.original),
            moves=[{"object": o, "from": None, "to": s} for o, s in zip(self.original, self.spots)],
        )

    def say_back(self, text: str) -> Step:
        said = order_from_text(text, self.original)
        chant = ", ".join(self.short(o) for o in self.original)
        lead = "Lovely, just like that." if said == self.original else f"Let's say it once more together: {chant}."
        return self.shuffle(lead)

    # ------------------------------------------------------------ 3. shuffle

    def shuffle_patterns(self) -> list[tuple[int, ...]]:
        """All ways to mix the row (never the original order). With 3 objects: 3 swaps where one
        object stays put (easier) and 2 rotations where all move (harder)."""
        n = len(self.original)
        perms = [p for p in itertools.permutations(range(n)) if p != tuple(range(n))]
        needed_help = bool(self.log) and self.log[-1].help > 0
        if needed_help or self.level == 1:
            easy = [p for p in perms if sum(i != j for i, j in enumerate(p)) == 2]
            perms = easy or perms
        fresh = [p for p in perms if p != self.last_pattern]
        return fresh or perms

    def shuffle(self, lead: str = "") -> Step:
        pattern = self.rng.choice(self.shuffle_patterns())
        self.last_pattern = pattern
        new = [self.original[i] for i in pattern]  # always actually mixed up
        moves = [{"object": o, "from": self.spots[self.original.index(o)], "to": self.spots[i]} for i, o in enumerate(new) if new[i] != self.original[i]]
        self.current, self.phase = new, "shuffle"
        return Step(say=f"{lead} Now, hands resting on your lap, please, while they get mixed up.".strip(), expect="moved", phase="shuffle", moves=moves)

    def after_shuffle(self) -> Step:
        self.phase, self.help, self.asked_words = "restore", 0, False
        return Step(
            say="All mixed up! Can you put them back the way they were, from left to right? Take your time, and tell me when you're done.",
            expect="done",
            phase="restore",
        )

    # ------------------------------------------------------------ 4-5. restore (errorless)

    def check(self, text: str, observed: list[str] | None = None) -> Step:
        """`observed`: left-to-right order from the camera or caregiver. Without it, a named order
        in the person's words is used; with neither, we restore it together (never a guess)."""
        if observed is not None and sorted(observed) != sorted(self.original):
            observed = None  # the camera missed something: treat as "couldn't see", never as an answer
        if observed is None:
            named = order_from_text(text, self.original)
            observed = named if len(named) == len(self.original) else None
        if observed is None and self.help == 0 and not self.asked_words and not is_unsure(text):
            self.asked_words = True
            return Step(say="I can't see the table from here. Could you tell me the order, from left to right?", expect="done", phase="restore")
        if observed is not None:
            self.current = list(observed)
        if self.current == self.original and observed is not None:
            return self._restored("That's exactly how they were. What a good memory!")

        self.help += 1
        if self.help == 1 and not is_unsure(text) and observed is not None:
            right = [o for i, o in enumerate(self.original) if self.current[i] == o]
            first_off = next(i for i, o in enumerate(self.original) if self.current[i] != o)
            want = self.original[first_off]
            other = self.rng.choice([o for o in self.original if o != want])
            pair = sorted([want, other], key=lambda _: self.rng.random())
            praise = f"The {self.short(right[0])} is in just the right spot. " if right else "Good effort. "
            return Step(
                say=f"{praise}Let's look at the {self.spots[first_off]} together. Was it the {pair[0]}, or the {pair[1]}?",
                expect="done",
                phase="restore",
                options=pair,
            )
        if self.help == 1:
            first = self.original[0]
            other = self.rng.choice(self.original[1:])
            pair = sorted([first, other], key=lambda _: self.rng.random())
            return Step(say=f"That's okay. Let's start on the left. Was it the {pair[0]}, or the {pair[1]}?", expect="done", phase="restore", options=pair)
        # Show the whole order and put it back together: every round ends restored.
        self.current = list(self.original)
        return self._restored(f"Let's put them back together: {self.names(self.original)}. There they are, just like before.", help_used=True)

    def _restored(self, praise: str, help_used: bool = False) -> Step:
        self.log.append(OrderRound(list(self.original), help=2 if help_used else min(self.help, 1)))
        return self.reminisce(praise)

    # ------------------------------------------------------------ 6. memory (optional)

    def reminisce(self, lead: str) -> Step:
        obj = self.rng.choice(self.original)
        prompts = [p for p in OBJECTS[obj]["memories"] if p not in self.memory_prompts_used] or OBJECTS[obj]["memories"]
        q = self.rng.choice(prompts)
        self.memory_prompts_used.add(q)
        self.phase = "reminisce"
        return Step(say=f"{lead} {q} You can skip this one if you like.", expect="talk", phase="reminisce")

    def shared(self, text: str) -> Step:
        skipped = bool(re.search(r"\b(skip|pass|no thanks|rather not|next)\b", text.lower())) or not text.strip()
        if self.log:
            self.log[-1].shared_memory = not skipped
        ack = "Of course, let's carry on." if skipped else "Thank you for sharing that with me."
        last = self.log[-1].help if self.log else 1
        if last == 0 and self.level < max(LEVELS) and len(self.pool) > LEVELS[self.level]:
            self.level += 1
        elif last == 2 and self.level > 1:
            self.level -= 1
        if self.recall_due is None:
            self.recall_due = self.round + SPACED_INTERVALS[0]
        return self.next_step(ack)

    # ------------------------------------------------------------ 7. spaced recall + flow

    def next_step(self, lead: str) -> Step:
        if self.recall_due is not None and self.round >= self.recall_due:
            self.phase, self.help = "recall", 0
            return Step(say=f"{lead} One more memory question. In our very first row, which one was on the left?", expect="talk", phase="recall")
        if self.round >= self.max_rounds:
            return self.finish(lead)
        nxt = self.start()
        nxt.say = f"{lead} {nxt.say}"
        return nxt

    def recall(self, text: str) -> Step:
        assert self.first_left
        named = order_from_text(text, list(OBJECTS))
        if named and named[0] == self.first_left:
            self.recall_step = min(self.recall_step + 1, len(SPACED_INTERVALS) - 1)
            self.recall_due = self.round + SPACED_INTERVALS[self.recall_step]
            return self.next_step(f"Yes, it was the {self.first_left}. Well remembered!")
        self.help += 1
        if self.help == 1:
            other = self.rng.choice([o for o in self.pool if o != self.first_left])
            pair = sorted([self.first_left, other], key=lambda _: self.rng.random())
            return Step(say=f"Let's think together. Was it the {pair[0]}, or the {pair[1]}?", expect="talk", phase="recall", options=pair)
        self.recall_step = 0
        self.recall_due = self.round + SPACED_INTERVALS[0]
        return self.next_step(f"It was the {self.first_left}, on the left.")

    def finish(self, lead: str = "") -> Step:
        self.phase = "done"
        return Step(say=f"{lead} We remembered {len(self.log)} rows together. Thank you, I really enjoyed that.".strip(), expect="nothing", phase="done")

    def summary(self) -> dict:
        return {
            "rounds": len(self.log),
            "level": self.level,
            "restoredAlone": sum(r.help == 0 for r in self.log),
            "restoredWithChoice": sum(r.help == 1 for r in self.log),
            "restoredTogether": sum(r.help == 2 for r in self.log),
            "sharedMemories": sum(r.shared_memory for r in self.log),
            "note": "Engagement notes for the caregiver only. Not a clinical score or a measure of memory.",
        }


def order_from_detections(detections: list[dict], objects: list[str]) -> list[str] | None:
    """Left-to-right order of taught objects from the robot worker's vision detections."""
    named = {}
    for d in detections:
        if d.get("name") in objects and (d["name"] not in named or d["score"] > named[d["name"]]["score"]):
            named[d["name"]] = d
    if set(named) != set(objects):
        return None  # not all objects seen clearly: don't guess
    return [n for n, _ in sorted(named.items(), key=lambda kv: kv[1]["center"][0])]
