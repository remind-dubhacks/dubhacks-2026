"""Synthetic-scene tests for color detection + teach-and-remember (no camera needed)."""

import cv2
import numpy as np

from worker.vision import Library, Memory, detect_colors, prepare, recognize

BLUE, PINK, WHITE, TABLE = (200, 90, 20), (180, 80, 240), (245, 245, 245), (90, 120, 150)  # BGR


def scene(offset=(0, 0), brightness=1.0, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), TABLE, np.uint8)
    dx, dy = offset
    # blue keychain: oval body + ring
    cv2.ellipse(img, (150 + dx, 300 + dy), (40, 25), 20, 0, 360, BLUE, -1)
    cv2.circle(img, (110 + dx, 270 + dy), 14, (120, 120, 120), 3)
    # pink pen: long thin rotated bar with a darker tip
    box = cv2.boxPoints(((380 + dx, 200 + dy), (170, 18), -25)).astype(np.int32)
    cv2.fillPoly(img, [box], PINK)
    cv2.circle(img, (455 + dx, 165 + dy), 6, (40, 40, 40), -1)
    # white keycap keyring: rounded square + letter
    cv2.rectangle(img, (480 + dx, 330 + dy), (530 + dx, 380 + dy), WHITE, -1)
    cv2.putText(img, "A", (493 + dx, 368 + dy), cv2.FONT_HERSHEY_SIMPLEX, 1, (60, 60, 60), 2)
    img = np.clip(img.astype(np.float32) * brightness + rng.normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    return prepare(img)


def blob_of(blobs, color):
    return max((b for b in blobs if b.color == color), key=lambda b: b.area)


def test_detects_the_three_colors():
    colors = {b.color for b in detect_colors(scene())}
    assert {"blue", "pink", "white"} <= colors


def test_teach_then_recognize_after_moving(tmp_path):
    lib = Library(tmp_path)
    first = scene()
    blobs = detect_colors(first)
    for color, name in (("blue", "blue keychain"), ("pink", "pink pen"), ("white", "white keycap")):
        b = blob_of(blobs, color)
        lib.teach(name, first, b.bbox, b.mask)

    moved = scene(offset=(40, 30), brightness=0.9, seed=1)
    names = {b.name: b for b in recognize(moved, lib) if b.name}
    assert set(names) == {"blue keychain", "pink pen", "white keycap"}
    assert names["pink pen"].color == "pink"
    assert all(b.score >= 0.55 for b in names.values())

    # Library survives a reload from disk.
    assert {n["name"] for n in Library(tmp_path).names()} == {"blue keychain", "pink pen", "white keycap"}


def test_unknown_object_is_not_labelled(tmp_path):
    lib = Library(tmp_path)
    first = scene()
    b = blob_of(detect_colors(first), "blue")
    lib.teach("blue keychain", first, b.bbox, b.mask)
    img = np.full((480, 640, 3), TABLE, np.uint8)
    cv2.circle(img, (300, 240), 40, (40, 200, 40), -1)  # a green thing we never taught
    labelled = [x for x in recognize(prepare(img), lib) if x.name]
    assert labelled == []


def test_memory_remembers_where(tmp_path):
    mem = Memory(tmp_path / "m.json")
    mem.observe(0, [{"name": "pink pen", "center": [0.2, 0.5], "where": "left", "color": "pink", "score": 0.8}])
    snap = mem.snapshot()
    assert snap[0]["name"] == "pink pen" and snap[0]["where"] == "left"
    mem.save()
    assert Memory(tmp_path / "m.json").snapshot()[0]["camera"] == 0
