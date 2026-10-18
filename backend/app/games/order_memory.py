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

from .find_remember import OBJECTS, SPACED_INTERVALS, Step, at, is_unsure, spoken_join  # noqa: F401

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
        self.asked_words = False
        self.guide: int | None = None  # spot we're currently guiding the person to fill
        self.placed: list[int] = []  # spots already right this round
        self.used_choice = False
        self.revealed = False  # avoid repeating the same shuffle twice in a row

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

    def shuffle(self, lead: str = "", pattern: tuple[int, ...] | None = None) -> Step:
        """Mix the row. `pattern[i]` is the original position of the object that ends up in spot i;
        tests pass it to enumerate every case, play picks one at random."""
        if pattern is None:
            pattern = self.rng.choice(self.shuffle_patterns())
        if sorted(pattern) != list(range(len(self.original))) or list(pattern) == list(range(len(self.original))):
            raise ValueError("pattern must be a real mix of the row")
        self.last_pattern = tuple(pattern)
        new = [self.original[i] for i in pattern]
        moves = [{"object": o, "from": self.spots[self.original.index(o)], "to": self.spots[i]} for i, o in enumerate(new) if new[i] != self.original[i]]
        self.current, self.phase = new, "shuffle"
        return Step(say=f"{lead} Now, hands resting on your lap, please, while they get mixed up.".strip(), expect="moved", phase="shuffle", moves=moves)

    def after_shuffle(self) -> Step:
        self.phase, self.asked_words = "restore", False
        self.guide, self.placed, self.used_choice, self.revealed = None, [], False, False
        return Step(
            say="All mixed up! Can you put them back the way they were, from left to right? Take your time, and tell me when you're done.",
            expect="done",
            phase="restore",
        )

    # ------------------------------------------------------------ 4-5. restore (errorless, one spot at a time)

    def check(self, text: str, observed: list[str] | None = None) -> Step:
        """`observed`: left-to-right order from the camera or caregiver. Without it, an order the
        person says in words is used; with neither we ask once, then guide (never a guess)."""
        if observed is not None and sorted(observed) != sorted(self.original):
            observed = None  # the camera missed something: "couldn't see", never an answer
        if observed == self.original:
            return self._restored("That's exactly how they were. What a good memory!" if self.guide is None and not self.placed else "There they are, just like before. Well done!")
        if self.guide is not None:
            return self._guided_answer(text, observed)

        if observed is None:
            named = order_from_text(text, self.original)
            observed = named if len(named) == len(self.original) else None
            if observed == self.original:
                return self._restored("That's exactly how they were. What a good memory!")
        if observed is None and not self.asked_words and not is_unsure(text):
            self.asked_words = True
            return Step(say="I can't see the table from here. Could you tell me the order, from left to right?", expect="done", phase="restore")

        if observed is not None:
            self.current = list(observed)
            right = [o for i, o in enumerate(self.original) if self.current[i] == o]
            self.placed = [i for i, o in enumerate(self.original) if self.current[i] == o]
            lead = (f"The {self.short(right[0])} is in just the right spot." if len(right) == 1 else "Good effort.")
        else:
            self.placed = []
            lead = "That's okay."
        return self._ask_next(lead)

    def _remaining(self) -> list[int]:
        return [i for i in range(len(self.original)) if i not in self.placed]

    def _ask_next(self, lead: str) -> Step:
        left = self._remaining()
        if len(left) <= 1:
            return self._finish_guided(lead)
        i = left[0]
        self.guide = i
        want = self.original[i]
        other = self.rng.choice([self.original[j] for j in left if j != i])
        pair = sorted([want, other], key=lambda _: self.rng.random())
        ask = "Next, what goes" if self.used_choice else "Let's think about what goes"
        self.used_choice = True
        return Step(say=f"{lead} {ask} {at(self.spots[i])}. Was it the {pair[0]}, or the {pair[1]}?", expect="done", phase="restore", options=pair)

    def _guided_answer(self, text: str, observed: list[str] | None) -> Step:
        i, want = self.guide, self.original[self.guide]
        named = order_from_text(text, self.original)
        ok = (observed is not None and observed[i] == want) or (observed is None and named[:1] == [want] and not is_unsure(text))
        if ok:
            lead = f"Yes, the {want} goes {at(self.spots[i])}."
        else:
            lead = f"It's the {want} {at(self.spots[i])}. Let's put it there."
            self.revealed = True
        self.placed.append(i)
        self.guide = None
        return self._ask_next(lead)

    def _finish_guided(self, lead: str) -> Step:
        for j in self._remaining():  # the last spot is decided by the others
            lead += f" And the {self.original[j]} goes {at(self.spots[j])}."
            self.placed.append(j)
        return self._restored(f"{lead} Now they're just like before.")

    def _restored(self, praise: str) -> Step:
        help_level = 2 if getattr(self, "revealed", False) else 1 if getattr(self, "used_choice", False) else 0
        self.current = list(self.original)
        self.guide = None
        self.log.append(OrderRound(list(self.original), help=help_level))
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
