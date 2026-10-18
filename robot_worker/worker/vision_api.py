"""Vision endpoints for Robot Studio: live annotated detection stream, teach, library, memory.

Cameras are shared with LeRobot, so the live stream only runs while teleop/recording is idle,
and it is ended by studio.release_cameras() before LeRobot starts (same as camera previews)."""

import base64
import threading
import time

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import studio
from .vision import Library, Memory, annotate, prepare, recognize

router = APIRouter(prefix="/studio/vision")
library = Library()
memory = Memory()

# Latest frame + detections per camera, written by the live stream.
latest: dict[int, dict] = {}
latest_lock = threading.Lock()


def _busy() -> None:
    if studio.proc.running:
        raise HTTPException(409, f"cameras are in use by {studio.proc.kind}; stop it to use detection")


@router.get("/stream/{index}.mjpg")
def stream(index: int, fps: float = 8.0):
    _busy()
    studio.live.release()

    def frames():
        gen = studio._preview_gen
        cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        studio._preview_clients += 1
        try:
            while cap.isOpened() and not studio.proc.running and gen == studio._preview_gen:
                ok, raw = cap.read()
                if not ok:
                    break
                frame = prepare(raw)
                blobs = recognize(frame, library)
                h, w = frame.shape[:2]
                dets = [b.to_dict(w, h) for b in blobs]
                memory.observe(index, dets)
                with latest_lock:
                    latest[index] = {"frame": frame, "detections": dets, "t": time.time()}
                ok, jpg = cv2.imencode(".jpg", annotate(frame, blobs), [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
                time.sleep(1 / fps)
        finally:
            studio._preview_clients -= 1
            cap.release()
            with latest_lock:
                latest.pop(index, None)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.get("/detections")
def detections(camera: int) -> dict:
    with latest_lock:
        cur = latest.get(camera)
    if not cur:
        raise HTTPException(404, "no live detection stream for that camera; open it first")
    return {"camera": camera, "age": round(time.time() - cur["t"], 2), "detections": cur["detections"]}


class TeachIn(BaseModel):
    camera: int
    name: str
    bbox: list[float] | None = None  # normalized [x, y, w, h]; omit to teach the largest colored object


@router.post("/teach")
def teach(body: TeachIn) -> dict:
    with latest_lock:
        cur = latest.get(body.camera)
    if not cur or time.time() - cur["t"] > 3:
        raise HTTPException(409, "open the live detection view for that camera first")
    frame = cur["frame"]
    h, w = frame.shape[:2]
    mask = None
    if body.bbox:
        x, y, bw, bh = body.bbox
        bbox = (int(x * w), int(y * h), max(1, int(bw * w)), max(1, int(bh * h)))
    else:
        from .vision import detect_colors

        blobs = [b for b in detect_colors(frame) if b.color != "white"] or detect_colors(frame)
        if not blobs:
            raise HTTPException(422, "no colored object found; draw a box around it")
        bbox, mask = blobs[0].bbox, blobs[0].mask
    try:
        return library.teach(body.name, frame, bbox, mask)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/library")
def get_library() -> list[dict]:
    return library.names()


@router.delete("/library/{name}")
def forget(name: str) -> dict:
    return {"removed": library.forget(name)}


@router.get("/library/{name}/thumb.jpg")
def thumb(name: str):
    path = library.thumb(name)
    if not path or not path.exists():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/memory")
def get_memory() -> list[dict]:
    return memory.snapshot()


@router.delete("/memory")
def clear_memory() -> dict:
    memory.clear()
    return {"cleared": True}


class ImageIn(BaseModel):
    imageB64: str


@router.post("/detect-image")
def detect_image(body: ImageIn) -> dict:
    """Detect in a still image (JPEG/PNG base64). For backend vision (read_order) and tests."""
    try:
        data = np.frombuffer(base64.b64decode(body.imageB64.split(",")[-1]), np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"bad image: {e}")
    if frame is None:
        raise HTTPException(422, "could not decode image")
    frame = prepare(frame)
    h, w = frame.shape[:2]
    return {"detections": [b.to_dict(w, h) for b in recognize(frame, library)]}


# ---------------------------------------------------------------- memory game: table row + hands

side_cam = None


robot_frame = None  # set by main: the robot's own side camera, when the executor holds it


def side_frame() -> tuple[np.ndarray | None, str]:
    """Freshest side-camera frame from whatever already has the camera open."""
    import os

    from .table_view import SideCamera

    global side_cam
    if robot_frame is not None:
        try:
            f = robot_frame()
            if f is not None:
                return f, "robot-camera"
        except Exception:  # noqa: BLE001
            pass
    index = int(os.getenv("SIDE_CAMERA_INDEX", "0"))
    with latest_lock:
        cur = latest.get(index)
    if cur and time.time() - cur["t"] < 1.5:
        return cur["frame"], "detection-stream"
    if studio.proc.running:
        return None, "busy"
    if side_cam is None:
        side_cam = SideCamera(index)
    studio.live.release()
    frame, age = side_cam.latest()
    return (frame, "side-camera") if frame is not None and age < 1.5 else (None, "no-frame")


@router.get("/row")
def row() -> dict:
    """Keyring order (slot 1 first, using black/white/purple) and whether a hand is on the table.
    `order` is all None unless all three keyrings are seen: the game then says 'unsure', never guesses."""
    from .table_view import look

    frame, source = side_frame()
    if frame is None:
        raise HTTPException(503, f"no side-camera frame ({source})")
    return {**look(frame), "source": source, "t": time.time()}


@router.get("/side.jpg")
def side_jpg():
    """One side-camera snapshot (for checking the table layout)."""
    from fastapi.responses import Response

    frame, source = side_frame()
    if frame is None:
        raise HTTPException(503, f"no side-camera frame ({source})")
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(jpg.tobytes(), media_type="image/jpeg")


class CalibrateIn(BaseModel):
    start: list[str] = ["black", "white", "purple"]


@router.post("/calibrate-slots")
def calibrate_slots(body: CalibrateIn) -> dict:
    """With the row in its start layout, save where slots 1-3 appear in the side camera.
    The scripted shuffles use it to line up each pick with where the keyring really is."""
    from .robot import load_poses, save_poses
    from .row_check import find, find_xy, read_row

    frame, source = side_frame()
    if frame is None:
        raise HTTPException(503, f"no side-camera frame ({source})")
    row = read_row(frame)
    if row["order"] != body.start:
        raise HTTPException(409, f"camera sees {row['seen']} (order {row['order']}); set the row to {body.start} first")
    found = find(frame)
    cal = {str(i + 1): round(found[o][0], 4) for i, o in enumerate(body.start)}
    xy = find_xy(frame)
    spots = {str(i + 1): [round(xy[o][0], 4), round(xy[o][1], 4)] for i, o in enumerate(body.start)}
    data = load_poses()
    data["camera_x"] = cal
    data["camera_xy"] = spots
    save_poses(data)
    return {"camera_x": cal, "camera_xy": spots, "source": source}
