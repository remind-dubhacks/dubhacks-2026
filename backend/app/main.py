"""ReMind session orchestrator (spec §7, §10).

The agent only proposes; this module decides. A robot job is created only when the session is
consented, not stopped, idle on the robot, and the object/action pair is on the activity allowlist.
Success is reported only after the worker finishes *and* (by default) a caregiver confirms it."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import agent, robot_client
from .catalog import ACTIONS, ACTIVITIES, OBJECTS, choice_labels
from .config import settings
from .db import Store, connect
from .models import (
    ROBOT_BUSY,
    TERMINAL_JOB,
    TRANSITIONS,
    FeedbackIn,
    JobCreate,
    JobStatus,
    ParticipantIn,
    SessionCreate,
    SessionState,
    StopIn,
    TurnIn,
    VerifyIn,
)
from .robot_client import RobotWorkerError
from .vision import router as vision_router
from .voice import router as voice_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("remind")

DEMO_PARTICIPANT = {
    "_id": "demo-rose",
    "alias": "Rose",  # synthetic, pseudonymous demo profile — never real patient data
    "interestTags": ["tea", "gardening", "family gatherings"],
    "communicationPreferences": {"largeText": True, "readAloud": True},
    "consentFlags": {"sessionConsent": True, "rememberPreferences": True},
    "preferences": {"favoriteObjectId": "tea_box"},
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = await connect()
    await seed(app.state.store)
    yield


async def seed(store: Store) -> None:
    if not await store.get("participants", DEMO_PARTICIPANT["_id"]):
        await store.insert("participants", {**DEMO_PARTICIPANT, "createdAt": now()})
    for act in ACTIVITIES.values():
        if not await store.get("activities", act["_id"]):
            await store.insert("activities", act)


app = FastAPI(title="ReMind API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(vision_router)
app.include_router(voice_router)


def store(request: Request) -> Store:
    return request.app.state.store


# ---------- helpers ----------


async def get_session(s: Store, session_id: str) -> dict:
    sess = await s.get("sessions", session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    return sess


async def transition(s: Store, sess: dict, new: SessionState, **fields) -> dict:
    cur = SessionState(sess["state"])
    if cur == new:
        return sess
    allowed = new in (SessionState.stopped, SessionState.needs_staff) and cur != SessionState.stopped
    if not (allowed or new in TRANSITIONS[cur]):
        raise HTTPException(409, f"invalid transition {cur.value} -> {new.value}")
    extra = {"endedAt": now()} if new == SessionState.stopped else {}
    return await s.update("sessions", sess["_id"], {"state": new.value, "updatedAt": now(), **extra, **fields})


async def advance(s: Store, sess: dict, *steps: SessionState) -> dict:
    """Walk forward through the given states, skipping ones the session has already passed."""
    for step in steps:
        cur = SessionState(sess["state"])
        if step == cur or step in TRANSITIONS[cur]:
            sess = await transition(s, sess, step)
    return sess


def session_view(sess: dict, persistent: bool) -> dict:
    activity = ACTIVITIES[sess["activityId"]]
    return {**sess, "choices": choice_labels(activity), "persistent": persistent}


async def stop_session(s: Store, sess: dict) -> dict:
    if sess.get("activeJobId"):
        job = await s.get("robot_jobs", sess["activeJobId"])
        if job and JobStatus(job["status"]) not in TERMINAL_JOB:
            await s.update("robot_jobs", job["_id"], {"status": JobStatus.stopped.value, "updatedAt": now()})
    return await transition(s, sess, SessionState.stopped, activeJobId=None)


async def remember_choice(s: Store, sess: dict, object_id: str) -> bool:
    participant = await s.get("participants", sess["participantId"])
    if not participant or not participant.get("consentFlags", {}).get("rememberPreferences"):
        return False
    prefs = {**participant.get("preferences", {}), "favoriteObjectId": object_id, "lastActivityId": sess["activityId"]}
    await s.update("participants", participant["_id"], {"preferences": prefs})
    return s.persistent


# ---------- routes ----------


@app.get("/api/health")
async def health(request: Request):
    try:
        worker = await robot_client.health()
    except RobotWorkerError as e:
        worker = {"ready": False, "error": str(e)}
    return {"ok": True, "persistent": store(request).persistent, "robot": worker}


@app.get("/api/activities")
async def list_activities():
    return [{**a, "choices": choice_labels(a)} for a in ACTIVITIES.values()]


@app.get("/api/participants")
async def list_participants(request: Request):
    return await store(request).find("participants")


@app.post("/api/participants")
async def create_participant(body: ParticipantIn, request: Request):
    doc = {"_id": new_id(), **body.model_dump(), "preferences": {}, "createdAt": now()}
    return await store(request).insert("participants", doc)


@app.get("/api/participants/{pid}")
async def get_participant(pid: str, request: Request):
    p = await store(request).get("participants", pid)
    if not p:
        raise HTTPException(404, "participant not found")
    return p


@app.delete("/api/participants/{pid}")
async def delete_participant(pid: str, request: Request):
    s = store(request)
    sessions = await s.find("sessions", {"participantId": pid})
    deleted = {"sessions": len(sessions), "robot_jobs": 0, "feedback": 0, "messages": 0}
    for sess in sessions:
        for coll in ("robot_jobs", "feedback", "messages"):
            deleted[coll] += await s.delete_many(coll, {"sessionId": sess["_id"]})
    await s.delete_many("sessions", {"participantId": pid})
    deleted["participants"] = await s.delete_many("participants", {"_id": pid})
    return {"deleted": deleted}


@app.post("/api/sessions")
async def create_session(body: SessionCreate, request: Request):
    s = store(request)
    participant = await s.get("participants", body.participantId)
    if not participant:
        raise HTTPException(404, "participant not found")
    activity = ACTIVITIES.get(body.activityId)
    if not activity:
        raise HTTPException(404, "activity not found")
    if not body.caregiverApproved:
        raise HTTPException(403, "a caregiver must approve the session")
    if not participant.get("consentFlags", {}).get("sessionConsent"):
        raise HTTPException(403, "participant has not consented to sessions")

    sess = {
        "_id": new_id(),
        "participantId": participant["_id"],
        "activityId": activity["_id"],
        "state": SessionState.idle.value,
        "startedAt": now(),
        "endedAt": None,
        "helpRequested": False,
        "optInSummary": None,
        "selections": [],
        "activeJobId": None,
        "lastReply": None,
    }
    await s.insert("sessions", sess)
    sess = await transition(s, sess, SessionState.consented)
    reply = agent.welcome(activity, participant)
    sess = await transition(s, sess, SessionState.prompting, lastReply=reply)
    return session_view(sess, s.persistent)


@app.get("/api/sessions/{sid}")
async def read_session(sid: str, request: Request):
    s = store(request)
    sess = await get_session(s, sid)
    view = session_view(sess, s.persistent)
    if sess.get("activeJobId"):
        view["activeJob"] = await s.get("robot_jobs", sess["activeJobId"])
    return view


@app.post("/api/sessions/{sid}/resume")
async def resume_session(sid: str, request: Request):
    """Caregiver clears a needs_staff state after checking the workspace."""
    s = store(request)
    sess = await get_session(s, sid)
    if sess["state"] != SessionState.needs_staff.value:
        raise HTTPException(409, "session is not waiting for staff")
    prompt = ACTIVITIES[sess["activityId"]]["prompts"]["choice"]
    sess = await transition(s, sess, SessionState.prompting, activeJobId=None, lastReply=prompt)
    return session_view(sess, s.persistent)


@app.post("/api/agent/turn")
async def agent_turn(body: TurnIn, request: Request):
    s = store(request)
    sess = await get_session(s, body.sessionId)
    activity = ACTIVITIES[sess["activityId"]]
    state = SessionState(sess["state"])

    if state == SessionState.stopped:
        return {"turn": {"reply": activity["prompts"]["stopped"], "intent": "stop"}, "session": session_view(sess, s.persistent)}

    participant = await s.get("participants", sess["participantId"])
    turn = await agent.agent_turn(body.text, activity, participant)

    if s.persistent:
        expires = now() + timedelta(hours=1)  # short retention; no persistent raw transcripts
        await s.insert("messages", {"_id": new_id(), "sessionId": sess["_id"], "role": "user", "text": body.text, "expiresAt": expires})

    if turn.intent == "stop":
        try:
            await robot_client.stop()
        except RobotWorkerError as e:
            log.error("software stop failed: %s", e)
        sess = await stop_session(s, sess)
    elif turn.intent == "help":
        sess = await s.update("sessions", sess["_id"], {"helpRequested": True})
        # TODO(Photon, P2): notify the caregiver here if opted in. Must never block this path.
    elif state in ROBOT_BUSY or state == SessionState.needs_staff:
        # Never queue a second action while the robot is busy or staff are needed.
        turn = turn.model_copy(update={"reply": activity["prompts"]["busy"], "intent": "chat", "objectId": None, "requestedAction": None})
    elif turn.intent == "select_object":
        if state in (SessionState.complete, SessionState.validated):
            sess = await transition(s, sess, SessionState.prompting)
        sess = await transition(s, sess, SessionState.choice_received)
        valid = (
            turn.objectId in activity["objectIds"]
            and turn.requestedAction in activity["allowedActionIds"]
            and turn.requestedAction in ACTIONS
        )
        if valid:
            sess = await transition(s, sess, SessionState.validated, pendingObjectId=turn.objectId)
        else:
            turn = turn.model_copy(update={"reply": activity["prompts"]["unclear"], "intent": "unclear", "objectId": None, "requestedAction": None})
            sess = await transition(s, sess, SessionState.prompting)
    elif state == SessionState.complete:
        sess = await transition(s, sess, SessionState.prompting)

    sess = await s.update("sessions", sess["_id"], {"lastReply": turn.reply})
    return {"turn": turn.model_dump(), "session": session_view(sess, s.persistent)}


@app.post("/api/robot/jobs")
async def create_job(body: JobCreate, request: Request):
    s = store(request)
    sess = await get_session(s, body.sessionId)
    activity = ACTIVITIES[sess["activityId"]]

    if sess["state"] != SessionState.validated.value or sess.get("pendingObjectId") != body.objectId:
        raise HTTPException(409, "object has not been validated for this session")
    if body.objectId not in activity["objectIds"] or body.objectId not in OBJECTS:
        raise HTTPException(422, "object not on allowlist")
    if body.actionId not in activity["allowedActionIds"]:
        raise HTTPException(422, "action not on allowlist")

    try:
        worker = await robot_client.health()
    except RobotWorkerError as e:
        await transition(s, sess, SessionState.needs_staff, lastReply=activity["prompts"]["robot_failed"])
        raise HTTPException(503, str(e))
    if not worker.get("ready") or worker.get("busy"):
        raise HTTPException(409, "robot is not ready")

    job = {
        "_id": new_id(),
        "sessionId": sess["_id"],
        "actionId": body.actionId,
        "objectId": body.objectId,
        "status": JobStatus.queued.value,
        "errorCode": None,
        "createdAt": now(),
        "updatedAt": now(),
    }
    await s.insert("robot_jobs", job)
    sess = await transition(s, sess, SessionState.queued, activeJobId=job["_id"], pendingObjectId=None)
    try:
        await robot_client.submit(job["_id"], body.actionId, body.objectId)
    except RobotWorkerError as e:
        job = await s.update("robot_jobs", job["_id"], {"status": JobStatus.failed.value, "errorCode": "submit_failed", "updatedAt": now()})
        await transition(s, sess, SessionState.needs_staff, lastReply=activity["prompts"]["robot_failed"])
        raise HTTPException(502, str(e))
    return job


@app.get("/api/robot/jobs/{jid}")
async def get_job(jid: str, request: Request):
    """Polled by the UI. Syncs worker status into the job and session; never invents success."""
    s = store(request)
    job = await s.get("robot_jobs", jid)
    if not job:
        raise HTTPException(404, "job not found")
    sess = await get_session(s, job["sessionId"])
    activity = ACTIVITIES[sess["activityId"]]
    status = JobStatus(job["status"])

    if status in (JobStatus.queued, JobStatus.running):
        try:
            remote = await robot_client.status(jid)
            status = JobStatus(remote["status"])
            job = await s.update("robot_jobs", jid, {"status": status.value, "errorCode": remote.get("errorCode"), "updatedAt": now()})
        except RobotWorkerError as e:
            log.error("status poll failed: %s", e)
            status = JobStatus.failed
            job = await s.update("robot_jobs", jid, {"status": status.value, "errorCode": "worker_unreachable", "updatedAt": now()})

    if sess["state"] != SessionState.stopped.value and sess.get("activeJobId") == jid:
        if status == JobStatus.running:
            sess = await advance(s, sess, SessionState.moving)
        elif status == JobStatus.verifying:
            sess = await advance(s, sess, SessionState.moving, SessionState.verifying)
        elif status == JobStatus.succeeded:
            sess = await complete_job(s, sess, job, activity)
        elif status in (JobStatus.failed, JobStatus.stopped):
            sess = await transition(s, sess, SessionState.needs_staff, lastReply=activity["prompts"]["robot_failed"])

    return {**job, "sessionState": sess["state"], "reply": sess.get("lastReply")}


async def complete_job(s: Store, sess: dict, job: dict, activity: dict) -> dict:
    sess = await advance(s, sess, SessionState.moving, SessionState.verifying)
    saved = await remember_choice(s, sess, job["objectId"])
    follow_up = activity["followUps"].get(job["objectId"], activity["prompts"]["choice"])
    return await transition(
        s,
        sess,
        SessionState.complete,
        activeJobId=None,
        lastReply=follow_up,
        preferenceSaved=saved,
        selections=[*sess.get("selections", []), job["objectId"]],
    )


@app.post("/api/robot/jobs/{jid}/verify")
async def verify_job(jid: str, body: VerifyIn, request: Request):
    """Caregiver confirms whether the object actually landed in the tray."""
    s = store(request)
    job = await s.get("robot_jobs", jid)
    if not job:
        raise HTTPException(404, "job not found")
    if job["status"] != JobStatus.verifying.value:
        raise HTTPException(409, f"job is {job['status']}, not awaiting verification")
    sess = await get_session(s, job["sessionId"])
    activity = ACTIVITIES[sess["activityId"]]
    if body.success:
        job = await s.update("robot_jobs", jid, {"status": JobStatus.succeeded.value, "updatedAt": now()})
        sess = await complete_job(s, sess, job, activity)
    else:
        job = await s.update("robot_jobs", jid, {"status": JobStatus.failed.value, "errorCode": "caregiver_rejected", "updatedAt": now()})
        sess = await transition(s, sess, SessionState.needs_staff, lastReply=activity["prompts"]["robot_failed"])
    return {**job, "sessionState": sess["state"], "reply": sess.get("lastReply")}


@app.post("/api/robot/stop")
async def robot_stop(body: StopIn, request: Request):
    """Software stop. The physical emergency stop remains the primary safety control."""
    s = store(request)
    worker_ok = True
    try:
        await robot_client.stop()
    except RobotWorkerError as e:
        log.error("software stop failed: %s", e)
        worker_ok = False
    sess = None
    if body.sessionId:
        sess = await stop_session(s, await get_session(s, body.sessionId))
        sess = await s.update("sessions", sess["_id"], {"lastReply": ACTIVITIES[sess["activityId"]]["prompts"]["stopped"]})
    return {"workerStopped": worker_ok, "session": session_view(sess, s.persistent) if sess else None}


@app.post("/api/feedback")
async def feedback(body: FeedbackIn, request: Request):
    s = store(request)
    await get_session(s, body.sessionId)
    doc = {"_id": new_id(), **body.model_dump(), "createdAt": now()}
    await s.insert("feedback", doc)
    await s.update("sessions", body.sessionId, {"optInSummary": {"enjoyed": body.enjoyed, "note": body.note}})
    return {**doc, "persistent": s.persistent}
