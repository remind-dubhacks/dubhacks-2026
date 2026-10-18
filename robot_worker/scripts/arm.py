"""SO-101 helper CLI for the ReMind team. Run from robot_worker/ on the laptop wired to the arm:

    uv run python scripts/arm.py <command> [args]

Setup (once per arm):     ports, calibrate follower, calibrate leader
Teleop / data collection: teleop, record
Scripted control:         read, teach <pose>, goto <pose>, gripper <0-100>, run <sequence>, relax

Settings come from robot_worker/.env (see .env.example). Keep hands out of the workspace while the
arm is powered, and keep the physical emergency stop / power switch within reach."""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from worker.robot import JOINTS, SO101, Stopped, load_poses, run_sequence, save_poses  # noqa: E402


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        sys.exit(f"Set {name} in robot_worker/.env first (run `arm.py ports` to find serial ports).")
    return value


def follower_args() -> list[str]:
    return ["--robot.type=so101_follower", f"--robot.port={env('SO101_PORT')}", f"--robot.id={env('SO101_ID', 'remind_follower')}"]


def leader_args() -> list[str]:
    return ["--teleop.type=so101_leader", f"--teleop.port={env('LEADER_PORT')}", f"--teleop.id={env('LEADER_ID', 'remind_leader')}"]


def cameras_arg() -> str:
    side, wrist = os.getenv("SIDE_CAMERA_INDEX", "0"), os.getenv("WRIST_CAMERA_INDEX", "1")
    cam = "{{type: opencv, index_or_path: {}, width: 640, height: 480, fps: 30}}"
    return f"--robot.cameras={{ side: {cam.format(side)}, wrist: {cam.format(wrist)} }}"


def lerobot(cmd: str, *args: str) -> None:
    exe = shutil.which(cmd)
    if not exe:
        sys.exit(f"`{cmd}` not found. Install the hardware extra: uv sync --extra hardware")
    print("$", cmd, " ".join(args))
    sys.exit(subprocess.call([exe, *args]))


def fmt(joints: dict[str, float]) -> str:
    return "  ".join(f"{j.removesuffix('.pos')}={joints[j]:7.2f}" for j in JOINTS)


# ---------- setup ----------


def cmd_ports(_):
    ports = sorted(set(glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")))
    print("\n".join(ports) if ports else "No robot serial ports found. Check USB and power.")
    print("\nTo tell leader from follower: unplug one arm's USB and run `lerobot-find-port`.")


def cmd_calibrate(a):
    lerobot("lerobot-calibrate", *(follower_args() if a.arm == "follower" else leader_args()))


# ---------- teleop & recording ----------


def cmd_teleop(a):
    args = follower_args() + leader_args()
    if a.cameras:
        args += [cameras_arg(), "--display_data=true"]
    lerobot("lerobot-teleoperate", *args)


def cmd_record(a):
    lerobot(
        "lerobot-record",
        *follower_args(),
        *leader_args(),
        cameras_arg(),
        "--display_data=true",
        f"--dataset.repo_id={a.repo}",
        f"--dataset.single_task={a.task}",
        f"--dataset.num_episodes={a.episodes}",
        f"--dataset.episode_time_s={a.episode_s}",
        f"--dataset.reset_time_s={a.reset_s}",
        "--dataset.fps=30",
        f"--dataset.push_to_hub={'true' if a.push else 'false'}",
    )


# ---------- scripted control ----------


def connect(read_only: bool = False) -> SO101:
    print("Connecting to follower arm…")
    return SO101(cameras=False, calibrate=not read_only, read_only=read_only)


def cmd_read(a):
    arm = connect(read_only=True)  # motors stay as they are, so you can move the arm by hand
    try:
        while True:
            print("\r" + fmt(arm.joints()), end="", flush=True)
            if not a.follow:
                print()
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        arm.disconnect()


def cmd_teach(a):
    """Torque off, move the arm by hand, press Enter to save the pose."""
    arm = connect()
    data = load_poses()
    try:
        input("Support the arm with one hand: torque turns OFF and the arm will go limp. Press Enter…")
        arm.torque(False)
        names = a.names
        for name in names:
            input(f"Move the arm to '{name}' and press Enter to save it…")
            data["poses"][name] = {k: round(v, 2) for k, v in arm.joints().items()}
            print(f"  {name}: {fmt(data['poses'][name])}")
        save_poses(data)
        print(f"Saved {len(names)} pose(s) to poses.json")
        input("Hold the arm: torque turns back ON at its current pose. Press Enter…")
        arm.torque(True)
    finally:
        arm.disconnect()


def with_stop(fn):
    """Run a motion; Ctrl+C stops at the next control step and holds position."""
    stop = threading.Event()
    try:
        fn(stop)
    except KeyboardInterrupt:
        stop.set()
        print("\nStopped (holding position).")
    except Stopped:
        print("\nStopped.")


def cmd_goto(a):
    pose = load_poses()["poses"].get(a.pose)
    if pose is None:
        sys.exit(f"No pose named {a.pose!r}. Teach it first: arm.py teach {a.pose}")
    arm = connect()
    try:
        with_stop(lambda stop: arm.move_to(pose, stop, a.speed))
        print(fmt(arm.joints()))
    finally:
        arm.disconnect()


def cmd_gripper(a):
    arm = connect()
    try:
        with_stop(lambda stop: arm.gripper(a.value, stop))
    finally:
        arm.disconnect()


def cmd_run(a):
    arm = connect()
    try:
        for i in range(a.repeat):
            input(f"[{i + 1}/{a.repeat}] Workspace clear and object in place? Press Enter to run '{a.sequence}'…")
            t0 = time.monotonic()
            with_stop(lambda stop: run_sequence(arm, a.sequence, stop, a.speed))
            print(f"Done in {time.monotonic() - t0:.1f}s. Record whether it succeeded: this is your real success rate.")
    finally:
        arm.disconnect()


def cmd_relax(_):
    arm = connect()
    input("Support the arm: torque turns OFF and it will drop. Press Enter…")
    arm.torque(False)
    arm.disconnect()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="list robot serial ports").set_defaults(fn=cmd_ports)

    c = sub.add_parser("calibrate", help="run LeRobot calibration for one arm")
    c.add_argument("arm", choices=["follower", "leader"])
    c.set_defaults(fn=cmd_calibrate)

    t = sub.add_parser("teleop", help="drive the follower with the leader arm")
    t.add_argument("--cameras", action="store_true", help="also stream side/wrist cameras")
    t.set_defaults(fn=cmd_teleop)

    r = sub.add_parser("record", help="record LeRobot teleop episodes for Perceptron training")
    r.add_argument("--repo", required=True, help="dataset repo id, e.g. your-hf-user/remind-tea")
    r.add_argument("--task", default="pick up the tea box and place it in the tray")
    r.add_argument("--episodes", type=int, default=20)
    r.add_argument("--episode-s", dest="episode_s", type=int, default=20)
    r.add_argument("--reset-s", dest="reset_s", type=int, default=10)
    r.add_argument("--push", action="store_true", help="push to Hugging Face Hub when done")
    r.set_defaults(fn=cmd_record)

    rd = sub.add_parser("read", help="print current joint positions")
    rd.add_argument("--follow", action="store_true", help="keep printing until Ctrl+C")
    rd.set_defaults(fn=cmd_read)

    te = sub.add_parser("teach", help="save poses by moving the arm by hand")
    te.add_argument("names", nargs="+", help="pose names, e.g. home above_tea grasp_tea")
    te.set_defaults(fn=cmd_teach)

    g = sub.add_parser("goto", help="move smoothly to a saved pose")
    g.add_argument("pose")
    g.add_argument("--speed", type=float, default=1.0, help="speed multiplier (default 1.0)")
    g.set_defaults(fn=cmd_goto)

    gr = sub.add_parser("gripper", help="set gripper opening 0-100")
    gr.add_argument("value", type=float)
    gr.set_defaults(fn=cmd_gripper)

    ru = sub.add_parser("run", help="run a saved sequence (e.g. tea, coffee)")
    ru.add_argument("sequence")
    ru.add_argument("--repeat", type=int, default=1, help="run N trials to measure success rate")
    ru.add_argument("--speed", type=float, default=1.0)
    ru.set_defaults(fn=cmd_run)

    sub.add_parser("relax", help="turn torque off (support the arm first)").set_defaults(fn=cmd_relax)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
