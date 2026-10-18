"""Recording campaign: drives a human operator through batches of LeRobot recordings until every
target (task x episode count) is reached, then optionally uploads and trains on Perceptron.

Per batch: pick the least-complete target -> tell the operator what to set up (spoken by the
Studio voice) -> optional vision check that the object is in view -> wait for "ready" -> motor
health check -> record N episodes -> count new episodes -> short break. Any fault pauses the
campaign; nothing retries on its own. The operator does every demonstration."""

import json
import os
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import studio

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "campaign.json"

router = APIRouter(prefix="/studio/campaign")


class Target(BaseModel):
    id: str
    task: str  # exact instruction; must match the robot worker's ALLOWED instruction at run time
    object: str  # name taught in the vision library, used for the pre-batch check
    target: int = 50
    variations: list[str] = []


class Config(BaseModel):
    repo: str
    batchSize: int = Field(10, ge=1, le=50)
    episodeSeconds: int = Field(20, ge=5, le=120)
    resetSeconds: int = Field(10, ge=0, le=60)
    breakSeconds: int = Field(20, ge=0, le=600)
    visionCheck: bool = True
    autoUpload: bool = True
    autoTrain: bool = False  # Perceptron allows only 2 successful training jobs per team: train deliberately
    trainSteps: int = Field(1000, ge=100, le=10000)  # API max is 10,000
    targets: list[Target]


def default_config() -> Config:
    user = os.getenv("HF_USER") or "remind"
    spot = lambda s, o: [  # noqa: E731
        f"{o} on spot {s}, label facing the camera",
        f"{o} on spot {s}, turned slightly left",
        f"{o} on spot {s}, turned slightly right",
        f"{o} on spot {s}, nudged 2 cm toward the robot",
        f"{o} on spot {s}, nudged 2 cm away from the robot",
    ]
    return Config(
        repo=f"{user}/remind-sort",
        targets=[
            Target(id="tea", task="pick up the tea box and place it in the tray", object="tea box", variations=spot("A", "tea box")),
            Target(id="coffee", task="pick up the coffee box and place it in the tray", object="coffee box", variations=spot("B", "coffee box")),
        ],
    )


class Campaign:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.ready = threading.Event()
        self.skip_check = threading.Event()
        self.thread: threading.Thread | None = None
        self.stop_flag = False
        self.paused = False
        self.state = "idle"
        self.message = ""
        self.message_seq = 0
        self.current: dict | None = None
        self.history: list[dict] = []
        self.config = default_config()
        self.progress: dict[str, int] = {}
        self.batches: dict[str, int] = {}
        self.dataset_id: str | None = None
        self.job_id: str | None = None
        self.load()

    # ---------- persistence

    def load(self) -> None:
        if STATE_FILE.exists():
            d = json.loads(STATE_FILE.read_text())
            self.config = Config(**d["config"])
            self.progress = d.get("progress", {})
            self.batches = d.get("batches", {})
            self.history = d.get("history", [])[-200:]
            self.dataset_id, self.job_id = d.get("datasetId"), d.get("jobId")

    def save(self) -> None:
        STATE_FILE.write_text(json.dumps({
            "config": self.config.model_dump(), "progress": self.progress, "batches": self.batches,
            "history": self.history[-200:], "datasetId": self.dataset_id, "jobId": self.job_id,
        }, indent=1))

    # ---------- status

    def say(self, message: str, state: str | None = None) -> None:
        with self.lock:
            if state:
                self.state = state
            self.message = message
            self.message_seq += 1
            self.history.append({"t": time.time(), "state": self.state, "message": message})
            self.save()

    def status(self) -> dict:
        with self.lock:
            targets = [{**t.model_dump(), "done": self.progress.get(t.id, 0)} for t in self.config.targets]
            return {
                "state": self.state,
                "running": bool(self.thread and self.thread.is_alive()),
                "paused": self.paused,
                "message": self.message,
                "messageSeq": self.message_seq,
                "current": self.current,
                "config": self.config.model_dump(),
                "targets": targets,
                "totalDone": sum(t["done"] for t in targets),
                "totalTarget": sum(t.target for t in self.config.targets),
                "datasetEpisodes": studio.episode_count(self.config.repo),
                "datasetId": self.dataset_id,
                "jobId": self.job_id,
                "history": self.history[-15:],
            }

    # ---------- control

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                if self.paused:
                    self.paused = False
                    self.say("Resuming the campaign.")
                return
            self.stop_flag, self.paused = False, False
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def pause(self, why: str = "Paused.") -> None:
        self.paused = True
        self.say(why, "paused")

    def stop(self) -> None:
        self.stop_flag = True
        self.ready.set()
        if studio.proc.running and studio.proc.kind == "record":
            studio.proc.stop()

    # ---------- runner

    def _wait(self, seconds: float) -> bool:
        """Sleep in small steps; False if stopped."""
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_flag:
                return False
            time.sleep(0.2)
        return not self.stop_flag

    def _wait_unpaused(self) -> bool:
        while self.paused and not self.stop_flag:
            time.sleep(0.3)
        return not self.stop_flag

    def _next_target(self) -> Target | None:
        left = [t for t in self.config.targets if self.progress.get(t.id, 0) < t.target]
        return min(left, key=lambda t: self.progress.get(t.id, 0) / max(1, t.target)) if left else None

    def _run(self) -> None:
        try:
            self.say("Campaign started.", "preflight")
            while not self.stop_flag:
                if not self._wait_unpaused():
                    break
                target = self._next_target()
                if target is None:
                    self._finish()
                    break
                self._batch(target)
            if self.stop_flag:
                self.say("Campaign stopped.", "idle")
        except Exception as e:  # noqa: BLE001
            self.say(f"Campaign error: {e}. Paused; fix it and press Start to continue.", "error")
        finally:
            with self.lock:
                self.current = None
                self.save()

    def _batch(self, t: Target) -> None:
        done = self.progress.get(t.id, 0)
        n = min(self.config.batchSize, t.target - done)
        k = self.batches.get(t.id, 0)
        variation = t.variations[k % len(t.variations)] if t.variations else f"{t.object} in its spot"
        with self.lock:
            self.current = {"targetId": t.id, "task": t.task, "object": t.object, "episodes": n, "batch": k + 1, "variation": variation}

        # 1. Setup prompt + vision check
        self.ready.clear()
        self.skip_check.clear()
        self.say(f"Next: {n} episodes of {t.object}. Set up: {variation}. Vary it a little each episode. Say ready when the scene is set.", "setup")
        if self.config.visionCheck:
            self._vision_check(t)
        while not self.ready.wait(0.3):
            if self.stop_flag:
                return
        if self.paused and not self._wait_unpaused():
            return

        # 2. Preflight: nothing else running, motors healthy
        if studio.proc.running:
            return self.pause(f"{studio.proc.kind} is already running. Stop it, then press Start.")
        try:
            studio.require_ports()
        except HTTPException as e:
            return self.pause(f"Can't record: {e.detail}")

        # 3. Record
        before = studio.episode_count(self.config.repo)
        cmd, _ = studio.record_cmd(studio.RecordIn(
            repo=self.config.repo, task=t.task, episodes=n, episodeSeconds=self.config.episodeSeconds,
            resetSeconds=self.config.resetSeconds, rerun=True, sounds=False))
        self.say(f"Recording {n} episodes: {t.task}.", "recording")
        studio.proc.start("record", cmd)
        while studio.proc.running:
            time.sleep(0.5)
        gained = max(0, studio.episode_count(self.config.repo) - before)
        with self.lock:
            self.progress[t.id] = done + gained
            self.batches[t.id] = k + 1
        if studio.proc.stopped_by_user or self.stop_flag:
            return self.pause(f"Recording stopped. Kept {gained} new episode{'s' if gained != 1 else ''}. Press Start to continue.")
        if studio.proc.exit_code not in (0, None):
            reason = next((l for l in reversed([x for _, x in studio.proc.logs]) if "Error" in l or "error" in l), "see the log")
            return self.pause(f"Recording failed after {gained} episodes: {reason[:160]}. Fix it, then press Start.")

        # 4. Break
        total = self.progress[t.id]
        msg = f"Batch done: {t.object} {total} of {t.target}."
        if self._next_target() is not None and self.config.breakSeconds:
            self.say(f"{msg} Take a {self.config.breakSeconds} second break.", "break")
            self._wait(self.config.breakSeconds)
        else:
            self.say(msg)

    def _vision_check(self, t: Target) -> None:
        from .vision_api import library  # lazy: keeps cv2 import out of startup paths

        if not any(n["name"] == t.object for n in library.names()):
            self.say(f"I haven't been taught what the {t.object} looks like, so I'll skip the camera check. Say ready when set.", "waiting_ready")
            return
        self.say(f"Checking the camera for the {t.object}.", "checking")
        found = self.look_for(t.object)
        if found:
            self.say(f"I can see the {t.object} at the {found}. Say ready to start recording.", "waiting_ready")
        else:
            self.say(f"I can't see the {t.object}. Check it's in its spot, then say ready. Say skip to record anyway.", "waiting_ready")

    def look_for(self, name: str, seconds: float = 4.0) -> str | None:
        import cv2

        from .vision import prepare, recognize
        from .vision_api import library

        if studio.proc.running:
            return None
        studio.release_cameras()
        cam = int(os.getenv("SIDE_CAMERA_INDEX", "0"))
        cap = cv2.VideoCapture(cam)
        try:
            end = time.time() + seconds
            while time.time() < end and cap.isOpened():
                ok, raw = cap.read()
                if not ok:
                    break
                frame = prepare(raw)
                h, w = frame.shape[:2]
                for b in recognize(frame, library):
                    if b.name == name:
                        return b.to_dict(w, h)["where"]
        finally:
            cap.release()
        return None

    def _finish(self) -> None:
        self.say(f"All targets reached: {sum(self.progress.values())} new episodes recorded.", "uploading" if self.config.autoUpload else "done")
        if not self.config.autoUpload:
            return self.say("Campaign complete. Upload and train from the Datasets section when ready.", "done")
        if not os.getenv("PERCEPTRON_API_KEY"):
            return self.say("Campaign complete, but there is no Perceptron API key, so I can't upload. Add it and press Upload.", "done")
        studio.upload(studio.UploadIn(repo=self.config.repo))
        while True:
            u = studio.uploads.get(self.config.repo, {})
            if u.get("phase") in ("finalized", "error") or self.stop_flag:
                break
            with self.lock:
                self.message = f"Uploading: {u.get('done', 0)} of {u.get('total', 0)} files."
            time.sleep(1)
        u = studio.uploads.get(self.config.repo, {})
        if u.get("phase") != "finalized":
            return self.say(f"Upload failed: {u.get('error', 'unknown error')}. Retry from Datasets.", "error")
        self.dataset_id = u.get("datasetId")
        if not self.config.autoTrain:
            return self.say(f"Uploaded as dataset {self.dataset_id}. Start training when ready.", "done")
        self.say("Upload finished. Starting training.", "training")
        job = studio.train(studio.TrainIn(datasetId=self.dataset_id, steps=self.config.trainSteps))
        self.job_id = job.get("id") if isinstance(job, dict) else None
        self.say(f"Training started{f', job {self.job_id}' if self.job_id else ''}. When a deployment is ready, test ten trials per object.", "done")


campaign = Campaign()


@router.get("")
def get_status() -> dict:
    return campaign.status()


@router.put("/config")
def set_config(cfg: Config) -> dict:
    if campaign.thread and campaign.thread.is_alive():
        raise HTTPException(409, "stop the campaign before changing its plan")
    with campaign.lock:
        campaign.config = cfg
        campaign.save()
    return campaign.status()


@router.post("/start")
def start() -> dict:
    campaign.start()
    return campaign.status()


@router.post("/ready")
def ready() -> dict:
    campaign.ready.set()
    return campaign.status()


@router.post("/skip")
def skip() -> dict:
    campaign.skip_check.set()
    campaign.ready.set()
    return campaign.status()


@router.post("/pause")
def pause() -> dict:
    campaign.pause("Paused by operator. The current batch finishes unless you press Stop.")
    return campaign.status()


@router.post("/stop")
def stop() -> dict:
    campaign.stop()
    return campaign.status()


@router.post("/reset-progress")
def reset_progress() -> dict:
    if campaign.thread and campaign.thread.is_alive():
        raise HTTPException(409, "stop the campaign first")
    with campaign.lock:
        campaign.progress, campaign.batches, campaign.history = {}, {}, []
        campaign.dataset_id = campaign.job_id = None
        campaign.save()
    return campaign.status()
