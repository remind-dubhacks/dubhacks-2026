"""Follows the table while the person restores the row, and decides *when* the agent may speak.

Fed with camera readings (the robot worker's /studio/vision/row, roughly every second). Pure logic,
time is passed in, so every case is testable.

Timing rules (errorless learning, and not talking over someone who is busy):
- Never speak while a hand is on the table: the person is in the middle of something.
- A placement is judged only once the row has *settled* (same reading, no hands, SETTLE_S).
- Right spot: a short "yes". Wrong spot: no comment at first; if it is still wrong after
  WRONG_GRACE_S of calm, a gentle two-way choice. Never the word "wrong".
- Holding a keyring for HOLD_CUE_S: "Where was the X at the start?"
- No activity: encouragement at HESITATE_S[0], a choice at [1], the robot offers to show at [2].
- At most one cue per MIN_GAP_S, so the person is never flooded."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

SETTLE_S = float(os.getenv("WATCH_SETTLE_S", "2.0"))
WRONG_GRACE_S = float(os.getenv("WATCH_WRONG_GRACE_S", "4.0"))
HOLD_CUE_S = float(os.getenv("WATCH_HOLD_CUE_S", "10"))
HESITATE_S = tuple(float(x) for x in os.getenv("WATCH_HESITATE_S", "20,45,75").split(","))
MIN_GAP_S = float(os.getenv("WATCH_MIN_GAP_S", "8"))


@dataclass
class Event:
    kind: str  # lifted | placed | complete | wrong_stays | holding | hesitate | unsure
    obj: str | None = None
    spot: int | None = None  # 0-based
    right: bool | None = None
    level: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class TableWatch:
    original: list[str]
    row: list[str]  # last settled row (starts as the shuffled row)
    t0: float
    last_activity: float = 0.0
    last_cue: float = -1e9
    hesitation: int = 0  # highest hesitation level already used
    candidate: tuple | None = None  # (row tuple, since)
    held: dict[str, float] = field(default_factory=dict)  # object -> when it left the table
    held_cued: set = field(default_factory=set)
    wrong_since: dict[int, float] = field(default_factory=dict)  # spot -> since when wrong after a placement
    wrong_cued: set = field(default_factory=set)
    done: bool = False

    def __post_init__(self) -> None:
        self.last_activity = self.t0

    # -------------------------------------------------------------- feeding

    def feed(self, reading: dict, t: float) -> list[Event]:
        """`reading`: {'order': [3 names or None], 'seen': [names], 'hands': bool} in game names."""
        if self.done:
            return []
        events: list[Event] = []
        order, seen, hands = reading.get("order"), reading.get("seen") or [], bool(reading.get("hands"))
        if hands:
            self.last_activity = t
            self.candidate = None
        # Lifted: a keyring that was on the table is gone while a hand is there.
        for o in self.row:
            if o not in seen and o not in self.held and (hands or len(seen) == len(self.row) - 1):
                self.held[o] = t
                self.last_activity = t
                events.append(Event("lifted", obj=o))
        if order and all(order) and not hands:
            key = tuple(order)
            if self.candidate is None or self.candidate[0] != key:
                self.candidate = (key, t)
            elif t - self.candidate[1] >= SETTLE_S and list(key) != self.row:
                events += self._settle(list(key), t)
            elif t - self.candidate[1] >= SETTLE_S:
                self.held.clear()  # same row as before: whatever was lifted went back
        events += self._timers(t, hands)
        return events

    def _settle(self, new: list[str], t: float) -> list[Event]:
        events = []
        for i, o in enumerate(new):
            if self.row[i] != o:  # this object arrived in spot i
                right = self.original[i] == o
                events.append(Event("placed", obj=o, spot=i, right=right))
                if right:
                    self.wrong_since.pop(i, None)
                else:
                    self.wrong_since[i] = t
        for i in list(self.wrong_since):
            if new[i] == self.original[i]:
                self.wrong_since.pop(i)
        self.row = new
        self.held.clear()
        self.last_activity = t
        self.hesitation = 0
        if new == self.original:
            self.done = True
            events.append(Event("complete"))
        return events

    def _timers(self, t: float, hands: bool) -> list[Event]:
        if hands or self.done or t - self.last_cue < MIN_GAP_S:
            return []
        for i, since in sorted(self.wrong_since.items()):
            if i not in self.wrong_cued and t - since >= WRONG_GRACE_S:
                self.wrong_cued.add(i)
                return [self._cue(Event("wrong_stays", obj=self.row[i], spot=i), t)]
        for o, since in self.held.items():
            if o not in self.held_cued and t - since >= HOLD_CUE_S:
                self.held_cued.add(o)
                return [self._cue(Event("holding", obj=o), t)]
        idle = t - self.last_activity
        for level, after in enumerate(HESITATE_S, 1):
            if idle >= after and self.hesitation < level and (level == len(HESITATE_S) or idle < HESITATE_S[level]):
                self.hesitation = level
                return [self._cue(Event("hesitate", level=level), t)]
        return []

    def _cue(self, e: Event, t: float) -> Event:
        self.last_cue = t
        return e
