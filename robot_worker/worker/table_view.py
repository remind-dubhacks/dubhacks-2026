"""What the side camera says about the table right now: the keyring row and whether a hand is in
the workspace. Used by the memory game (live restore watching) and by the robot itself (it pauses
while a hand is on the table).

Hands are found by skin colour (YCrCb plus an HSV guard). On the 121 recorded side-camera frames,
none of which show a hand, the detector found no skin at all (max 0.02% of the frame).
Skin tones vary, so check it once with a real hand before relying on it, and keep the physical
emergency stop as the primary control."""

from __future__ import annotations

import os
import threading
import time

import cv2
import numpy as np

from .row_check import read_row

HAND_MIN_FRAC = float(os.getenv("HAND_MIN_FRAC", "0.01"))  # share of the frame that must look like skin


def hand_fraction(frame_bgr: np.ndarray) -> float:
    img = cv2.resize(frame_bgr, (320, int(frame_bgr.shape[0] * 320 / frame_bgr.shape[1])))
    blur = cv2.GaussianBlur(img, (5, 5), 0)
    ycc = cv2.cvtColor(blur, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(ycc, (40, 138, 77), (250, 175, 127)) & cv2.inRange(hsv, (0, 40, 60), (25, 200, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return float(m.mean() / 255)


def hands_in(frame_bgr: np.ndarray) -> bool:
    return hand_fraction(frame_bgr) >= HAND_MIN_FRAC


def look(frame_bgr: np.ndarray) -> dict:
    row = read_row(frame_bgr)
    frac = hand_fraction(frame_bgr)
    return {**row, "hands": frac >= HAND_MIN_FRAC, "handFrac": round(frac, 4)}


class SideCamera:
    """Keeps the side camera open while someone keeps asking for frames; closes it after `idle`
    seconds without a request so LeRobot and the live view can have it back."""

    def __init__(self, index: int, idle: float = 20.0) -> None:
        self.index, self.idle = index, idle
        self.frame: np.ndarray | None = None
        self.t = 0.0
        self.asked = 0.0
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def latest(self, timeout: float = 3.0) -> tuple[np.ndarray | None, float]:
        self.asked = time.time()
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        end = time.time() + timeout
        while time.time() < end:
            if self.frame is not None and time.time() - self.t < 1.0:
                return self.frame, time.time() - self.t
            time.sleep(0.05)
        return self.frame, (time.time() - self.t) if self.frame is not None else float("inf")

    def _run(self) -> None:
        cap = cv2.VideoCapture(self.index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        try:
            while cap.isOpened() and time.time() - self.asked < self.idle:
                ok, f = cap.read()
                if ok:
                    self.frame, self.t = f, time.time()
                time.sleep(0.1)
        finally:
            cap.release()
            self.frame = None
