"""The 5 robot shuffle skills, as the game sees them. Mirrors robot_worker/worker/shuffle_math.py
(a test checks the two agree). `pattern[i]` is the start spot (0-based) of the object that ends up
in spot i, the same convention as OrderMemory.shuffle()."""

from __future__ import annotations

# shuffle id -> pattern
SHUFFLES: dict[str, tuple[int, int, int]] = {
    "swap_lr": (2, 1, 0),
    "swap_lm": (1, 0, 2),
    "swap_mr": (0, 2, 1),
    "rot_left": (1, 2, 0),
    "rot_right": (2, 0, 1),
}
BY_PATTERN = {p: sid for sid, p in SHUFFLES.items()}

# The trained skill only ever saw this start layout (docs/RECORDING_SETUP.md).
ROBOT_START = ["black keycap", "white keycap", "purple keycap"]
# Camera colour names (robot worker row endpoint) -> game object names.
CAMERA_NAMES = {"black": "black keycap", "white": "white keycap", "purple": "purple keycap"}


def shuffle_id(pattern: tuple[int, ...]) -> str | None:
    return BY_PATTERN.get(tuple(pattern))


def fix_for(current: list[str], target: list[str]) -> str | None:
    """Which single robot shuffle turns `current` into `target` (None if already equal or not a
    3-object permutation)."""
    if len(current) != 3 or sorted(current) != sorted(target) or current == target:
        return None
    pattern = tuple(current.index(o) for o in target)
    return shuffle_id(pattern)


def allowed() -> set[str]:
    """Shuffles the robot may run: ROBOT_SHUFFLES (comma list, the ones verified on the arm), else all."""
    import os

    only = {x.strip() for x in os.getenv("ROBOT_SHUFFLES", "").split(",") if x.strip()}
    return (only & set(SHUFFLES)) or set(SHUFFLES)


def to_camera(row: list[str]) -> list[str]:
    """Game object names -> the robot worker's colour names."""
    back = {v: k for k, v in CAMERA_NAMES.items()}
    return [back[o] for o in row]
