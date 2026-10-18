"""SO-101 hardware adapter built on LeRobot.

LeRobot's API moves quickly. Check these imports and config fields against the installed version,
and use the ports, calibration ids and camera indices the Perceptron mentors set up."""

import io
import json
import os
import threading
import time
from pathlib import Path

# Order required by the Perceptron contract (docs/PERCEPTRON_API.md §1).
JOINTS = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"]
GRIPPER = "gripper.pos"

POSES_FILE = Path(os.getenv("POSES_FILE", Path(__file__).resolve().parent.parent / "poses.json"))

# Joint speed limits for scripted moves: arm joints in deg/s, gripper in units (0-100)/s.
ARM_SPEED = float(os.getenv("ARM_SPEED_DEG_S", "30"))
GRIPPER_SPEED = float(os.getenv("GRIPPER_SPEED_S", "60"))
CONTROL_HZ = float(os.getenv("CONTROL_FPS", "30"))


class Stopped(Exception):
    pass


def _import_follower():
    try:
        from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig
    except ImportError:  # newer LeRobot layouts
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig  # type: ignore
    return SO101Follower, SO101FollowerConfig


def _png(frame) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, format="PNG")
    return buf.getvalue()


def camera_config() -> dict:
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig

    cam = lambda idx: OpenCVCameraConfig(index_or_path=idx, width=640, height=480, fps=30)  # noqa: E731
    return {
        "side": cam(int(os.getenv("SIDE_CAMERA_INDEX", "0"))),
        "wrist": cam(int(os.getenv("WRIST_CAMERA_INDEX", "1"))),
    }


class SO101:
    def __init__(self, cameras: bool = True, calibrate: bool = False, read_only: bool = False) -> None:
        SO101Follower, SO101FollowerConfig = _import_follower()
        config = SO101FollowerConfig(
            port=os.environ["SO101_PORT"],
            id=os.getenv("SO101_ID", "remind_follower"),
            cameras=camera_config() if cameras else {},
            use_degrees=True,  # Perceptron expects degrees for arm joints, 0-100 for the gripper
            # Caps how far any joint may move in a single command (safety net for policy output).
            max_relative_target=float(os.getenv("MAX_RELATIVE_TARGET", "10")),
            # Hold position when a script exits instead of letting the arm drop. Use `arm.py relax`
            # (while supporting the arm) to turn torque off deliberately.
            disable_torque_on_disconnect=False,
        )
        self.robot = SO101Follower(config)
        if read_only:
            # Open the bus only: skips configure(), which would switch torque on and lock the arm.
            self.robot.bus.connect()
        else:
            self.robot.connect(calibrate=calibrate)
        if not self.robot.is_calibrated:
            self.robot.disconnect()
            raise RuntimeError("Follower arm is not calibrated. Run: uv run python scripts/arm.py calibrate follower")

    # ----- policy I/O -----

    def observe(self) -> tuple[list[float], bytes, bytes]:
        obs = self.robot.get_observation()
        state = [float(obs[j]) for j in JOINTS]
        return state, _png(obs["side"]), _png(obs["wrist"])

    def side_frame(self):
        """Latest side-camera frame as BGR (for the hands check), without a full observation."""
        import cv2

        cam = self.robot.cameras.get("side")
        if cam is None:
            return None
        for _ in range(4):  # the USB camera occasionally misses its 200 ms frame deadline
            try:
                return cv2.cvtColor(cam.async_read(), cv2.COLOR_RGB2BGR)
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
        return None

    def act(self, action: list[float]) -> None:
        self.robot.send_action(dict(zip(JOINTS, action)))

    # ----- scripted control -----

    def joints(self) -> dict[str, float]:
        pos = self.robot.bus.sync_read("Present_Position", num_retry=5)
        return {j: float(pos[j.removesuffix(".pos")]) for j in JOINTS}

    def torque(self, on: bool) -> None:
        bus = self.robot.bus
        bus.enable_torque() if on else bus.disable_torque()

    def move_to(self, target: dict[str, float], stop: threading.Event | None = None, speed_scale: float = 1.0) -> None:
        """Linearly interpolate in joint space from the current pose to `target` under speed limits.
        Joints missing from `target` keep their current value."""
        start = self.joints()
        goal = {j: float(target.get(j, start[j])) for j in JOINTS}
        duration = max(
            abs(goal[j] - start[j]) / ((GRIPPER_SPEED if j == GRIPPER else ARM_SPEED) * speed_scale) for j in JOINTS
        )
        steps = max(1, int(duration * CONTROL_HZ))
        for i in range(1, steps + 1):
            if stop is not None and stop.is_set():
                raise Stopped()
            a = i / steps
            self.robot.send_action({j: start[j] + (goal[j] - start[j]) * a for j in JOINTS})
            time.sleep(1 / CONTROL_HZ)

    def gripper(self, value: float, stop: threading.Event | None = None) -> None:
        self.move_to({GRIPPER: value}, stop)

    def disconnect(self) -> None:
        self.robot.disconnect()


# ----- poses and sequences (robot_worker/poses.json) -----


def load_poses() -> dict:
    if POSES_FILE.exists():
        return json.loads(POSES_FILE.read_text())
    return {"poses": {}, "sequences": {}}


def save_poses(data: dict) -> None:
    POSES_FILE.write_text(json.dumps(data, indent=2) + "\n")


def run_sequence(arm: SO101, name: str, stop: threading.Event | None = None, speed_scale: float = 1.0) -> None:
    """Run a named sequence. Each step is a pose name, {"gripper": 0-100}, or {"wait": seconds}."""
    data = load_poses()
    steps = data["sequences"].get(name)
    if steps is None:
        raise KeyError(f"no sequence named {name!r} in {POSES_FILE}")
    run_steps(arm, steps, data["poses"], stop, speed_scale, name)


def run_steps(arm: SO101, steps: list, poses: dict, stop: threading.Event | None = None, speed_scale: float = 1.0, name: str = "steps") -> None:
    for step in steps:
        if stop is not None and stop.is_set():
            raise Stopped()
        if isinstance(step, str):
            if step not in poses:
                raise KeyError(f"sequence {name!r} uses unknown pose {step!r}")
            arm.move_to(poses[step], stop, speed_scale)
        elif "gripper" in step:
            arm.gripper(float(step["gripper"]), stop)
        elif "wait" in step:
            if stop is not None and stop.wait(float(step["wait"])):
                raise Stopped()
            elif stop is None:
                time.sleep(float(step["wait"]))
