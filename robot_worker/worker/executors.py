"""Job executors. Both are cancellable via a threading.Event and never retry on their own."""

import os
import random
import threading
import time
import uuid

from .motion_guard import ActionGuard, GraspMonitor, GuardError
from .robot import Stopped

DEFAULT_START = ["black", "white", "purple"]  # docs/RECORDING_SETUP.md
HANDS_EVERY = int(os.getenv("HANDS_CHECK_EVERY_N_ACTIONS", "6"))  # ~5 checks a second at 30 fps
HANDS_CLEAR_S = float(os.getenv("HANDS_CLEAR_SECONDS", "1.5"))  # table must stay clear this long
HANDS_MAX_WAIT_S = float(os.getenv("HANDS_MAX_WAIT_SECONDS", "30"))


def wait_for_clear_table(robot, stop: threading.Event, say=None) -> bool:
    """If a hand is in the workspace, hold still until the table has been clear for HANDS_CLEAR_S.
    Returns True if it had to pause. Raises RobotError if the hand stays too long."""
    from .table_view import hands_in

    frame = robot.side_frame()
    if frame is None or not hands_in(frame):
        return False
    if say:
        say("I'll wait while your hand is on the table.")
    start = time.monotonic()
    clear_since = None
    while time.monotonic() - start < HANDS_MAX_WAIT_S:
        if stop.wait(0.1):
            raise Stopped()
        frame = robot.side_frame()
        if frame is not None and not hands_in(frame):
            clear_since = clear_since or time.monotonic()
            if time.monotonic() - clear_since >= HANDS_CLEAR_S:
                return True
        else:
            clear_since = None
    raise RobotError("hands_in_workspace", "a hand stayed in the workspace, so the robot stopped")


def shuffle_check(spec: dict, side_png: bytes | None) -> dict | None:
    """For shuffle jobs: compare the camera's view of the row with what the shuffle must produce."""
    sid = spec.get("shuffle")
    if not sid:
        return None
    from . import shuffle_math

    expected = shuffle_math.expected_end(spec.get("start") or DEFAULT_START, sid)
    observed, visible = None, 0
    if side_png:
        import cv2
        import numpy as np

        from .row_check import read_row

        frame = cv2.imdecode(np.frombuffer(side_png, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            row = read_row(frame)
            observed, visible = row["order"], row["visible"]
    return {
        "shuffle": sid,
        "expected": expected,
        "observed": observed,
        "visible": visible,
        "verdict": shuffle_math.verdict(expected, observed),
    }


class RobotError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class MockExecutor:
    """Simulates a pick-and-place so the UI and backend can be built before the arm is ready."""

    mode = "mock"

    def __init__(self) -> None:
        self.duration = float(os.getenv("MOCK_DURATION_S", "4"))
        self.fail_rate = float(os.getenv("MOCK_FAIL_RATE", "0"))
        self.last_check: dict | None = None

    def ready(self) -> bool:
        return True

    def execute(self, spec: dict, stop: threading.Event) -> None:
        end = time.monotonic() + self.duration
        while time.monotonic() < end:
            if stop.wait(0.1):
                raise Stopped()
        if random.random() < self.fail_rate:
            raise RobotError("grasp_failed", "simulated grasp failure")
        check = shuffle_check(spec, None)
        if check:  # no camera in mock mode: pretend the row came out exactly right
            check.update(observed=check["expected"], visible=3, verdict="ok", simulated=True)
        self.last_check = check


class PerceptronExecutor:
    """Runs the Perceptron-hosted policy on the real SO-101 for one episode."""

    mode = "perceptron"

    def __init__(self) -> None:
        from .perceptron import PerceptronClient
        from .robot import SO101

        self.client = PerceptronClient(os.environ["PERCEPTRON_API_KEY"], os.environ["PERCEPTRON_DEPLOYMENT_ID"])
        contract = self.client.fetch_contract()
        self.contract_id = contract.get("contract_id") or contract.get("contract_sha256") or contract["id"]  # live contract has contract_sha256
        # The contract says how many actions of each chunk to run before predicting again.
        spec = contract.get("contract") or contract
        self.stride = int((spec.get("rtc") or {}).get("execution_stride") or 0) or None
        self.fps = float(os.getenv("CONTROL_FPS", "30"))
        self.max_seconds = float(os.getenv("MAX_EPISODE_SECONDS", "25"))
        self.blank_wrist = os.getenv("BLANK_WRIST_CAMERA", "0") == "1"
        self.robot = SO101()
        self.guard = ActionGuard()
        self.last_check: dict | None = None
        self.hand_pauses = 0

    GRANT_TTL_S = int(os.getenv("PERCEPTRON_SESSION_TTL_S", "3600"))

    def _get_grant(self):
        """One long-lived session, reused across jobs and refreshed shortly before it expires."""
        g = getattr(self, "_grant", None)
        if g is None or g.expires_at - time.time() < 120:
            g = self.client.grant(f"remind-{uuid.uuid4().hex[:12]}", ttl_seconds=self.GRANT_TTL_S)
            self._grant = g
        return g

    @staticmethod
    def say(text: str) -> None:
        from . import voice

        voice.speak(text)

    def ready(self) -> bool:
        return self.client.deployment().get("status") == "ready"

    def execute(self, spec: dict, stop: threading.Event) -> None:
        instruction = spec["instruction"]
        self.last_check = None
        monitor = GraspMonitor(self.fps)
        guard_total = {"chunks": 0, "clampedHard": 0, "clampedEnvelope": 0, "stepLimited": 0}
        side = None
        self.hand_pauses = 0
        wait_for_clear_table(self.robot, stop, self.say)
        try:
            grant = self._get_grant()
        except Exception as e:  # noqa: BLE001
            # Perceptron refused or is unreachable (e.g. 409 deployment_recovering). The arm has not
            # moved yet, so a shuffle can safely run from taught poses instead.
            if spec.get("shuffle") and os.getenv("SCRIPTED_FALLBACK", "1") == "1" and not ScriptedExecutor.missing_poses():
                fb = ScriptedExecutor(robot=self.robot)
                fb.execute(spec, stop)
                self.last_check = {**(fb.last_check or {}), "mode": "scripted-fallback", "policyError": str(e)[:200]}
                return
            raise RobotError("policy_unavailable", str(e)[:300]) from e
        try:
            try:
                self.client.create_session(grant, instruction, self.contract_id)
            except Exception:  # noqa: BLE001
                # The kept session may have expired: start a fresh one once.
                self._grant = None
                grant = self._get_grant()
                self.client.create_session(grant, instruction, self.contract_id)
            t0 = time.monotonic()
            seq = 0
            while time.monotonic() - t0 < self.max_seconds:
                if stop.is_set():
                    raise Stopped()
                state, side, wrist = self.robot.observe()
                if getattr(self, "blank_wrist", False):
                    wrist = _black_png_like(wrist)  # match a model trained while the wrist camera was black
                monitor.update(state)
                if monitor.stalled:
                    raise RobotError("arm_stalled", "holding an object without moving")
                result = self.client.predict(
                    grant,
                    {
                        "contract_id": self.contract_id,
                        "observation_id": f"obs-{seq:05d}",
                        "sequence": seq,
                        "timestamp_seconds": time.monotonic() - t0,
                        "state": state,
                        "image_encoding": "png",
                    },
                    side,
                    wrist,
                )
                seq += 1
                # TODO: confirm the action-chunk field name and execution timing in the contract.
                chunk = result.get("actions") or result.get("action_chunk") or []
                if not chunk:
                    raise RobotError("empty_action_chunk", str(result)[:200])
                if self.stride:
                    chunk = chunk[: self.stride]
                try:
                    chunk, report = self.guard.check_chunk(state, chunk)
                except GuardError as e:
                    raise RobotError(e.code, str(e)) from e
                guard_total["chunks"] += 1
                for k in ("clampedHard", "clampedEnvelope", "stepLimited"):
                    guard_total[k] += report.to_dict()[k]
                for n, action in enumerate(chunk):
                    if stop.is_set():
                        raise Stopped()
                    if n % HANDS_EVERY == 0 and wait_for_clear_table(self.robot, stop, self.say):
                        self.hand_pauses += 1
                        break  # the table may have changed: get a fresh plan from the policy
                    self.robot.act(action)
                    time.sleep(1 / self.fps)
            # The policy ran its full episode budget. Now check the result instead of assuming it.
            state, side, _ = self.robot.observe()
            monitor.update(state)
            if monitor.holding:
                raise RobotError("object_still_held", "time ran out with a keyring still in the gripper")
            check = shuffle_check(spec, side) or {}
            extra = {"grasp": monitor.summary(), "guard": guard_total, "handPauses": self.hand_pauses}
            self.last_check = {**check, **extra}
            if check.get("verdict") == "mismatch":
                raise RobotError("shuffle_mismatch", f"expected {check['expected']}, saw {check['observed']}")
        except Stopped:
            raise
        except RobotError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RobotError("policy_error", str(e)) from e
        finally:
            # Keep the session for the next job: closing it makes Perceptron spend ~5 minutes
            # "recovering" (409 deployment_recovering). Reset starts a new episode instead.
            try:
                self.client.reset(grant)
            except Exception:  # noqa: BLE001
                self._grant = None


def _black_png_like(png: bytes, _cache: dict = {}) -> bytes:  # noqa: B006
    """An all-black PNG the size of `png` (for a model trained while the wrist camera was black)."""
    if "png" not in _cache:
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        _cache["png"] = cv2.imencode(".png", np.zeros_like(img))[1].tobytes()
    return _cache["png"]


class ScriptedExecutor:
    """Replays taught poses from poses.json. For shuffles it builds the pick-and-place steps from
    shuffle_math, so it works without Perceptron. Label it as scripted (not a learned policy) in
    the demo. Also used by PerceptronExecutor as a fallback when Perceptron refuses a session."""

    mode = "scripted"
    SPEED = float(os.getenv("SCRIPT_SPEED_SCALE", "0.6"))

    def __init__(self, robot=None) -> None:
        from .robot import SO101

        self.robot = robot or SO101(cameras=os.getenv("SCRIPTED_CAMERAS", "1") == "1")
        self.last_check: dict | None = None
        self.hand_pauses = 0

    def ready(self) -> bool:
        return True

    @staticmethod
    def missing_poses() -> list[str]:
        from .robot import load_poses
        from .shuffle_math import SCRIPT_POSES

        taught = load_poses()["poses"]
        return [p for p in SCRIPT_POSES if p not in taught]

    def say(self, text: str) -> None:
        from . import voice

        voice.speak(text)

    def _frame(self):
        """Current side-camera frame (BGR) or None."""
        try:
            f = self.robot.side_frame()
            if f is not None:
                return f
        except Exception:  # noqa: BLE001
            pass
        try:
            import cv2
            import numpy as np

            _, side, _ = self.robot.observe()
            return cv2.imdecode(np.frombuffer(side, np.uint8), cv2.IMREAD_COLOR) if side else None
        except Exception:  # noqa: BLE001
            return None

    def _holding(self) -> bool:
        """The follower's gripper reading tells a keyring from nothing: ~19-23 on a keycap, ~11 empty."""
        from .motion_guard import HOLD_LO

        try:
            return self.robot.joints()["gripper.pos"] >= HOLD_LO
        except Exception:  # noqa: BLE001
            return True  # can't read it: don't block the move (the camera checks the result)

    def _scripted_shuffle(self, spec: dict, stop: threading.Event, camera: bool) -> None:
        """Pick-and-place through taught poses. With the camera calibrated: check the row first,
        and line up each pick with where the keyring really is."""
        from .robot import GRIPPER, load_poses
        from .row_check import find, find_xy, read_row
        from .shuffle_math import GRIP_CLOSE, GRIP_OPEN, SHUFFLES
        from .slot_locate import fit, load_calibration, load_spots, pan_correction, spot_problems

        data = load_poses()
        # Taught poses carry whatever the gripper was doing while teaching; the script opens and
        # closes the gripper itself, so poses only move the arm joints.
        poses = {k: {j: v for j, v in p.items() if j != GRIPPER} for k, p in data["poses"].items()}
        start = list(spec.get("start") or DEFAULT_START)
        # Off by default: with the current camera framing the corrections made picks worse (slot 3
        # sits at the image edge, slot 4 is out of view). Turn on once the camera sees all 4 slots.
        use_cam_picks = camera and os.getenv("PICK_CAMERA_CORRECTION", "0") == "1"
        cal = load_calibration(data) if use_cam_picks else {}
        slope = None
        if cal:
            try:
                slope, _ = fit(cal, {s: poses[f"down_s{s}"]["shoulder_pan.pos"] for s in cal})
            except ValueError:
                cal = {}
        self.corrections: list[dict] = []

        if camera:
            frame = self._frame()
            seen = read_row(frame)["order"] if frame is not None else None
            if seen and all(seen) and seen != start:
                raise RobotError("start_mismatch", f"table shows {seen}, expected {start}; set the row first")
            spots = load_spots(data)
            if frame is not None and spots:
                problems = spot_problems(find_xy(frame), start + [None], spots)
                if problems:
                    self.last_check = {"spots": problems}
                    self.say(" ".join(p["say"] for p in problems))
                    raise RobotError("keyring_off_spot", " ".join(p["sayVi"] for p in problems))

        def move(pose: dict) -> None:
            self.robot.move_to(pose, stop, self.SPEED)

        def grip(v: float, wait: float) -> None:
            self.robot.gripper(v, stop)
            if stop.wait(wait):
                raise Stopped()

        row: list[str | None] = [*start, None]
        move(poses["home"])
        grip(GRIP_OPEN, 0.2)
        for a, b in SHUFFLES[spec["shuffle"]].moves:
            obj = row[a - 1]
            corr = 0.0
            if cal and slope is not None and a in cal:
                frame = self._frame()
                found = find(frame) if frame is not None else {}
                if obj in found:
                    corr = pan_correction(found[obj][0], a, cal, slope)
                    self.corrections.append({"slot": a, "object": obj, "x": round(found[obj][0], 3), "panDeg": round(corr, 2)})
            above = {**poses[f"above_s{a}"], "shoulder_pan.pos": poses[f"above_s{a}"]["shoulder_pan.pos"] + corr}
            down = {**poses[f"down_s{a}"], "shoulder_pan.pos": poses[f"down_s{a}"]["shoulder_pan.pos"] + corr}
            move(above)
            move(down)
            grip(GRIP_CLOSE, 0.4)
            if not self._holding():
                # Missed: open, try once more from the same spot, then stop before placing so a
                # missed keyring is never knocked by the next move.
                grip(GRIP_OPEN, 0.3)
                grip(GRIP_CLOSE, 0.4)
                if not self._holding():
                    grip(GRIP_OPEN, 0.3)
                    move(above)
                    move(poses["home"])
                    raise RobotError("grasp_missed", f"could not pick the {obj} from slot {a}")
            move(above)
            # Travel high: a straight joint-space move between two low "above" poses dips toward the
            # table mid-way and knocked keyrings over in the first arm tests.
            move(poses["home"])
            move(poses[f"above_s{b}"])
            move(poses[f"down_s{b}"])
            grip(GRIP_OPEN, 0.3)
            move(poses[f"above_s{b}"])
            move(poses["home"])
            row[b - 1], row[a - 1] = obj, None
        move(poses["home"])

    def execute(self, spec: dict, stop: threading.Event) -> None:
        from .robot import run_sequence

        self.last_check = None
        has_camera = hasattr(self.robot, "side_frame") and getattr(getattr(self.robot, "robot", None), "cameras", None)
        try:
            if has_camera:
                wait_for_clear_table(self.robot, stop, self.say)
            if spec.get("shuffle"):
                missing = self.missing_poses()
                if missing:
                    raise RobotError("poses_missing", "teach these poses first: " + ", ".join(missing))
                self._scripted_shuffle(spec, stop, bool(has_camera))
            else:
                run_sequence(self.robot, spec["sequence"], stop)
        except (Stopped, RobotError):
            raise
        except KeyError as e:
            raise RobotError("sequence_missing", str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise RobotError("motion_error", str(e)) from e
        side = None
        if has_camera:
            try:
                _, side, _ = self.robot.observe()
            except Exception:  # noqa: BLE001
                side = None
        check = shuffle_check(spec, side)
        if check:
            self.last_check = {**check, "mode": "scripted", "pickCorrections": getattr(self, "corrections", [])}
            if check["verdict"] == "mismatch":
                raise RobotError("shuffle_mismatch", f"expected {check['expected']}, saw {check['observed']}")
