"""Robot Studio API: run teleop / recording as LeRobot subprocesses, preview cameras, and push
datasets through the Perceptron pipeline. Mounted on the robot worker at /studio.

Start the worker from Terminal.app (which has camera permission) so the subprocesses inherit it."""

import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Literal

import httpx
from dotenv import set_key
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
CALIB = Path.home() / ".cache/huggingface/lerobot/calibration"
DATA_HOME = Path(os.getenv("HF_LEROBOT_HOME", Path.home() / ".cache/huggingface/lerobot"))
PERCEPTRON = os.getenv("PERCEPTRON_BASE_URL", "https://robotics.perceptron.inc")

router = APIRouter(prefix="/studio")

from . import voice  # noqa: E402
from .liveview import LiveView, display_args  # noqa: E402


# ---------------------------------------------------------------- process manager


class Proc:
    """At most one LeRobot process at a time: they all need the same serial ports and cameras."""

    def __init__(self) -> None:
        self.p: subprocess.Popen | None = None
        self.kind: str | None = None
        self.started: float | None = None
        self.cmd: list[str] = []
        self.logs: deque[tuple[int, str]] = deque(maxlen=2000)
        self.seq = 0
        self.episode: int | None = None
        self.phase: str | None = None
        self.exit_code: int | None = None
        self.stopped_by_user = False
        self.lock = threading.Lock()
        self.plan = {"episodes": 0, "episode_s": 0, "reset_s": 0}
        self._timers: list[threading.Timer] = []

    @property
    def running(self) -> bool:
        return self.p is not None and self.p.poll() is None

    def _after(self, seconds: float, text: str) -> None:
        if seconds > 0:
            t = threading.Timer(seconds, voice.speak, args=(text,))
            t.daemon = True
            t.start()
            self._timers.append(t)

    def _clear_timers(self) -> None:
        for t in self._timers:
            t.cancel()
        self._timers = []

    def log(self, line: str) -> None:
        with self.lock:
            self.seq += 1
            self.logs.append((self.seq, line))
        before = (self.phase, self.episode)
        if m := re.search(r"Recording episode (\d+)", line):
            self.episode, self.phase = int(m.group(1)), "recording"
        elif "Reset the environment" in line:
            self.phase = "reset"
        elif "Re-record episode" in line:
            self.phase = "re-record"
        elif "Stop recording" in line or "Exiting" in line:
            self.phase = "finishing"
        if self.kind == "record" and (self.phase, self.episode) != before:
            self._narrate()

    def _narrate(self) -> None:
        """Spoken prompts for the operator (Mac voice), timed from LeRobot's own phase lines."""
        self._clear_timers()
        n, total = (self.episode or 0) + 1, self.plan["episodes"] or "?"
        if self.phase == "recording":
            voice.speak(f"Episode {n} of {total}. Go.")
            self._after(self.plan["episode_s"] - 5, "Five seconds.")
        elif self.phase == "reset":
            left = (self.plan["episodes"] or n) - n
            voice.speak(f"Reset the objects. {left} to go." if left > 0 else "Reset the objects. Last one done.")
            self._after(self.plan["reset_s"] - 3, "Get ready.")
        elif self.phase == "re-record":
            voice.speak("Redo that one.")
        elif self.phase == "finishing":
            voice.speak("Saving.")

    def start(self, kind: str, cmd: list[str]) -> None:
        if self.running:
            raise HTTPException(409, f"{self.kind} is already running; stop it first")
        exe = shutil.which(cmd[0], path=str(ROOT / ".venv/bin")) or shutil.which(cmd[0])
        if not exe:
            raise HTTPException(500, f"{cmd[0]} not found; run `uv sync --extra hardware`")
        self.kind, self.cmd, self.started, self.episode, self.phase, self.exit_code = kind, cmd, time.time(), None, None, None
        self.stopped_by_user = False
        arg = lambda k: next((int(a.split("=", 1)[1]) for a in cmd if a.startswith(f"--dataset.{k}=")), 0)  # noqa: E731
        self.plan = {"episodes": arg("num_episodes"), "episode_s": arg("episode_time_s"), "reset_s": arg("reset_time_s")}
        self.log(f"$ {' '.join(cmd)}")
        self.p = subprocess.Popen(
            [exe, *cmd[1:]],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            start_new_session=True,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.p and self.p.stdout
        for line in self.p.stdout:
            self.log(line.rstrip())
        self.exit_code = self.p.wait()
        self.log(f"[{self.kind} exited with code {self.exit_code}]")
        self.phase = "done"
        self._clear_timers()

    def stop(self) -> None:
        if not self.running:
            return
        assert self.p
        self.stopped_by_user = True
        # SIGINT lets LeRobot finish cleanly (save the dataset, disconnect arms).
        os.killpg(self.p.pid, signal.SIGINT)
        try:
            self.p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(self.p.pid, signal.SIGKILL)
            self.log("[force-killed after 20s]")

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "running": self.running,
            "startedAt": self.started,
            "episode": self.episode,
            "phase": self.phase,
            "exitCode": self.exit_code,
            "stoppedByUser": self.stopped_by_user,
            "cmd": " ".join(self.cmd),
        }


proc = Proc()

# Always-live Rerun camera view; steps aside whenever LeRobot or a preview needs the cameras.
live = LiveView(
    busy=lambda: proc.running or _preview_clients > 0 or camera_lock.locked(),
    cameras=lambda: {"side": int(os.getenv("SIDE_CAMERA_INDEX", "0")), "wrist": int(os.getenv("WRIST_CAMERA_INDEX", "1"))},
)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def robot_args(cameras: bool = True) -> list[str]:
    args = [
        "--robot.type=so101_follower",
        f"--robot.port={env('SO101_PORT')}",
        f"--robot.id={env('SO101_ID', 'remind_follower')}",
        "--teleop.type=so101_leader",
        f"--teleop.port={env('LEADER_PORT')}",
        f"--teleop.id={env('LEADER_ID', 'remind_leader')}",
    ]
    if cameras:
        cam = "{{type: opencv, index_or_path: {}, width: 640, height: 480, fps: 30}}"
        side, wrist = env("SIDE_CAMERA_INDEX", "0"), env("WRIST_CAMERA_INDEX", "1")
        args.append(f"--robot.cameras={{ side: {cam.format(side)}, wrist: {cam.format(wrist)} }}")
    return args


MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def motor_health(port: str) -> dict:
    """Ping each servo and read temperature. Feetech servos latch errors such as overload until
    their power is cut, and then stop answering LeRobot's handshake."""
    import scservo_sdk as scs

    ph, pk = scs.PortHandler(port), scs.PacketHandler(0)
    if not ph.openPort():
        return {"error": "could not open port"}
    ph.setBaudRate(1_000_000)
    out = {}
    try:
        for i, name in enumerate(MOTORS, start=1):
            model, comm, err = pk.ping(ph, i)
            if comm != scs.COMM_SUCCESS:
                out[name] = {"ok": False, "problem": "no reply"}
                continue
            temp, _, _ = pk.read1ByteTxRx(ph, i, 63)
            problem = pk.getRxPacketError(err).replace("[RxPacketError] ", "") if err else None
            out[name] = {"ok": not problem and temp < 65, "tempC": temp, "problem": problem or ("hot" if temp >= 65 else None)}
    finally:
        ph.closePort()
    return out


class ClearIn(BaseModel):
    arm: Literal["follower", "leader"] = "follower"
    motor: str = "gripper"


@router.post("/clear-fault")
def clear_fault(body: ClearIn) -> dict:
    """Operator-requested recovery from a latched servo fault (same effect as a power cycle):
    set the motor's target to where it already is (no motion), toggle torque so the status clears,
    and leave that motor's torque off. Refused while LeRobot is using the arms."""
    import scservo_sdk as scs

    if proc.running:
        raise HTTPException(409, "stop teleop/recording first")
    if body.motor not in MOTORS:
        raise HTTPException(422, "unknown motor")
    port = env("SO101_PORT" if body.arm == "follower" else "LEADER_PORT")
    mid = MOTORS.index(body.motor) + 1
    ph, pk = scs.PortHandler(port), scs.PacketHandler(0)
    if not ph.openPort():
        raise HTTPException(500, "could not open the arm's port")
    ph.setBaudRate(1_000_000)
    try:
        pos, comm, _ = pk.read2ByteTxRx(ph, mid, 56)
        if comm != scs.COMM_SUCCESS:
            raise HTTPException(500, "motor not answering; unplug that arm's DC power for 10 s")
        temp, _, _ = pk.read1ByteTxRx(ph, mid, 63)
        if temp >= 65:
            raise HTTPException(409, f"{body.motor} is hot ({temp}°C); let it cool first")
        pk.write2ByteTxRx(ph, mid, 42, pos)  # target = current position
        pk.write1ByteTxRx(ph, mid, 40, 1)
        time.sleep(0.4)
        pk.write1ByteTxRx(ph, mid, 40, 0)
        time.sleep(0.2)
        _, _, err = pk.read2ByteTxRx(ph, mid, 42)
    finally:
        ph.closePort()
    return {"arm": body.arm, "motor": body.motor, "cleared": not err, "tempC": temp}


@router.get("/health")
def health() -> dict:
    if proc.running:
        raise HTTPException(409, "arms are in use by LeRobot")
    return {arm: motor_health(env(key)) if Path(env(key)).exists() else {"error": "not connected"}
            for arm, key in (("follower", "SO101_PORT"), ("leader", "LEADER_PORT"))}


def require_ports() -> None:
    for name in ("SO101_PORT", "LEADER_PORT"):
        if not env(name) or not Path(env(name)).exists():
            raise HTTPException(400, f"{name} is not set or not connected ({env(name) or 'empty'})")
    bad = [f"{arm} {m}: {h.get('problem')}" for arm, motors in health().items() if "error" not in motors
           for m, h in motors.items() if not h["ok"]]
    if bad:
        raise HTTPException(409, "Motor problem: " + "; ".join(bad) + ". Unplug that arm's DC power for 10 s (and let a hot motor cool), then retry.")
    release_cameras()


# ---------------------------------------------------------------- status & config


@router.get("/status")
def status() -> dict:
    ports = sorted(glob.glob("/dev/tty.usbmodem*"))

    def cal(path: Path) -> dict | None:
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        return {k: v["range_max"] - v["range_min"] for k, v in d.items()}

    return {
        "process": proc.status(),
        "ports": ports,
        "follower": {
            "port": env("SO101_PORT"),
            "connected": env("SO101_PORT") in ports,
            "calibration": cal(CALIB / f"robots/so_follower/{env('SO101_ID', 'remind_follower')}.json"),
        },
        "leader": {
            "port": env("LEADER_PORT"),
            "connected": env("LEADER_PORT") in ports,
            "calibration": cal(CALIB / f"teleoperators/so_leader/{env('LEADER_ID', 'remind_leader')}.json"),
        },
        "cameras": {"side": int(env("SIDE_CAMERA_INDEX", "0")), "wrist": int(env("WRIST_CAMERA_INDEX", "1"))},
        "perceptron": {"configured": bool(env("PERCEPTRON_API_KEY"))},
        "live": live.status(),
        "serverVoice": voice.ENABLED,
        "hfUser": env("HF_USER"),
    }


class LiveIn(BaseModel):
    on: bool


@router.post("/live")
def set_live(body: LiveIn) -> dict:
    live.enabled = body.on
    if body.on:
        live.start()
    else:
        live.release(hold_off=0)
    return live.status()


@router.get("/logs")
def logs(since: int = 0) -> dict:
    with proc.lock:
        lines = [{"seq": s, "line": l} for s, l in proc.logs if s > since]
    return {"lines": lines[-500:], "last": proc.seq}


class CameraConfig(BaseModel):
    side: int
    wrist: int


@router.post("/config/cameras")
def set_cameras(body: CameraConfig) -> dict:
    for key, value in (("SIDE_CAMERA_INDEX", body.side), ("WRIST_CAMERA_INDEX", body.wrist)):
        set_key(str(ENV_FILE), key, str(value), quote_mode="never")
        os.environ[key] = str(value)
    return {"side": body.side, "wrist": body.wrist}


# ---------------------------------------------------------------- camera previews (idle only)

camera_lock = threading.Lock()
_preview_clients = 0
_preview_gen = 0  # bumping this ends every open preview stream


def release_cameras(timeout: float = 4.0) -> None:
    """End preview streams and the live view so LeRobot can open the cameras."""
    global _preview_gen
    live.release(hold_off=8.0)
    _preview_gen += 1
    deadline = time.time() + timeout
    while (_preview_clients > 0 or camera_lock.locked()) and time.time() < deadline:
        time.sleep(0.05)
    if _preview_clients > 0:
        raise HTTPException(409, "camera previews are still open; close them and retry")


@router.post("/cameras/release")
def cameras_release() -> dict:
    release_cameras()
    return {"released": True}


@router.get("/cameras")
def list_cameras(max_index: int = 5) -> list[dict]:
    if proc.running:
        raise HTTPException(409, "cameras are in use by LeRobot; watch them in Rerun")
    import cv2

    found = []
    live.release()
    with camera_lock:
        for i in range(max_index):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ok, frame = cap.read()
                if ok:
                    found.append({"index": i, "width": frame.shape[1], "height": frame.shape[0]})
            cap.release()
    return found


@router.get("/camera/{index}.mjpg")
def camera_stream(index: int):
    if proc.running:
        raise HTTPException(409, "cameras are in use by LeRobot; watch them in Rerun")
    import cv2

    live.release()  # the live view steps aside while this preview runs

    def frames():
        global _preview_clients
        gen = _preview_gen
        cap = cv2.VideoCapture(index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        _preview_clients += 1
        try:
            while cap.isOpened() and not proc.running and gen == _preview_gen:
                ok, frame = cap.read()
                if not ok:
                    break
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
                time.sleep(1 / 15)
        finally:
            _preview_clients -= 1
            cap.release()

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


# ---------------------------------------------------------------- teleop & recording


class TeleopIn(BaseModel):
    cameras: bool = True
    rerun: bool = True


@router.post("/teleop")
def start_teleop(body: TeleopIn) -> dict:
    require_ports()
    cmd = ["lerobot-teleoperate", *robot_args(body.cameras), "--fps=30"]
    if body.rerun:
        cmd += ["--display_data=true", *display_args()]
    proc.start("teleop", cmd)
    return proc.status()


class RecordIn(BaseModel):
    repo: str
    task: str = "pick up the tea box and place it in the tray"
    episodes: int = 10
    episodeSeconds: int = 20
    resetSeconds: int = 10
    rerun: bool = True
    sounds: bool = True  # LeRobot's own spoken prompts; the Studio voice assistant replaces them


def record_cmd(body: RecordIn) -> tuple[list[str], bool]:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", body.repo):
        raise HTTPException(422, "repo must look like user/name")
    resume = (DATA_HOME / body.repo / "meta/info.json").exists()
    cmd = [
        "lerobot-record",
        *robot_args(True),
        f"--dataset.repo_id={body.repo}",
        f"--dataset.single_task={body.task}",
        f"--dataset.num_episodes={body.episodes}",
        f"--dataset.episode_time_s={body.episodeSeconds}",
        f"--dataset.reset_time_s={body.resetSeconds}",
        "--dataset.fps=30",
        "--dataset.push_to_hub=false",
        "--dataset.no_stamp=true",  # LeRobot 0.6 otherwise makes a new timestamped folder per run, breaking resume
        f"--display_data={'true' if body.rerun else 'false'}",
        *(display_args() if body.rerun else []),
        f"--play_sounds={'true' if body.sounds else 'false'}",
    ]
    if resume:
        cmd.append("--resume=true")
    return cmd, resume


def episode_count(repo: str) -> int:
    info = DATA_HOME / repo / "meta/info.json"
    return int(json.loads(info.read_text()).get("total_episodes") or 0) if info.exists() else 0


@router.post("/record")
def start_record(body: RecordIn) -> dict:
    require_ports()
    cmd, resume = record_cmd(body)
    proc.start("record", cmd)
    return {**proc.status(), "resume": resume}


@router.post("/stop")
def stop() -> dict:
    proc.stop()
    return proc.status()


# ---------------------------------------------------------------- local datasets


def dataset_info(path: Path) -> dict:
    info = json.loads((path / "meta/info.json").read_text())
    files = [f for f in path.rglob("*") if f.is_file()]
    return {
        "repo": str(path.relative_to(DATA_HOME)),
        "episodes": info.get("total_episodes"),
        "frames": info.get("total_frames"),
        "fps": info.get("fps"),
        "codebaseVersion": info.get("codebase_version"),
        "features": [k for k in info.get("features", {}) if k.startswith("observation.images")],
        "sizeMB": round(sum(f.stat().st_size for f in files) / 1e6, 1),
        "files": len(files),
    }


@router.get("/datasets")
def datasets() -> list[dict]:
    out = []
    for info in DATA_HOME.glob("*/*/meta/info.json"):
        if "calibration" in info.parts:
            continue
        try:
            out.append(dataset_info(info.parent.parent))
        except Exception as e:  # noqa: BLE001
            out.append({"repo": str(info.parent.parent.relative_to(DATA_HOME)), "error": str(e)})
    return sorted(out, key=lambda d: d["repo"])


# ---------------------------------------------------------------- Perceptron pipeline


def pc() -> httpx.Client:
    key = env("PERCEPTRON_API_KEY")
    if not key:
        raise HTTPException(400, "set PERCEPTRON_API_KEY in robot_worker/.env")
    # Long-running operations may answer 303 with a same-origin polling URL; follow it.
    return httpx.Client(base_url=PERCEPTRON, headers={"Authorization": f"Bearer {key}"}, timeout=60, follow_redirects=True)


def pjson(r: httpx.Response):
    if r.status_code >= 400:
        try:  # API errors look like {"error": {"code", "message", "fields"}}
            err = r.json()["error"]
            detail = f"{err.get('code')}: {err.get('message') or ''} {err.get('fields') or ''}".strip()
        except Exception:  # noqa: BLE001
            detail = r.text[:500]
        raise HTTPException(r.status_code, f"Perceptron {detail}")
    return r.json() if r.content else {}


def _grant_list(resp) -> list[dict]:
    """The upload-URL response body isn't specified in the OpenAPI schema; accept likely shapes."""
    if isinstance(resp, list):
        return resp
    for key in ("files", "uploads", "items", "data"):
        if isinstance(resp.get(key), list):
            return resp[key]
    raise RuntimeError(f"unexpected upload response: {str(resp)[:200]}")


uploads: dict[str, dict] = {}  # repo -> progress


def _upload(repo: str) -> None:
    state = uploads[repo]
    root = DATA_HOME / repo
    try:
        # The API rejects zero-byte files (size_bytes >= 1).
        files = sorted(f for f in root.rglob("*") if f.is_file() and not f.name.startswith(".") and f.stat().st_size > 0)
        state.update(total=len(files), done=0, phase="registering")
        slug = repo.replace("/", "-")[:80]
        with pc() as c:
            # Stable key per dataset snapshot: a retry reuses the registration instead of duplicating it.
            key = f"upload-{slug}-{episode_count(repo)}ep"
            ds = pjson(c.post("/v1/datasets", headers={"Idempotency-Key": key}, json={"name": slug, "source_kind": "upload"}))
            state["datasetId"] = ds_id = ds.get("id") or ds.get("dataset_id")
            if not ds_id:
                raise RuntimeError(f"no dataset id in response: {str(ds)[:200]}")
            entries = []
            for f in files:
                data = f.read_bytes()
                entries.append({"path": f.relative_to(root).as_posix(), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            state["phase"] = "uploading"
            for i in range(0, len(entries), 500):
                batch = entries[i : i + 500]
                grants = pjson(c.post(f"/v1/datasets/{ds_id}/uploads", json={"files": batch}))
                for g in _grant_list(grants):
                    path = root / g["path"]
                    url = g.get("url") or g.get("upload_url") or g.get("signed_url")
                    # Signed URL + its exact headers only; never the team key.
                    r = httpx.request(g.get("method", "PUT"), url, headers=g.get("headers", {}), content=path.read_bytes(), timeout=300)
                    if r.status_code >= 400:
                        raise RuntimeError(f"upload {g['path']} failed: {r.status_code} {r.text[:200]}")
                    state["done"] += 1
            state["phase"] = "finalizing"
            pjson(c.post(f"/v1/datasets/{ds_id}/finalize"))
            state["phase"] = "finalized"
    except Exception as e:  # noqa: BLE001
        state.update(phase="error", error=str(e))


class UploadIn(BaseModel):
    repo: str


@router.post("/perceptron/upload")
def upload(body: UploadIn) -> dict:
    if not (DATA_HOME / body.repo / "meta/info.json").exists():
        raise HTTPException(404, "dataset not found locally")
    if uploads.get(body.repo, {}).get("phase") in ("registering", "uploading", "finalizing"):
        raise HTTPException(409, "upload already in progress")
    pc().close()  # fail fast if no key
    uploads[body.repo] = {"phase": "starting", "done": 0, "total": 0}
    threading.Thread(target=_upload, args=(body.repo,), daemon=True).start()
    return uploads[body.repo]


@router.get("/perceptron/uploads")
def upload_status() -> dict:
    return uploads


class HfIn(BaseModel):
    repoId: str
    name: str | None = None


@router.post("/perceptron/datasets/hf")
def register_hf(body: HfIn) -> dict:
    with pc() as c:
        return pjson(c.post("/v1/datasets", headers={"Idempotency-Key": f"hf-{body.repoId.replace('/', '-')}"},
                            json={"name": body.name or body.repoId.replace("/", "-"), "source_kind": "huggingface", "repo_id": body.repoId, "revision": "main"}))


@router.get("/perceptron/datasets/{ds_id}")
def dataset_status(ds_id: str) -> dict:
    with pc() as c:
        ds = pjson(c.get(f"/v1/datasets/{ds_id}"))
        try:
            ds["validation"] = pjson(c.get(f"/v1/datasets/{ds_id}/validation"))
        except HTTPException:
            pass
        return ds


@router.get("/perceptron/capabilities")
def capabilities():
    with pc() as c:
        return pjson(c.get("/v1/capabilities"))


class TrainIn(BaseModel):  # limits from the participant OpenAPI JobRequest schema
    datasetId: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$")
    steps: int = Field(1000, ge=1, le=10000)
    backend: Literal["standard", "shared"] = "standard"
    mode: Literal["expert_only", "backbone_lora", "full"] = "expert_only"
    actionHorizon: Literal[20, 30] = 30
    rtc: bool = True


@router.post("/perceptron/train")
def train(body: TrainIn) -> dict:
    with pc() as c:
        return pjson(c.post("/v1/jobs", headers={"Idempotency-Key": f"train-{body.datasetId}-{body.mode}-{body.actionHorizon}-{body.steps}"},
                            json={"dataset_id": body.datasetId, "backend": body.backend, "mode": body.mode,
                                  "action_horizon": body.actionHorizon, "rtc_enabled": body.rtc, "steps": body.steps}))


@router.get("/perceptron/jobs")
def jobs():
    with pc() as c:
        return pjson(c.get("/v1/jobs"))


@router.get("/perceptron/jobs/{job_id}")
def job(job_id: str):
    with pc() as c:
        j = pjson(c.get(f"/v1/jobs/{job_id}"))
        try:
            j["metrics"] = pjson(c.get(f"/v1/jobs/{job_id}/metrics"))
            j["logs"] = pjson(c.get(f"/v1/jobs/{job_id}/logs"))
        except HTTPException:
            pass
        return j


@router.post("/perceptron/jobs/{job_id}/cancel")
def cancel(job_id: str):
    with pc() as c:
        return pjson(c.post(f"/v1/jobs/{job_id}/cancel"))


@router.get("/perceptron/deployments")
def deployments():
    with pc() as c:
        return pjson(c.get("/v1/deployments"))
