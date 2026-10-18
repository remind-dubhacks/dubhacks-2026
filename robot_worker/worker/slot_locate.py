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


# ---------------------------------------------------------------- is each keyring on its spot?

TOL_X = float(os.getenv("SPOT_TOL_X", "0.03"))  # share of the image width (~1 cm on the table)
TOL_Y = float(os.getenv("SPOT_TOL_Y", "0.05"))
NAMES_VI = {"black": "đen", "white": "trắng", "purple": "tím"}


def spot_problems(found_xy: dict[str, tuple[float, float]], row: list[str | None],
                  ref_xy: dict[int, tuple[float, float]]) -> list[dict]:
    """Keyrings that sit too far from the spot the robot grabs at, with a plain hint which way to
    nudge them. Slot 1 is the left end; the camera faces the robot, so the image is mirrored and
    things lower in the image are further from the robot."""
    out = []
    for slot, obj in enumerate(row[:3], 1):
        if obj is None or slot not in ref_xy or obj not in found_xy:
            continue
        x, y = found_xy[obj]
        rx, ry = ref_xy[slot]
        dx, dy = x - rx, y - ry
        if abs(dx) <= TOL_X and abs(dy) <= TOL_Y:
            continue
        hint_en, hint_vi = [], []
        if dx > TOL_X:
            hint_en.append("toward the right end"); hint_vi.append("sang phải (về phía ô 4)")
        elif dx < -TOL_X:
            hint_en.append("toward the left end"); hint_vi.append("sang trái (về phía ô 1)")
        if dy > TOL_Y:
            hint_en.append("closer to the robot"); hint_vi.append("lại gần robot")
        elif dy < -TOL_Y:
            hint_en.append("a little away from the robot"); hint_vi.append("ra xa robot một chút")
        out.append({"slot": slot, "object": obj, "dx": round(dx, 3), "dy": round(dy, 3),
                    "say": f"Please move the {obj} keyring a little " + " and ".join(hint_en) + ".",
                    "sayVi": f"Đẩy móc khóa {NAMES_VI.get(obj, obj)} " + " và ".join(hint_vi) + "."})
    return out


def load_spots(poses_data: dict) -> dict[int, tuple[float, float]]:
    return {int(k): (float(v[0]), float(v[1])) for k, v in (poses_data.get("camera_xy") or {}).items()}
