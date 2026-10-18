"""Math checks between the policy and the motors.

Every action chunk the Perceptron policy returns passes through ActionGuard before it reaches the
arm. Limits come from motion_limits.json (scripts/build_motion_limits.py):

- hard:     calibrated joint travel minus a buffer. Never exceeded, whatever the policy says.
- envelope: where the arm went in the recorded demonstrations, plus a margin. Values outside are
            clamped, and a chunk with too many such values is refused as out of distribution.
- step:     the largest per-frame move. Bigger jumps are cut into the allowed step.

GraspMonitor watches the follower's gripper reading, which tells us whether it holds a keyring
(it settles around 20 on a keycap and around 11 when it closes on nothing), and flags a stall or an
object still in the hand when time runs out.

LeRobot's own max_relative_target stays on underneath as a last line of defence."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

LIMITS_FILE = Path(os.getenv("MOTION_LIMITS_FILE", Path(__file__).resolve().parent.parent / "motion_limits.json"))
JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]

# Refuse a chunk when more than this share of its values had to be pulled back into the envelope.
MAX_OUT_OF_ENVELOPE = float(os.getenv("MAX_OUT_OF_ENVELOPE", "0.2"))
# Overshoots smaller than this are clamped quietly and don't count toward a refusal. The parking
# pose rests against the shoulder-lift and wrist-flex end stops, a few degrees past the hard buffer.
OOD_TOLERANCE = float(os.getenv("OUT_OF_ENVELOPE_TOLERANCE_DEG", "5"))
# Motor health: pause before the servo's own 65 C shutdown.
MAX_TEMP_C = float(os.getenv("MAX_MOTOR_TEMP_C", "60"))


@dataclass
class Limits:
    hard: dict[str, tuple[float, float]]
    envelope: dict[str, tuple[float, float]]
    step: dict[str, float]

    @classmethod
    def load(cls, path: Path = LIMITS_FILE) -> "Limits":
        d = json.loads(path.read_text())
        return cls(
            hard={j: tuple(d["hard"][j]) for j in JOINTS},
            envelope={j: tuple(d["envelope"][j]) for j in JOINTS},
            step={j: float(d["step"][j]) for j in JOINTS},
        )

    def __post_init__(self) -> None:
        for j in JOINTS:
            hlo, hhi = self.hard[j]
            elo, ehi = self.envelope[j]
            if not (hlo < hhi and elo < ehi and self.step[j] > 0):
                raise ValueError(f"bad limits for {j}")
            # The envelope may never reach past the hard limits.
            self.envelope[j] = (max(elo, hlo), min(ehi, hhi))


@dataclass
class ChunkReport:
    frames: int = 0
    clamped_hard: int = 0
    clamped_envelope: int = 0
    step_limited: int = 0
    worst: dict[str, float] = field(default_factory=dict)  # joint -> largest overshoot seen

    @property
    def values(self) -> int:
        return self.frames * len(JOINTS)

    @property
    def out_of_envelope_share(self) -> float:
        return self.clamped_envelope / self.values if self.values else 0.0

    def to_dict(self) -> dict:
        return {
            "frames": self.frames,
            "clampedHard": self.clamped_hard,
            "clampedEnvelope": self.clamped_envelope,
            "stepLimited": self.step_limited,
            "outOfEnvelopeShare": round(self.out_of_envelope_share, 3),
            "worst": {k: round(v, 2) for k, v in self.worst.items()},
        }


class GuardError(Exception):
    def __init__(self, code: str, message: str, report: ChunkReport | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.report = report


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class ActionGuard:
    def __init__(self, limits: Limits | None = None) -> None:
        self.limits = limits or Limits.load()

    def check_chunk(self, state: list[float], chunk: list[list[float]]) -> tuple[list[list[float]], ChunkReport]:
        """Return a safe copy of `chunk` and what had to change. Raises GuardError when the chunk is
        malformed or mostly outside the demonstrated envelope."""
        if len(state) != len(JOINTS) or not all(math.isfinite(v) for v in state):
            raise GuardError("bad_state", f"state must be {len(JOINTS)} finite numbers")
        if not chunk:
            raise GuardError("empty_chunk", "policy returned no actions")
        report = ChunkReport()
        safe: list[list[float]] = []
        prev = list(state)
        for k, action in enumerate(chunk):
            if len(action) != len(JOINTS):
                raise GuardError("bad_action", f"action {k} has {len(action)} values, expected {len(JOINTS)}")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in action):
                raise GuardError("bad_action", f"action {k} has a non-finite value")
            out = []
            for i, j in enumerate(JOINTS):
                v = float(action[i])
                hlo, hhi = self.limits.hard[j]
                elo, ehi = self.limits.envelope[j]
                if v < hlo or v > hhi:
                    report.clamped_hard += 1
                if v < elo or v > ehi:
                    over = (elo - v) if v < elo else (v - ehi)
                    report.worst[j] = max(report.worst.get(j, 0.0), over)
                    if over > OOD_TOLERANCE:
                        report.clamped_envelope += 1
                v = _clamp(v, elo, ehi)
                s = self.limits.step[j]
                if abs(v - prev[i]) > s:
                    report.step_limited += 1
                    v = prev[i] + math.copysign(s, v - prev[i])
                # The step cut starts from the live state, which could itself sit outside the envelope.
                v = _clamp(v, hlo, hhi)
                out.append(v)
            safe.append(out)
            prev = out
            report.frames += 1
        if report.out_of_envelope_share > MAX_OUT_OF_ENVELOPE:
            raise GuardError(
                "policy_out_of_range",
                f"{report.out_of_envelope_share:.0%} of the chunk is outside the demonstrated range",
                report,
            )
        return safe, report


def motors_ok(temps_c: dict[str, float]) -> tuple[bool, str]:
    """False with a reason if any motor is too hot to keep moving."""
    hot = {k: t for k, t in temps_c.items() if t is not None and t >= MAX_TEMP_C}
    if hot:
        name, t = max(hot.items(), key=lambda kv: kv[1])
        return False, f"{name} is at {t:.0f} C (limit {MAX_TEMP_C:.0f} C)"
    return True, ""


# ---------------------------------------------------------------- grasp monitor

HOLD_LO = float(os.getenv("GRIP_HOLD_LO", "15.5"))  # follower reading while closed on a keycap: ~19-23
HOLD_HI = float(os.getenv("GRIP_HOLD_HI", "25"))
OPEN_ABOVE = float(os.getenv("GRIP_OPEN_ABOVE", "27"))
SETTLE_FRAMES = 8


class GraspMonitor:
    """Feeds on follower gripper readings, one per control frame."""

    def __init__(self, fps: float = 30.0, stall_seconds: float = 12.0) -> None:
        self.fps = fps
        self.stall_frames = int(stall_seconds * fps)
        self.window: list[float] = []
        self.holding = False
        self.grasps = 0
        self.releases = 0
        self.frames = 0
        self.last_change = 0
        self.last_pose: list[float] | None = None
        self.still_frames = 0

    def update(self, state: list[float]) -> None:
        self.frames += 1
        g = state[-1]
        self.window = (self.window + [g])[-SETTLE_FRAMES:]
        settled = len(self.window) == SETTLE_FRAMES
        if not self.holding and settled and all(HOLD_LO <= v <= HOLD_HI for v in self.window):
            self.holding = True
            self.grasps += 1
            self.last_change = self.frames
        elif self.holding and g > OPEN_ABOVE:
            self.holding = False
            self.releases += 1
            self.last_change = self.frames
        elif self.holding and settled and all(v < HOLD_LO - 2 for v in self.window):
            self.holding = False  # closed on nothing: the keyring slipped out
            self.last_change = self.frames
        if self.last_pose is not None and max(abs(a - b) for a, b in zip(state[:-1], self.last_pose[:-1])) < 0.5:
            self.still_frames += 1
        else:
            self.still_frames = 0
        self.last_pose = list(state)

    @property
    def stalled(self) -> bool:
        """Holding something and not moving for too long: the arm is stuck mid-task."""
        return self.holding and self.still_frames >= self.stall_frames

    def summary(self) -> dict:
        return {"grasps": self.grasps, "releases": self.releases, "holding": self.holding, "stalled": self.stalled}
