# Robot worker & SO-101 scripts

Run these on the laptop the arms are plugged into. Everything goes from this folder.

```bash
uv sync --extra hardware          # installs LeRobot (+ PyTorch: needs several GB free)
cp ../.env.example .env           # then fill in the robot section
```

> **Safety:** Keep hands out of the workspace while the arm is powered, and keep the power switch / e-stop within reach. Ctrl+C stops scripted motion at the next step and holds position. Scripts leave torque **on** when they exit, so the arm holds its pose. Use `relax` only while supporting the arm.

## 1. Connect & calibrate (once per arm)

```bash
uv run python scripts/arm.py ports            # list serial ports
lerobot-find-port                             # unplug one arm when asked, to tell leader from follower
```

Put the ports in `.env` as `SO101_PORT` (follower) and `LEADER_PORT` (leader), then:

```bash
uv run python scripts/arm.py calibrate follower
uv run python scripts/arm.py calibrate leader
```

If Perceptron mentors already calibrated the arms, reuse their `SO101_ID` / `LEADER_ID` so LeRobot finds the existing calibration files.

## 2. Teleoperate & record demonstrations (Perceptron P0)

```bash
uv run python scripts/arm.py teleop --cameras
uv run python scripts/arm.py record --repo <hf-user>/remind-tea --episodes 20
```

Recording uses the format Perceptron expects: 30 fps, `side` and `wrist` cameras at 640×480, and 6 joints. Then follow [docs/PERCEPTRON_API.md](../docs/PERCEPTRON_API.md) to register the dataset, train, and deploy.

## 3. Scripted control (reliable fallback with fixed pickup spots)

Teach poses by hand. Torque goes off so you can move the arm, and each Enter saves one pose to `poses.json`:

```bash
uv run python scripts/arm.py teach home above_tea grasp_tea above_tray release_tray
uv run python scripts/arm.py read --follow    # live joint readout
uv run python scripts/arm.py goto home --speed 0.5
uv run python scripts/arm.py gripper 60       # 0-100; check which end is open on your arm
uv run python scripts/arm.py run tea --repeat 10   # repeated trials → real success rate
```

Sequences live in `poses.json`. A step is a pose name, `{"gripper": n}` or `{"wait": s}`. Speed limits come from `ARM_SPEED_DEG_S` / `GRIPPER_SPEED_S`.

## 4. Run the worker

```bash
ROBOT_MODE=mock uv run uvicorn worker.main:app --port 8001        # no hardware
ROBOT_MODE=scripted uv run uvicorn worker.main:app --port 8001    # replays poses.json sequences
ROBOT_MODE=perceptron uv run uvicorn worker.main:app --port 8001  # Perceptron policy + cameras
```

In the demo, label scripted runs as scripted, not as a learned policy.
