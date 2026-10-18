from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class SessionState(str, Enum):
    idle = "idle"
    consented = "consented"
    prompting = "prompting"
    choice_received = "choice_received"
    validated = "validated"
    queued = "queued"
    moving = "moving"
    verifying = "verifying"
    complete = "complete"
    stopped = "stopped"
    needs_staff = "needs_staff"


# Spec §5. `stopped` and `needs_staff` are reachable from anywhere (handled in transition()).
TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.idle: {SessionState.consented},
    SessionState.consented: {SessionState.prompting},
    SessionState.prompting: {SessionState.choice_received},
    SessionState.choice_received: {SessionState.validated, SessionState.prompting},
    SessionState.validated: {SessionState.queued, SessionState.prompting},
    SessionState.queued: {SessionState.moving},
    SessionState.moving: {SessionState.verifying},
    SessionState.verifying: {SessionState.complete},
    SessionState.complete: {SessionState.prompting},
    SessionState.needs_staff: {SessionState.prompting},  # caregiver resumes
    SessionState.stopped: set(),
}

ROBOT_BUSY = {SessionState.queued, SessionState.moving, SessionState.verifying}


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    verifying = "verifying"  # motion finished; waiting for caregiver to confirm the result
    succeeded = "succeeded"
    failed = "failed"
    stopped = "stopped"


TERMINAL_JOB = {JobStatus.succeeded, JobStatus.failed, JobStatus.stopped}

Intent = Literal["begin", "select_object", "help", "repeat", "skip", "stop", "chat", "unclear"]


class AgentTurn(BaseModel):
    """Structured agent output (spec §7). The server validates it; it never drives motors directly."""

    reply: str
    intent: Intent
    objectId: str | None = None
    requestedAction: str | None = None
    needsConfirmation: bool = False


class ConsentFlags(BaseModel):
    sessionConsent: bool = True
    rememberPreferences: bool = True


class ParticipantIn(BaseModel):
    alias: str
    interestTags: list[str] = []
    communicationPreferences: dict = {}
    consentFlags: ConsentFlags = ConsentFlags()


class SessionCreate(BaseModel):
    participantId: str
    activityId: str = "sort_and_share"
    caregiverApproved: bool = False


class TurnIn(BaseModel):
    sessionId: str
    text: str = Field(max_length=500)


class JobCreate(BaseModel):
    sessionId: str
    objectId: str
    actionId: str = "move_known_object"


class VerifyIn(BaseModel):
    success: bool


class StopIn(BaseModel):
    sessionId: str | None = None


class FeedbackIn(BaseModel):
    sessionId: str
    enjoyed: bool | None = None
    note: str | None = Field(default=None, max_length=1000)
