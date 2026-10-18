"""Read the keyring row from one side-camera frame.

Tuned on the 60 recorded shuffle episodes: black keycap (very dark), white keycap (cream, a little
warmer than the white table) and the purple switch block. The side camera faces the arm, so the
image is mirrored: image right is slot 1. Only the order of the objects is used, never pixel
positions, so a slightly moved camera still works.

The camera does not always see the whole row (slot 3 can sit off the left edge). If only two
keyrings are visible we report the order of those two and leave the third unknown, which makes
the verdict 'unsure' instead of guessing."""

from __future__ import annotations

import os

import cv2
import numpy as np

RANGES: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    # Wide enough for the camera's auto white balance (cream keycap read H 18-54, purple H 102-145).
    "black": [((0, 0, 0), (179, 255, 72))],
    "white": [((15, 15, 70), (65, 95, 215))],
    "purple": [((95, 25, 50), (150, 255, 235))],
}
MIN_AREA = 250  # pixels at 640 px wide
UNION = {"purple"}
SHAPED = {"black", "white"}  # keycaps: compact, roughly square blobs
MAX_AREA = int(os.getenv("KEYRING_MAX_AREA", "9000"))  # px at 640 wide (a keycap is ~1500-4000)
TOP_IGNORE = float(os.getenv("ROW_TOP_IGNORE", "0.09"))
MIRRORED = os.getenv("SIDE_CAMERA_MIRRORED", "1") == "1"


def find_xy(frame_bgr: np.ndarray) -> dict[str, tuple[float, float]]:
    """object -> (x, y) of its centre as 0-1 fractions of the frame (y grows toward the camera)."""
    return {k: (v[0], v[2]) for k, v in _find(frame_bgr).items()}


def find(frame_bgr: np.ndarray) -> dict[str, tuple[float, int]]:
    return {k: (v[0], v[1]) for k, v in _find(frame_bgr).items()}


def _find(frame_bgr: np.ndarray) -> dict[str, tuple[float, int, float]]:
    """object -> (x center as a 0-1 fraction of width, area in px) for each object found."""
    h, w = frame_bgr.shape[:2]
    img = cv2.resize(frame_bgr, (640, int(h * 640 / w))) if w != 640 else frame_bgr
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    # The table fills most of the frame: drop pixels close to its median colour so a white or wood
    # tabletop is never mistaken for a keycap.
    med = np.median(hsv.reshape(-1, 3), axis=0)
    table = (np.abs(hsv[..., 1].astype(np.int16) - int(med[1])) <= 12) & (np.abs(hsv[..., 2].astype(np.int16) - int(med[2])) <= 30)
    hsv[table] = (60, 255, 255)  # pure green: outside every keyring range
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    out: dict[str, tuple[float, int, float]] = {}
    # Where the purple block is (dilated): its pale, bluish sides must never count as the white keycap.
    pm = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in RANGES["purple"]:
        pm |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    pm = cv2.dilate(cv2.morphologyEx(pm, cv2.MORPH_OPEN, k), np.ones((25, 25), np.uint8))
    for name, ranges in RANGES.items():
        m = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            m |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=2)
        n, _, stats, cents = cv2.connectedComponentsWithStats(m)
        if n <= 1:
            continue
        H = img.shape[0]
        # Keyring-shaped blobs only: not too big, roughly square, not along the top edge (robot base,
        # cables and the arm itself are dark too).
        ok = [i for i in range(1, n)
              if stats[i, cv2.CC_STAT_AREA] <= MAX_AREA
              and 0.4 <= stats[i, cv2.CC_STAT_WIDTH] / max(1, stats[i, cv2.CC_STAT_HEIGHT]) <= 2.5
              and cents[i][1] >= TOP_IGNORE * H
              # solid like a keycap, not a thin cable loop
              and stats[i, cv2.CC_STAT_AREA] >= 0.45 * stats[i, cv2.CC_STAT_WIDTH] * stats[i, cv2.CC_STAT_HEIGHT]
              # sleeves and hands reach in from the right and bottom edges
              and stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] < img.shape[1] - 2
              and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < H - 2
              and (name != "white" or not pm[int(cents[i][1]), int(cents[i][0])])
              ] if name in SHAPED else [
                  # the purple block: anything reaching the right or bottom edge is a sleeve or a hand (on the white
                  # table the block itself can sit cut off at the left edge)
                  i for i in range(1, n)
                  if stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < H - 2
                  and stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] < img.shape[1] - 2]
        if not ok:
            continue
        best = max(ok, key=lambda i: stats[i, cv2.CC_STAT_AREA])
        area = int(stats[best, cv2.CC_STAT_AREA])
        if area < MIN_AREA:
            continue
        cx, cy = float(cents[best][0]), float(cents[best][1])
        if name in UNION:
            # The translucent purple block shows up as several patches that change frame to frame;
            # the centre of all its patches near the biggest one is far steadier than any one patch.
            keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 40
                    and abs(cents[i][0] - cx) < 90 and abs(cents[i][1] - cy) < 160]
            wsum = sum(stats[i, cv2.CC_STAT_AREA] for i in keep)
            cx = float(sum(cents[i][0] * stats[i, cv2.CC_STAT_AREA] for i in keep) / wsum)
            cy = float(sum(cents[i][1] * stats[i, cv2.CC_STAT_AREA] for i in keep) / wsum)
            area = int(wsum)
        out[name] = (cx / 640, area, cy / img.shape[0])
    if "white" not in out and "black" in out and "purple" in out:
        w = _white_by_edges(img, out)
        if w:
            out["white"] = w
    return out


def _white_by_edges(img: np.ndarray, out: dict) -> tuple[float, int, float] | None:
    """On a table the same colour as the cream keycap, find it by shape: a keycap and its clear base
    make a dense patch of edges; the tabletop doesn't. Must sit on the row the black and purple
    keyrings define and not on top of either of them."""
    H, W = img.shape[:2]
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    e = cv2.Canny(g, 40, 120)
    e = cv2.morphologyEx(cv2.dilate(e, np.ones((5, 5), np.uint8)), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, st, ce = cv2.connectedComponentsWithStats(e)
    row_y = (out["black"][2] + out["purple"][2]) / 2 * H
    taken = [(out[k][0] * W, out[k][2] * H) for k in ("black", "purple")]
    best = None
    for i in range(1, n):
        a = int(st[i, cv2.CC_STAT_AREA]); x, y = ce[i]
        if a < 400 or a > MAX_AREA * 1.5 or abs(y - row_y) > 0.12 * H:
            continue
        if any(abs(x - tx) < 45 for tx, _ in taken):
            continue
        if best is None or a > best[1]:
            best = (float(x) / W, a, float(y) / H)
    return best


def read_row(frame_bgr: np.ndarray) -> dict:
    """{'order': [slot1, slot2, slot3] with None where unknown, 'visible': n}."""
    found = find(frame_bgr)
    ranked = sorted(found, key=lambda o: found[o][0], reverse=MIRRORED)  # slot 1 first
    if len(ranked) == 3:
        order: list[str | None] = ranked
    else:
        order = [None, None, None]  # two objects alone can't be pinned to slots
    return {"order": order, "visible": len(ranked), "seen": ranked}
