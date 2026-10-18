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
        self.robot = SO101()
        self.guard = ActionGuard()
        self.last_check: dict | None = None
        self.hand_pauses = 0

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
        grant = self.client.grant(f"remind-{uuid.uuid4().hex[:12]}", ttl_seconds=600)
        try:
            self.client.create_session(grant, instruction, self.contract_id)
            t0 = time.monotonic()
            seq = 0
            while time.monotonic() - t0 < self.max_seconds:
                if stop.is_set():
                    raise Stopped()
                state, side, wrist = self.robot.observe()
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
            try:
                self.client.delete_session(grant)
            except Exception:  # noqa: BLE001
                pass


class ScriptedExecutor:
    """Replays a taught waypoint sequence from poses.json. A reliable fallback for fixed pickup
    positions; label it as scripted (not a learned policy) in the demo."""

    mode = "scripted"

    def __init__(self) -> None:
        from .robot import SO101

        self.robot = SO101(cameras=False)

    def ready(self) -> bool:
        return True

    def execute(self, spec: dict, stop: threading.Event) -> None:
        from .robot import run_sequence

        try:
            run_sequence(self.robot, spec["sequence"], stop)
        except (Stopped, RobotError):
            raise
        except KeyError as e:
            raise RobotError("sequence_missing", str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise RobotError("motion_error", str(e)) from e
