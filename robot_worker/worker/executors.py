"""Job executors. Both are cancellable via a threading.Event and never retry on their own."""

import os
from pathlib import Path
import random
import threading
import time
import uuid

from .motion_guard import ActionGuard, GraspMonitor, GuardError
from .robot import Stopped

DEFAULT_START = ["black", "white", "purple"]  # docs/RECORDING_SETUP.md
# The purple switch block is wider and slicker than a keycap: squeeze it a little harder.
GRIP_CLOSE_BY_OBJECT = {"purple": float(os.getenv("SCRIPT_GRIP_CLOSE_PURPLE", "6"))}
TRAVEL_LIFT_DEG = float(os.getenv("SCRIPT_TRAVEL_LIFT_DEG", "15"))  # extra height when crossing between slots
# Retry offsets (deg of shoulder_pan) when a pick misses: same spot, then a little to each side.
SEARCH_OFFSETS_DEG = [float(x) for x in os.getenv("PICK_SEARCH_DEG", "0,2.5,-2.5,5,-5").split(",")]
HANDS_EVERY = int(os.getenv("HANDS_CHECK_EVERY_N_ACTIONS", "6"))  # ~5 checks a second at 30 fps
HANDS_CLEAR_S = float(os.getenv("HANDS_CLEAR_SECONDS", "1.5"))  # table must stay clear this long
HANDS_MAX_WAIT_S = float(os.getenv("HANDS_MAX_WAIT_SECONDS", "30"))

# Set by main.run() for each job: receives live events ({"kind": ...}) so the backend can tell the
# companion what the robot is doing. While a hook is set, the companion does the talking, so the
# laptop's own voice stays quiet to avoid two voices at once.
EVENT_HOOK = None


def emit(kind: str, **data) -> None:
    if EVENT_HOOK is not None:
        try:
            EVENT_HOOK({"kind": kind, **data, "t": time.time()})
        except Exception:  # noqa: BLE001 - reporting must never stop the robot logic
            pass


def wait_for_clear_table(robot, stop: threading.Event, say=None) -> bool:
    """If a hand is in the workspace, hold still until the table has been clear for HANDS_CLEAR_S.
    Returns True if it had to pause. Raises RobotError if the hand stays too long."""
    from .table_view import hands_in

    frame = robot.side_frame()
    if frame is None or not hands_in(frame):
        return False
    emit("paused_for_hand")
    if say and EVENT_HOOK is None:
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
                emit("resumed")
                return True
        else:
            clear_since = None
    emit("hand_timeout")
    raise RobotError("hands_in_workspace", "a hand stayed in the workspace, so the robot stopped")


def shuffle_check(spec: dict, side_png: bytes | None) -> dict | None:
    """For shuffle jobs: compare the camera's view of the row with what the shuffle must produce."""
    sid = spec.get("shuffle")
    if not sid:
        return None
    from . import shuffle_math

    expected = shuffle_math.expected_end(spec.get("start") or DEFAULT_START, sid)
    emit("checking")
    observed, visible = None, 0
    if side_png:
        import cv2
        import numpy as np

        from .row_check import read_row

        frame = cv2.imdecode(np.frombuffer(side_png, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            row = read_row(frame)
            observed, visible = row["order"], row["visible"]
    out = {
        "shuffle": sid,
        "expected": expected,
        "observed": observed,
        "visible": visible,
        "verdict": shuffle_math.verdict(expected, observed),
    }
    emit("checked", verdict=out["verdict"])
    return out


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

    def _finish_scripted(self, spec: dict, ai_check: dict, stop: threading.Event) -> bool:
        """Hybrid: the AI policy tried first. If the camera sees all three keyrings but not in the
        expected order, finish the job with the one scripted shuffle that turns what is on the table
        into the expected row. Returns True when that worked. Never runs when the camera can't see
        all three (a keyring may be in the gripper or in slot 4)."""
        from .shuffle_math import shuffle_for

        observed = ai_check.get("observed")
        if os.getenv("HYBRID_SCRIPTED", "1") != "1" or not observed or not all(observed):
            return False
        if ScriptedExecutor.missing_poses():
            return False
        sid = shuffle_for(list(observed), list(ai_check["expected"]))
        if sid is None:
            return False
        fb = ScriptedExecutor(robot=self.robot)
        fb.execute({**spec, "shuffle": sid, "start": list(observed)}, stop)
        self.last_check = {**(fb.last_check or {}), "mode": "ai+scripted", "aiCheck": ai_check, "scriptedShuffle": sid}
        return True

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
            self.last_check = {**check, **extra, "mode": "ai"}
            if check and check.get("verdict") != "ok" and self._finish_scripted(spec, check, stop):
                return
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

    @staticmethod
    def _search_offsets(data: dict, slot: int) -> list[float]:
        """Where to feel for a missed keyring: inside the middle 50% of the pans the human demos
        grasped at for this slot (poses.json demo_ranges), else the fixed PICK_SEARCH_DEG list."""
        iqr = ((data.get("demo_ranges") or {}).get(str(slot)) or {}).get("iqr", {}).get("shoulder_pan.pos")
        if not iqr:
            return SEARCH_OFFSETS_DEG
        h = round(max(1.0, (iqr[1] - iqr[0]) / 2), 2)
        return [0.0, h, -h, 2 * h, -2 * h]

    def _holding(self) -> bool:
        """The follower's gripper reading tells a keyring from nothing: ~19-23 on a keycap, ~11 empty."""
        from .motion_guard import HOLD_LO

        try:
            self._last_grip = round(self.robot.joints()["gripper.pos"], 1)
            return self._last_grip >= HOLD_LO
        except Exception:  # noqa: BLE001
            return True  # can't read it: don't block the move (the camera checks the result)

    def _scripted_shuffle(self, spec: dict, stop: threading.Event, camera: bool) -> None:
        """Pick-and-place through taught poses. With the camera calibrated: check the row first,
        and line up each pick with where the keyring really is."""
        from .robot import GRIPPER, load_poses
        from .row_check import find, find_xy, read_row
        from .shuffle_math import GRIP_CLOSE, GRIP_OPEN, GRIP_RELEASE, SHUFFLES
        from .slot_locate import load_calibration, load_spots, pick_correction, spot_problems

        data = load_poses()
        # Taught poses carry whatever the gripper was doing while teaching; the script opens and
        # closes the gripper itself, so poses only move the arm joints.
        poses = {k: {j: v for j, v in p.items() if j != GRIPPER} for k, p in data["poses"].items()}
        start = list(spec.get("start") or DEFAULT_START)
        # Off by default: with the current camera framing the corrections made picks worse (slot 3
        # sits at the image edge, slot 4 is out of view). Turn on once the camera sees all 4 slots.
        use_cam_picks = camera and os.getenv("PICK_CAMERA_CORRECTION", "0") == "1"
        cal = load_calibration(data) if use_cam_picks else {}
        pans = {s: poses[f"down_s{s}"]["shoulder_pan.pos"] for s in cal if f"down_s{s}" in poses}
        self.corrections: list[dict] = []

        if camera:
            frame = self._frame()
            seen = read_row(frame)["order"] if frame is not None else None
            if seen and all(seen) and seen != start:
                raise RobotError("start_mismatch", f"table shows {seen}, expected {start}; set the row first")
            spots = load_spots(data)
            if frame is not None and spots:
                problems = spot_problems(find_xy(frame), start + [None], spots)
                for _ in range(2):  # one odd frame shouldn't stop the robot: look again
                    if not problems:
                        break
                    time.sleep(0.5)
                    again = self._frame()
                    problems = spot_problems(find_xy(again), start + [None], spots) if again is not None else problems
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

        def high(pose: dict) -> dict:
            """The same spot, raised: shoulder_lift back by TRAVEL_LIFT_DEG (smaller lift = higher)."""
            if "shoulder_lift.pos" not in pose:
                return pose
            return {**pose, "shoulder_lift.pos": pose["shoulder_lift.pos"] - TRAVEL_LIFT_DEG}

        last_high: dict | None = None
        row: list[str | None] = [*start, None]
        move(poses["home"])
        grip(GRIP_OPEN, 0.2)
        for a, b in SHUFFLES[spec["shuffle"]].moves:
            obj = row[a - 1]
            corr = 0.0
            if cal and a in cal:
                frame = self._frame()
                found = find(frame) if frame is not None else {}
                if obj in found:
                    # Expected image x for THIS keyring on this slot (the purple block's centre sits
                    # off the gripper's centre; slot_locate.pick_correction accounts for it).
                    corr = pick_correction(found[obj][0], a, obj, cal, pans)
                    self.corrections.append({"slot": a, "object": obj, "x": round(found[obj][0], 3), "panDeg": round(corr, 2)})
            above = {**poses[f"above_s{a}"], "shoulder_pan.pos": poses[f"above_s{a}"]["shoulder_pan.pos"] + corr}
            down = {**poses[f"down_s{a}"], "shoulder_pan.pos": poses[f"down_s{a}"]["shoulder_pan.pos"] + corr}
            if last_high is not None:  # coming from the previous place: stay high until over this slot
                move(high(above))
            close = GRIP_CLOSE_BY_OBJECT.get(obj, GRIP_CLOSE)
            move(above)
            move(down)
            grip(close, 0.4)
            if not self._holding():
                # Missed: feel for it. The gripper reading tells holding from empty, so search a
                # little to each side (the camera can't see slot 4, where keyrings shift on release).
                # Lift between tries so a miss never drags the keyring; stop before placing if all fail.
                found = False
                for off in self._search_offsets(data, a):
                    grip(GRIP_OPEN, 0.2)
                    move(above)
                    a2 = {**above, "shoulder_pan.pos": above["shoulder_pan.pos"] + off}
                    d2 = {**down, "shoulder_pan.pos": down["shoulder_pan.pos"] + off}
                    move(a2)
                    move(d2)
                    grip(close, 0.4)
                    if self._holding():
                        above, found = a2, True
                        self.corrections.append({"slot": a, "object": obj, "searchDeg": off})
                        break
                if not found:
                    grip(GRIP_OPEN, 0.3)
                    move(above)
                    move(poses["home"])
                    raise RobotError("grasp_missed", f"could not pick the {obj} from slot {a} (gripper read {getattr(self, '_last_grip', '?')}, holding needs >= 15.5)")
            move(above)
            # Travel at height: a straight joint-space move between two low "above" poses dips toward
            # the table mid-way (it knocked keyrings over), so rise a little, swing across, come down.
            # Much shorter than going back to home between every pick and place.
            move(high(above))
            move(high(poses[f"above_s{b}"]))
            move(poses[f"above_s{b}"])
            move(poses[f"down_s{b}"])
            # Release gently: open just enough to let go, lift, then open fully. Snapping wide open
            # at table height flicked keyrings over at slot 4.
            grip(GRIP_RELEASE, 0.4)
            move(poses[f"above_s{b}"])
            grip(GRIP_OPEN, 0.1)
            last_high = high(poses[f"above_s{b}"])
            move(last_high)
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


class ReplayExecutor:
    """Replays the cleanest recorded human demonstration of each shuffle (replays/<shuffle>.npy,
    picked by scripts: camera-verified start and end, one grasp per move). The arm repeats exactly
    what the operator did, slowed down, with every frame through the ActionGuard and the hands
    check. It needs the keyrings where they were during recording (set them with show_slots.py
    using the recording-median poses). The motion is object-agnostic, so swap_lr replayed on its
    own result swaps back."""

    mode = "replay"
    SPEED = float(os.getenv("REPLAY_SPEED", "0.6"))  # 1.0 = as recorded
    DIR = Path(__file__).resolve().parent.parent / "replays"

    def __init__(self, robot=None) -> None:
        from .robot import SO101

        self.robot = robot or SO101()
        self.guard = ActionGuard()
        self.last_check: dict | None = None
        self.hand_pauses = 0

    def ready(self) -> bool:
        return self.DIR.exists()

    def say(self, text: str) -> None:
        from . import voice

        voice.speak(text)

    def trajectory(self, sid: str):
        import numpy as np

        path = self.DIR / f"{sid}.npy"
        if not path.exists():
            raise RobotError("replay_missing", f"no recorded trajectory for {sid}")
        traj = np.load(path)
        if self.SPEED >= 0.999:
            return traj.tolist()
        # Slow down by resampling in time (linear between recorded frames).
        n = len(traj)
        t_new = np.arange(0, n - 1, self.SPEED)
        return [list(traj[int(t)] + (traj[min(int(t) + 1, n - 1)] - traj[int(t)]) * (t - int(t))) for t in t_new]

    def execute(self, spec: dict, stop: threading.Event) -> None:
        from .robot import JOINTS

        sid = spec.get("shuffle")
        if not sid:
            raise RobotError("replay_needs_shuffle", "replay mode only runs shuffles")
        self.last_check, self.hand_pauses = None, 0
        traj = self.trajectory(sid)
        wait_for_clear_table(self.robot, stop, self.say)
        # Go to where the recording starts, slowly, then play it.
        self.robot.move_to(dict(zip(JOINTS, traj[0])), stop, 0.4)
        state = list(traj[0])
        guard_total = {"chunks": 0, "clampedHard": 0, "clampedEnvelope": 0, "stepLimited": 0}
        fps = float(os.getenv("CONTROL_FPS", "30"))
        try:
            for k in range(0, len(traj), 30):
                chunk, report = self.guard.check_chunk(state, traj[k:k + 30])
                guard_total["chunks"] += 1
                for key in ("clampedHard", "clampedEnvelope", "stepLimited"):
                    guard_total[key] += report.to_dict()[key]
                for n, action in enumerate(chunk):
                    if stop.is_set():
                        raise Stopped()
                    if n % HANDS_EVERY == 0 and wait_for_clear_table(self.robot, stop, self.say):
                        self.hand_pauses += 1  # paused for a hand; the replay resumes where it was
                    self.robot.act(action)
                    time.sleep(1 / fps)
                state = chunk[-1]
        except GuardError as e:
            raise RobotError(e.code, str(e)) from e
        side = None
        try:
            _, side, _ = self.robot.observe()
        except Exception:  # noqa: BLE001
            pass
        check = shuffle_check(spec, side) or {}
        self.last_check = {**check, "mode": "replay", "guard": guard_total, "handPauses": self.hand_pauses,
                           "frames": len(traj)}
        if check.get("verdict") == "mismatch":
            raise RobotError("shuffle_mismatch", f"expected {check['expected']}, saw {check['observed']}")
