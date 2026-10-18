"""Camera-guided picks for the scripted shuffles.

Calibration (start layout on the table): the side camera records where each slot's keyring sits
in the image (x as a fraction of the width). Slots 1-3 only: slot 4 is outside the camera's view.

Before each pick, the camera finds the keyring that should be in that slot. If it sits off its
calibrated spot, the robot turns its base (shoulder_pan) by the matching amount, using a straight
line fitted through the taught down-pose pans of slots 1-3 against their image x. The correction
is capped at MAX_CORRECTION_DEG so a bad camera reading can never swing the arm far."""

from __future__ import annotations

import os

MAX_CORRECTION_DEG = float(os.getenv("PICK_MAX_CORRECTION_DEG", "6"))  # 1.3-3 deg corrections all picked fine
# A keyring cut off by the image edge has a biased centre: no correction there (first arm test:
# the purple block at x~0.10 read 6 deg off and the pick missed).
EDGE = float(os.getenv("PICK_EDGE_MARGIN", "0.08"))
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

# The open gripper (~4 cm) takes a keycap (~2 cm) up to ~1.5 cm off centre: 0.05 of the image width.
# A pick missed at 0.07 off. The long purple block's centre varies more with how it is set down.
# With camera pick correction on (up to 3 deg, ~0.055 of the width) only bigger offsets need a nudge.
TOL_X = float(os.getenv("SPOT_TOL_X", "0.13"))  # beyond the 6 deg the pick correction can cover
# Off by default: the slots sit at different depths in the side view, so a keyring's image height
# depends on the slot as well as its shape, and robot-placed keyrings were flagged. 1.0 = no y check.
TOL_Y = float(os.getenv("SPOT_TOL_Y", "1.0"))
# The purple block's centre moves with where the gripper held it, even when the robot set it down
# itself, so it is not spot-checked (pick correction and the grasp check still apply).
LOOSER = {"purple": float("inf")}
NAMES_VI = {"black": "đen", "white": "trắng", "purple": "tím"}


CAL_START = ["black", "white", "purple"]


def object_offsets(ref_xy: dict[int, tuple[float, float]], cal_start: list[str] = CAL_START) -> dict[str, tuple[float, float]]:
    """How far each keyring's detected centre sits from a keycap's in the same spot. The purple
    switch block is long, so its centre is much lower in the image; the two keycaps match."""
    caps = [s for s, o in enumerate(cal_start, 1) if o in ("black", "white") and s in ref_xy]
    if not caps:
        return {}
    base_y = sum(ref_xy[s][1] for s in caps) / len(caps)
    out = {o: (0.0, 0.0) for o in ("black", "white")}
    for s, o in enumerate(cal_start, 1):
        if o not in out and s in ref_xy:
            out[o] = (0.0, ref_xy[s][1] - base_y)
    return out


def slot_spot(slot: int, obj: str, ref_xy: dict[int, tuple[float, float]], cal_start: list[str] = CAL_START) -> tuple[float, float]:
    """Where `obj` should appear when it sits on `slot`'s grab spot."""
    offs = object_offsets(ref_xy, cal_start)
    cal_obj = cal_start[slot - 1]
    rx, ry = ref_xy[slot]
    ry -= offs.get(cal_obj, (0.0, 0.0))[1]  # the slot's spot for a keycap
    return rx, ry + offs.get(obj, (0.0, 0.0))[1]


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
        rx, ry = slot_spot(slot, obj, ref_xy)
        dx, dy = x - rx, y - ry
        tx, ty = TOL_X * LOOSER.get(obj, 1), TOL_Y * LOOSER.get(obj, 1)
        if abs(dx) <= tx and abs(dy) <= ty:
            continue
        hint_en, hint_vi = [], []
        if dx > tx:
            hint_en.append("toward the right end"); hint_vi.append("sang phải (về phía ô 4)")
        elif dx < -tx:
            hint_en.append("toward the left end"); hint_vi.append("sang trái (về phía ô 1)")
        if dy > ty:
            hint_en.append("closer to the robot"); hint_vi.append("lại gần robot")
        elif dy < -ty:
            hint_en.append("a little away from the robot"); hint_vi.append("ra xa robot một chút")
        out.append({"slot": slot, "object": obj, "dx": round(dx, 3), "dy": round(dy, 3),
                    "say": f"Please move the {obj} keyring a little " + " and ".join(hint_en) + ".",
                    "sayVi": f"Đẩy móc khóa {NAMES_VI.get(obj, obj)} " + " và ".join(hint_vi) + "."})
    return out


def load_spots(poses_data: dict) -> dict[int, tuple[float, float]]:
    return {int(k): (float(v[0]), float(v[1])) for k, v in (poses_data.get("camera_xy") or {}).items()}


# ---------------------------------------------------------------- per-keyring pick correction

CAL_OBJECTS = {1: "black", 2: "white", 3: "purple", 4: "black"}  # what sat on each slot at calibration


def pick_correction(x_seen: float, slot: int, obj: str, ref_x: dict[int, float], pans: dict[int, float],
                    cal_objects: dict[int, str] = CAL_OBJECTS) -> float:
    """Degrees of shoulder_pan to add so the gripper lines up with `obj` as the camera sees it.

    Fits image x against the taught pans using only slots calibrated with a keycap (their centre is
    the gripper's centre), then estimates how far the purple block's image centre sits from a
    keycap's on the same spot. The expected x for `obj` on `slot` is the slot's keycap x plus that
    object's offset; the correction turns the remaining gap into degrees, capped and skipped near
    the image edge."""
    caps = [s for s in ref_x if cal_objects.get(s) in ("black", "white") and s in pans]
    if len(caps) < 2 or slot not in ref_x or slot not in pans:
        return 0.0
    if not (EDGE <= x_seen <= 1 - EDGE):
        return 0.0
    slope, icpt = fit({s: pans[s] for s in caps}, {s: ref_x[s] for s in caps})  # x = slope * pan + icpt
    if slope == 0:
        return 0.0
    offs = {"black": 0.0, "white": 0.0}
    for s, o in cal_objects.items():
        if o not in offs and s in ref_x and s in pans:
            offs[o] = ref_x[s] - (slope * pans[s] + icpt)
    keycap_x = ref_x[slot] - offs.get(cal_objects.get(slot, "black"), 0.0)
    dx = x_seen - (keycap_x + offs.get(obj, 0.0))
    if abs(dx) < MIN_SHIFT:
        return 0.0
    c = dx / slope  # degrees of pan per unit of image x
    return max(-MAX_CORRECTION_DEG, min(MAX_CORRECTION_DEG, c))
