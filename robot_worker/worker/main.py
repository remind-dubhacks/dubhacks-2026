"""ReMind robot worker. Accepts only allowlisted (action, object) jobs, runs one at a time, and
never retries after an error. The physical emergency stop remains the primary safety control."""

import logging
import os
import threading
from datetime import datetime, timezone

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import campaign, studio, vision_api  # noqa: E402
from .shuffle_math import allowlist as shuffle_allowlist  # noqa: E402
from .executors import MockExecutor, PerceptronExecutor, RobotError, ScriptedExecutor, Stopped

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("robot_worker")

# Defense in depth: the backend validates too, but the worker refuses anything not listed here.
# `instruction` is sent to the Perceptron policy; `sequence` names a taught sequence in poses.json.
ALLOWED: dict[tuple[str, str], dict] = {
    ("move_known_object", "tea_box"): {"instruction": "pick up the tea box and place it in the tray", "sequence": "tea"},
    ("move_known_object", "coffee_box"): {"instruction": "pick up the coffee box and place it in the tray", "sequence": "coffee"},
    # Memory game shuffles: the instruction is exactly what the policy was trained on.
    **shuffle_allowlist(),
}

REQUIRE_VERIFICATION = os.getenv("REQUIRE_VERIFICATION", "true").lower() == "true"
MODE = os.getenv("ROBOT_MODE", "mock")
EXECUTORS = {"mock": MockExecutor, "perceptron": PerceptronExecutor, "scripted": ScriptedExecutor}
executor = EXECUTORS[MODE]()
if getattr(getattr(getattr(executor, "robot", None), "robot", None), "cameras", None):
    vision_api.robot_frame = executor.robot.side_frame  # row checks read the camera the robot holds

app = FastAPI(title="ReMind robot worker")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(studio.router)
app.include_router(vision_api.router)
app.include_router(campaign.router)
studio.live.start()  # always-live Rerun camera view (LIVE_VIEW=0 to turn off)
jobs: dict[str, dict] = {}
lock = threading.Lock()
stop_event = threading.Event()
active_job: str | None = None


class JobIn(BaseModel):
    jobId: str
    actionId: str
    objectId: str
    # Shuffles only: the row before the move, slot 1 first (black/white/purple). Defaults to the
    # recording start layout. Lets the camera check a shuffle that starts from a mixed row.
    start: list[str] | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(job_id: str, spec: dict) -> None:
    global active_job
    job = jobs[job_id]
    job.update(status="running", startedAt=now())
    studio.ROBOT_BUSY = True  # keep motor-health polls off the serial port during the move
    try:
        executor.execute(spec, stop_event)
        check = getattr(executor, "last_check", None)
        job["check"] = check
        # A camera-confirmed shuffle needs no caregiver check; anything unsure still does.
        confirmed = bool(check) and check.get("verdict") == "ok"
        job["status"] = "verifying" if REQUIRE_VERIFICATION and not confirmed else "succeeded"
    except Stopped:
        job["status"] = "stopped"
    except RobotError as e:
        log.error("job %s failed: %s", job_id, e)
        job.update(status="failed", errorCode=e.code, error=str(e), check=getattr(executor, "last_check", None))
    except Exception as e:  # noqa: BLE001
        log.exception("job %s crashed", job_id)
        job.update(status="failed", errorCode="worker_exception", error=str(e))
    finally:
        studio.ROBOT_BUSY = False
        job["finishedAt"] = now()
        with lock:
            active_job = None


@app.get("/health")
def health():
    try:
        ready = executor.ready()
    except Exception as e:  # noqa: BLE001
        return {"mode": executor.mode, "ready": False, "busy": active_job is not None, "error": str(e)}
    return {"mode": executor.mode, "ready": ready, "busy": active_job is not None, "requireVerification": REQUIRE_VERIFICATION}


@app.post("/jobs")
def submit(body: JobIn):
    global active_job
    spec = ALLOWED.get((body.actionId, body.objectId))
    if spec is None:
        raise HTTPException(422, "action/object not on worker allowlist")
    with lock:
        if active_job is not None:
            raise HTTPException(409, "robot is busy")
        active_job = body.jobId
    if body.start is not None:
        if sorted(body.start) != ["black", "purple", "white"] or "shuffle" not in spec:
            with lock:
                active_job = None
            raise HTTPException(422, "start must be black, white and purple in some order (shuffle jobs only)")
        spec = {**spec, "start": list(body.start)}
    stop_event.clear()
    jobs[body.jobId] = {**body.model_dump(), "status": "queued", "errorCode": None, "queuedAt": now()}
    threading.Thread(target=run, args=(body.jobId, spec), daemon=True).start()
    return jobs[body.jobId]


@app.get("/jobs/{job_id}")
def status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return jobs[job_id]


@app.post("/stop")
def stop():
    stop_event.set()
    log.warning("software stop requested (active job: %s)", active_job)
    return {"stopping": active_job}
