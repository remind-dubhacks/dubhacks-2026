"""Color detection + teach-and-remember object recognition (OpenCV only, no model download).

- detect_colors(): HSV masks -> colored blobs (bbox, center, area).
- Library: teach an object from a box in a frame; stores an H-S histogram, ORB descriptors,
  dominant color and a thumbnail. Several examples per name make recognition more robust.
- recognize(): labels each blob with the best-matching taught object.
- Memory: when/where each named object was last seen (persisted JSON).

Tuned for small everyday props (blue keychain, pink pen, white keycap keyring). White is
detected only as compact blobs, because tables and walls are often white too."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "vision_library"
MEMORY_FILE = ROOT / "vision_memory.json"

WORK_WIDTH = 640  # frames are resized to this width before processing

# OpenCV HSV: H 0-179, S 0-255, V 0-255. Each color is a list of (lo, hi) ranges.
PALETTE: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    "red": [((0, 120, 70), (7, 255, 255)), ((172, 120, 70), (179, 255, 255))],
    "orange": [((8, 120, 90), (19, 255, 255))],
    "yellow": [((20, 90, 100), (34, 255, 255))],
    "green": [((35, 70, 50), (85, 255, 255))],
    "blue": [((90, 90, 50), (130, 255, 255))],
    "purple": [((131, 60, 50), (147, 255, 255))],
    "pink": [((148, 50, 110), (171, 255, 255)), ((0, 30, 170), (7, 119, 255)), ((172, 30, 170), (179, 119, 255))],
    "white": [((0, 0, 200), (179, 35, 255))],
}
DRAW = {  # BGR for annotations
    "red": (40, 40, 220), "orange": (0, 140, 255), "yellow": (0, 220, 240), "green": (60, 180, 60),
    "blue": (220, 120, 30), "purple": (180, 60, 140), "pink": (180, 105, 255), "white": (230, 230, 230),
}
MIN_AREA_FRAC = 0.0015  # ignore specks
MAX_AREA_FRAC = {"white": 0.08}  # large white regions are background (table, wall, paper)
DEFAULT_MAX_AREA_FRAC = 0.35
MATCH_THRESHOLD = 0.55


@dataclass
class Blob:
    color: str
    bbox: tuple[int, int, int, int]  # x, y, w, h in work-frame pixels
    area: float
    mask: np.ndarray = field(repr=False)
    name: str | None = None
    score: float = 0.0

    def to_dict(self, frame_w: int, frame_h: int) -> dict:
        x, y, w, h = self.bbox
        return {
            "color": self.color,
            "name": self.name,
            "score": round(self.score, 2),
            "bbox": [round(x / frame_w, 4), round(y / frame_h, 4), round(w / frame_w, 4), round(h / frame_h, 4)],
            "center": [round((x + w / 2) / frame_w, 3), round((y + h / 2) / frame_h, 3)],
            "areaFrac": round(self.area / (frame_w * frame_h), 4),
            "where": region((x + w / 2) / frame_w, (y + h / 2) / frame_h),
        }


def region(cx: float, cy: float) -> str:
    horiz = "left" if cx < 0.33 else "right" if cx > 0.67 else "center"
    vert = "top" if cy < 0.33 else "bottom" if cy > 0.67 else "middle"
    return f"{vert} {horiz}" if vert != "middle" else horiz


def prepare(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if w != WORK_WIDTH:
        frame = cv2.resize(frame, (WORK_WIDTH, int(h * WORK_WIDTH / w)), interpolation=cv2.INTER_AREA)
    return frame


def color_mask(hsv: np.ndarray, color: str) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in PALETTE[color]:
        mask |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)


def detect_colors(frame: np.ndarray, colors: list[str] | None = None) -> list[Blob]:
    """frame must already be prepare()d (BGR)."""
    hsv = cv2.cvtColor(cv2.GaussianBlur(frame, (5, 5), 0), cv2.COLOR_BGR2HSV)
    total = frame.shape[0] * frame.shape[1]
    blobs: list[Blob] = []
    for color in colors or list(PALETTE):
        mask = color_mask(hsv, color)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < MIN_AREA_FRAC * total or area > MAX_AREA_FRAC.get(color, DEFAULT_MAX_AREA_FRAC) * total:
                continue
            x, y, w, h = cv2.boundingRect(c)
            blob_mask = np.zeros(mask.shape, np.uint8)
            cv2.drawContours(blob_mask, [c], -1, 255, cv2.FILLED)
            blobs.append(Blob(color, (x, y, w, h), area, blob_mask))
    return sorted(blobs, key=lambda b: -b.area)


# ---------------------------------------------------------------- features

_orb = cv2.ORB_create(nfeatures=300)
_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)


def hs_hist(frame: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mask, [30, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist


def orb_desc(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
    x, y, w, h = bbox
    pad = 6
    crop = frame[max(0, y - pad) : y + h + pad, max(0, x - pad) : x + w + pad]
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if min(gray.shape) < 40:  # ORB needs some pixels; upscale tiny crops
        s = 40 / min(gray.shape)
        gray = cv2.resize(gray, None, fx=s, fy=s)
    _, desc = _orb.detectAndCompute(gray, None)
    return desc


def orb_score(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None or len(a) < 2 or len(b) < 2:
        return 0.0
    good = 0
    for pair in _matcher.knnMatch(a, b, k=2):
        if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
            good += 1
    return min(1.0, good / max(8, min(len(a), len(b)) * 0.3))


def dominant_color(frame: np.ndarray, mask: np.ndarray) -> str | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    best, best_n = None, 0
    for color in PALETTE:
        n = int(cv2.countNonZero(color_mask(hsv, color) & mask))
        if n > best_n:
            best, best_n = color, n
    return best if best_n > 0.15 * max(1, cv2.countNonZero(mask)) else None


# ---------------------------------------------------------------- library


@dataclass
class Example:
    name: str
    color: str | None
    hist: np.ndarray
    desc: np.ndarray | None
    aspect: float
    file: str


class Library:
    def __init__(self, root: Path = LIBRARY_DIR) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.examples: list[Example] = []
        self.load()

    def load(self) -> None:
        self.examples = []
        if not self.root.exists():
            return
        for meta in sorted(self.root.glob("*/*.json")):
            d = json.loads(meta.read_text())
            npz = np.load(meta.with_suffix(".npz"), allow_pickle=False)
            desc = npz["desc"] if "desc" in npz and npz["desc"].size else None
            self.examples.append(Example(d["name"], d.get("color"), npz["hist"], desc, d.get("aspect", 1.0), str(meta.with_suffix(".jpg"))))

    def names(self) -> list[dict]:
        out: dict[str, dict] = {}
        for e in self.examples:
            item = out.setdefault(e.name, {"name": e.name, "examples": 0, "color": e.color, "thumb": Path(e.file).name})
            item["examples"] += 1
        return list(out.values())

    def teach(self, name: str, frame: np.ndarray, bbox: tuple[int, int, int, int], mask: np.ndarray | None = None) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        x, y, w, h = bbox
        if w < 8 or h < 8:
            raise ValueError("box is too small")
        if mask is None:
            # Box drawn by hand: use colored pixels inside it as the object, else the whole box.
            box = np.zeros(frame.shape[:2], np.uint8)
            box[y : y + h, x : x + w] = 255
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            colored = np.zeros_like(box)
            for color in PALETTE:
                colored |= color_mask(hsv, color)
            obj = colored & box
            mask = obj if cv2.countNonZero(obj) > 0.1 * w * h else box
        color = dominant_color(frame, mask)
        hist = hs_hist(frame, mask)
        desc = orb_desc(frame, bbox)
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "object"
        folder = self.root / slug
        folder.mkdir(parents=True, exist_ok=True)
        stem = folder / f"{int(time.time() * 1000)}"
        crop = frame[y : y + h, x : x + w]
        cv2.imwrite(str(stem.with_suffix(".jpg")), crop)
        np.savez(stem.with_suffix(".npz"), hist=hist, desc=desc if desc is not None else np.zeros((0, 32), np.uint8))
        stem.with_suffix(".json").write_text(json.dumps({"name": name, "color": color, "aspect": w / h, "bbox": bbox}))
        with self.lock:
            self.examples.append(Example(name, color, hist, desc, w / h, str(stem.with_suffix(".jpg"))))
        return {"name": name, "color": color, "examples": sum(e.name == name for e in self.examples)}

    def forget(self, name: str) -> int:
        n = 0
        for meta in self.root.glob("*/*.json"):
            if json.loads(meta.read_text())["name"] == name:
                for suffix in (".json", ".npz", ".jpg"):
                    meta.with_suffix(suffix).unlink(missing_ok=True)
                n += 1
        self.load()
        return n

    def thumb(self, name: str) -> Path | None:
        for e in self.examples:
            if e.name == name:
                return Path(e.file)
        return None

    def match(self, frame: np.ndarray, blob: Blob) -> tuple[str | None, float]:
        if not self.examples:
            return None, 0.0
        hist = hs_hist(frame, blob.mask)
        desc = orb_desc(frame, blob.bbox)
        aspect = blob.bbox[2] / max(1, blob.bbox[3])
        best: dict[str, float] = {}
        for e in self.examples:
            h = max(0.0, cv2.compareHist(hist, e.hist, cv2.HISTCMP_CORREL))
            c = 1.0 if e.color == blob.color else 0.0
            o = orb_score(desc, e.desc)
            a = 1.0 - min(1.0, abs(np.log(max(aspect, 1e-3) / max(e.aspect, 1e-3))) / 1.5)
            s = 0.5 * h + 0.25 * c + 0.15 * o + 0.10 * a
            best[e.name] = max(best.get(e.name, 0.0), s)
        name, score = max(best.items(), key=lambda kv: kv[1])
        return (name, score) if score >= MATCH_THRESHOLD else (None, score)


def recognize(frame: np.ndarray, library: Library) -> list[Blob]:
    blobs = detect_colors(frame)
    for b in blobs:
        b.name, b.score = library.match(frame, b)
    # One label per taught object: keep its best-scoring blob.
    best: dict[str, Blob] = {}
    for b in blobs:
        if b.name and (b.name not in best or b.score > best[b.name].score):
            best[b.name] = b
    for b in blobs:
        if b.name and best[b.name] is not b:
            b.name, b.score = None, b.score
    return blobs


# ---------------------------------------------------------------- memory


class Memory:
    def __init__(self, path: Path = MEMORY_FILE) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.items: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
        self._last_save = 0.0

    def observe(self, camera: int, detections: list[dict]) -> None:
        now = time.time()
        with self.lock:
            for d in detections:
                if not d["name"]:
                    continue
                item = self.items.setdefault(d["name"], {"name": d["name"], "firstSeen": now, "timesSeen": 0, "history": []})
                item.update(lastSeen=now, camera=camera, center=d["center"], where=d["where"], color=d["color"], score=d["score"])
                item["timesSeen"] += 1
                hist = item["history"]
                if not hist or now - hist[-1]["t"] > 5:  # sparse trail of positions
                    hist.append({"t": now, "camera": camera, "center": d["center"], "where": d["where"]})
                    del hist[:-20]
            if now - self._last_save > 2:
                self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.items, indent=1))
        self._last_save = time.time()

    def clear(self) -> None:
        with self.lock:
            self.items = {}
            self.save()

    def snapshot(self) -> list[dict]:
        now = time.time()
        with self.lock:
            return sorted(
                ({**{k: v for k, v in i.items() if k != "history"}, "secondsAgo": round(now - i["lastSeen"], 1)} for i in self.items.values()),
                key=lambda i: i["secondsAgo"],
            )


# ---------------------------------------------------------------- drawing


def annotate(frame: np.ndarray, blobs: list[Blob]) -> np.ndarray:
    out = frame.copy()
    for b in blobs:
        x, y, w, h = b.bbox
        col = DRAW.get(b.color, (255, 255, 255))
        thick = 3 if b.name else 1
        cv2.rectangle(out, (x, y), (x + w, y + h), col, thick)
        label = f"{b.name} {b.score:.2f}" if b.name else b.color
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x, max(0, y - th - 6)), (x + tw + 6, y), col, cv2.FILLED)
        cv2.putText(out, label, (x + 3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0) if b.color in ("white", "yellow") else (255, 255, 255), 1, cv2.LINE_AA)
    return out
