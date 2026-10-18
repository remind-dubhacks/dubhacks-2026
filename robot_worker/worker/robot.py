"""SO-101 hardware adapter built on LeRobot.

LeRobot's API moves quickly. Check these imports and config fields against the installed version,
and use the ports, calibration id and camera indices the Perceptron mentors set up."""

import io
import os

# Order required by the Perceptron contract (docs/PERCEPTRON_API.md §1).
JOINTS = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"]


def _png(frame) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, format="PNG")
    return buf.getvalue()


class SO101:
    def __init__(self) -> None:
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        from lerobot.robots.so101_follower import SO101Follower, SO101FollowerConfig

        cam = lambda idx: OpenCVCameraConfig(index_or_path=idx, width=640, height=480, fps=30)  # noqa: E731
        config = SO101FollowerConfig(
            port=os.environ["SO101_PORT"],
            id=os.getenv("SO101_ID", "remind_follower"),
            cameras={
                "side": cam(int(os.getenv("SIDE_CAMERA_INDEX", "0"))),
                "wrist": cam(int(os.getenv("WRIST_CAMERA_INDEX", "1"))),
            },
        )
        self.robot = SO101Follower(config)
        self.robot.connect()

    def observe(self) -> tuple[list[float], bytes, bytes]:
        obs = self.robot.get_observation()
        state = [float(obs[j]) for j in JOINTS]
        return state, _png(obs["side"]), _png(obs["wrist"])

    def act(self, action: list[float]) -> None:
        self.robot.send_action(dict(zip(JOINTS, action)))

    def disconnect(self) -> None:
        self.robot.disconnect()
