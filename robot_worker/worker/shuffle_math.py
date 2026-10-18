"""The shuffle skills as math: what each one must do to the row, checked move by move.

The row has 4 slots; slots 1-3 hold the three keyrings and slot 4 (right end) is a parking spot
that must be empty before and after every shuffle. A shuffle is a list of (from_slot, to_slot)
moves, each picking from an occupied slot and placing into an empty one. Its result is a
permutation of slots 1-3, which is what the memory game needs to know to score the patient."""

from __future__ import annotations

from dataclasses import dataclass

SLOTS = 4
PARK = 4


@dataclass(frozen=True)
class Shuffle:
    id: str
    instruction: str  # exactly what the policy was trained on
    moves: tuple[tuple[int, int], ...]  # 1-based slots, in order


SHUFFLES: dict[str, Shuffle] = {
    s.id: s
    for s in [
        Shuffle("swap_lr", "swap the left and right objects", ((1, 4), (3, 1), (4, 3))),
        Shuffle("swap_lm", "swap the left and middle objects", ((1, 4), (2, 1), (4, 2))),
        Shuffle("swap_mr", "swap the middle and right objects", ((2, 4), (3, 2), (4, 3))),
        Shuffle("rot_left", "rotate the objects one spot to the left", ((1, 4), (2, 1), (3, 2), (4, 3))),
        Shuffle("rot_right", "rotate the objects one spot to the right", ((3, 4), (2, 3), (1, 2), (4, 1))),
    ]
}


def allowlist() -> dict[tuple[str, str], dict]:
    """Worker job allowlist entries, one per shuffle. ROBOT_SHUFFLES (comma list) limits them to the
    shuffles verified on the arm, e.g. ROBOT_SHUFFLES=swap_lr,swap_lm for the demo."""
    import os

    only = {x.strip() for x in os.getenv("ROBOT_SHUFFLES", "").split(",") if x.strip()}
    return {("shuffle", s.id): {"instruction": s.instruction, "shuffle": s.id}
            for s in SHUFFLES.values() if not only or s.id in only}


# Scripted fallback (no Perceptron needed): each move is a pick and a place through taught poses.
# Poses: home, above_s1..above_s4, down_s1..down_s4 (teach with: scripts/arm.py teach ...).
import os as _os  # noqa: E402

# Wider than the demos (~36-40): a keyring that shifted ~1 cm on release at slot 4 was still missed at 38.
GRIP_OPEN = float(_os.getenv("SCRIPT_GRIP_OPEN", "55"))
GRIP_CLOSE = float(_os.getenv("SCRIPT_GRIP_CLOSE", "12"))
GRIP_RELEASE = float(_os.getenv("SCRIPT_GRIP_RELEASE", "26"))  # just past holding (~20): lets go without a flick  # demos closed to ~8; a bit gentler to spare the gripper motor
SCRIPT_POSES = ["home"] + [f"above_s{i}" for i in range(1, SLOTS + 1)] + [f"down_s{i}" for i in range(1, SLOTS + 1)]


def scripted_steps(shuffle_id: str) -> list:
    """The shuffle as run_sequence steps: pose names, {"gripper": v} and {"wait": s}."""
    steps: list = ["home", {"gripper": GRIP_OPEN}]
    for a, b in SHUFFLES[shuffle_id].moves:
        steps += [f"above_s{a}", f"down_s{a}", {"gripper": GRIP_CLOSE}, {"wait": 0.4}, f"above_s{a}",
                  f"above_s{b}", f"down_s{b}", {"gripper": GRIP_OPEN}, {"wait": 0.3}, f"above_s{b}"]
    return steps + ["home"]


class MoveError(ValueError):
    pass


def apply_moves(row: list[str | None], moves) -> list[str | None]:
    """Play the moves on a 4-slot row. Raises MoveError on an impossible move."""
    if len(row) != SLOTS:
        raise MoveError(f"row must have {SLOTS} slots")
    row = list(row)
    for k, (a, b) in enumerate(moves, 1):
        if not (1 <= a <= SLOTS and 1 <= b <= SLOTS) or a == b:
            raise MoveError(f"move {k}: bad slots {a}->{b}")
        if row[a - 1] is None:
            raise MoveError(f"move {k}: slot {a} is empty")
        if row[b - 1] is not None:
            raise MoveError(f"move {k}: slot {b} is taken")
        row[b - 1], row[a - 1] = row[a - 1], None
    return row


def expected_end(start: list[str], shuffle_id: str) -> list[str]:
    """Order of slots 1-3 after the shuffle, for any starting order of three objects."""
    if len(start) != 3 or len(set(start)) != 3:
        raise MoveError("start must be three different objects")
    end = apply_moves([*start, None], SHUFFLES[shuffle_id].moves)
    if end[PARK - 1] is not None:
        raise MoveError(f"{shuffle_id} leaves the parking slot occupied")
    return end[:3]  # type: ignore[return-value]


def permutation(shuffle_id: str) -> tuple[int, int, int]:
    """For each end slot, which start slot its object came from (1-based)."""
    end = expected_end(["a", "b", "c"], shuffle_id)
    return tuple("abc".index(x) + 1 for x in end)  # type: ignore[return-value]


def shuffle_for(start: list[str], end: list[str]) -> str | None:
    """Which shuffle turns `start` into `end`, if any."""
    for sid in SHUFFLES:
        if expected_end(start, sid) == list(end):
            return sid
    return None


def verdict(expected: list[str], observed: list[str | None] | None) -> str:
    """'ok' when every slot matches, 'mismatch' when a seen object is in the wrong slot,
    'unsure' when the camera could not see enough to tell."""
    if not observed or len(observed) != 3:
        return "unsure"
    seen = [(e, o) for e, o in zip(expected, observed) if o is not None]
    if any(e != o for e, o in seen):
        return "mismatch"
    return "ok" if len(seen) == 3 else "unsure"
