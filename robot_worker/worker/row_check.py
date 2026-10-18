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
    "black": [((0, 0, 0), (179, 255, 55))],
    "white": [((18, 22, 85), (36, 90, 200))],
    "purple": [((108, 25, 50), (145, 255, 230))],
}
MIN_AREA = 250  # pixels at 640 px wide
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
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    out: dict[str, tuple[float, int, float]] = {}
    for name, ranges in RANGES.items():
        m = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            m |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=2)
        n, _, stats, cents = cv2.connectedComponentsWithStats(m)
        if n <= 1:
            continue
        best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        area = int(stats[best, cv2.CC_STAT_AREA])
        if area >= MIN_AREA:
            out[name] = (float(cents[best][0]) / 640, area, float(cents[best][1]) / img.shape[0])
    return out


def read_row(frame_bgr: np.ndarray) -> dict:
    """{'order': [slot1, slot2, slot3] with None where unknown, 'visible': n}."""
    found = find(frame_bgr)
    ranked = sorted(found, key=lambda o: found[o][0], reverse=MIRRORED)  # slot 1 first
    if len(ranked) == 3:
        order: list[str | None] = ranked
    else:
        order = [None, None, None]  # two objects alone can't be pinned to slots
    return {"order": order, "visible": len(ranked), "seen": ranked}
