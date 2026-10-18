"""Camera-guided picks for the scripted shuffles.

Calibration (start layout on the table): the side camera records where each slot's keyring sits
in the image (x as a fraction of the width). Slots 1-3 only: slot 4 is outside the camera's view.

Before each pick, the camera finds the keyring that should be in that slot. If it sits off its
calibrated spot, the robot turns its base (shoulder_pan) by the matching amount, using a straight
line fitted through the taught down-pose pans of slots 1-3 against their image x. The correction
is capped at MAX_CORRECTION_DEG so a bad camera reading can never swing the arm far."""

from __future__ import annotations

import os

MAX_CORRECTION_DEG = float(os.getenv("PICK_MAX_CORRECTION_DEG", "3"))
# A keyring cut off by the image edge has a biased centre: no correction there (first arm test:
# the purple block at x~0.10 read 6 deg off and the pick missed).
EDGE = float(os.getenv("PICK_EDGE_MARGIN", "0.15"))
MIN_SHIFT = float(os.getenv("PICK_MIN_SHIFT", "0.01"))  # ignore image shifts under 1% of the width


def fit(ref_x: dict[int, float], pans: dict[int, float]) -> tuple[float, float]:
    """Least-squares line pan = slope * x + intercept through the calibrated slots."""
    slots = [s for s in ref_x if s in pans]
    if len(slots) < 2:
        raise ValueError("need at least two calibrated slots")
    xs = [ref_x[s] for s in slots]
    ys = [pans[s] for s in slots]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        raise ValueError("calibrated slots must be at different image positions")
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return slope, my - slope * mx


def pan_correction(x_seen: float, slot: int, ref_x: dict[int, float], slope: float) -> float:
    """Degrees to add to the slot's taught pan so the gripper lines up with what the camera sees."""
    if slot not in ref_x or not (EDGE <= x_seen <= 1 - EDGE) or not (EDGE <= ref_x[slot] <= 1 - EDGE):
        return 0.0
    dx = x_seen - ref_x[slot]
    if abs(dx) < MIN_SHIFT:
        return 0.0
    c = slope * dx
    return max(-MAX_CORRECTION_DEG, min(MAX_CORRECTION_DEG, c))


def load_calibration(poses_data: dict) -> dict[int, float]:
    return {int(k): float(v) for k, v in (poses_data.get("camera_x") or {}).items()}
