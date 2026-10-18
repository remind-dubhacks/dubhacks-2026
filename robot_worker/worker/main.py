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
from .executors import MockExecutor, PerceptronExecutor, RobotError, ScriptedExecutor, Stopped

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("robot_worker")

# Defense in depth: the backend validates too, but the worker refuses anything not listed here.
# `instruction` is sent to the Perceptron policy; `sequence` names a taught sequence in poses.json.
ALLOWED: dict[tuple[str, str], dict] = {
    ("move_known_object", "tea_box"): {"instruction": "pick up the tea box and place it in the tray", "sequence": "tea"},
    ("move_known_object", "coffee_box"): {"instruction": "pick up the coffee box and place it in the tray", "sequence": "coffee"},
}

REQUIRE_VERIFICATION = os.getenv("REQUIRE_VERIFICATION", "true").lower() == "true"
MODE = os.getenv("ROBOT_MODE", "mock")
EXECUTORS = {"mock": MockExecutor, "perceptron": PerceptronExecutor, "scripted": ScriptedExecutor}
executor = EXECUTORS[MODE]()

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
jobs: dict[str, dict] = {}
lock = threading.Lock()
stop_event = threading.Event()
active_job: str | None = None


class JobIn(BaseModel):
    jobId: str
    actionId: str
    objectId: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(job_id: str, spec: dict) -> None:
    global active_job
    job = jobs[job_id]
    job.update(status="running", startedAt=now())
    try:
        executor.execute(spec, stop_event)
        job["status"] = "verifying" if REQUIRE_VERIFICATION else "succeeded"
    except Stopped:
        job["status"] = "stopped"
    except RobotError as e:
        log.error("job %s failed: %s", job_id, e)
        job.update(status="failed", errorCode=e.code)
    except Exception as e:  # noqa: BLE001
        log.exception("job %s crashed", job_id)
        job.update(status="failed", errorCode="worker_exception", error=str(e))
    finally:
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
