"""Build motion_limits.json from the follower calibration and a recorded dataset.

    uv run python scripts/build_motion_limits.py [--repo remind/remind-shuffle]

- hard: the calibrated travel of each joint, in the units the policy uses (degrees, gripper 0-100),
  shrunk by a safety buffer so we never drive a joint into its end stop.
- envelope: where the arm actually went while a human demonstrated the task (0.5th-99.5th
  percentile of the recorded actions) plus a margin. A policy that leaves this box is doing
  something it never saw, so its output is clamped and flagged.
- step: the largest per-frame move we allow, from the recorded 99.9th percentile with headroom."""

import argparse
import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CAL = Path(os.path.expanduser("~/.cache/huggingface/lerobot/calibration/robots/so_follower/remind_follower.json"))
DATA = Path(os.path.expanduser("~/.cache/huggingface/lerobot"))
NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
RESOLUTION = 4096  # STS3215
HARD_BUFFER_DEG = 3.0
HARD_BUFFER_GRIP = 2.0
ENVELOPE_MARGIN_DEG = 10.0
ENVELOPE_MARGIN_GRIP = 5.0
STEP_HEADROOM = 1.5


def hard_limits(cal: dict) -> dict:
    out = {}
    for n in NAMES:
        lo, hi = cal[n]["range_min"], cal[n]["range_max"]
        if n == "gripper":  # LeRobot RANGE_0_100
            out[n] = [HARD_BUFFER_GRIP, 100 - HARD_BUFFER_GRIP]
        else:  # LeRobot DEGREES: (raw - mid) * 360 / (resolution - 1)
            mid = (lo + hi) / 2
            to_deg = lambda raw: (raw - mid) * 360 / (RESOLUTION - 1)  # noqa: E731
            out[n] = [round(to_deg(lo) + HARD_BUFFER_DEG, 2), round(to_deg(hi) - HARD_BUFFER_DEG, 2)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="remind/remind-shuffle")
    ap.add_argument("--out", default=str(ROOT / "motion_limits.json"))
    args = ap.parse_args()

    hard = hard_limits(json.loads(CAL.read_text()))
    files = sorted(glob.glob(str(DATA / args.repo / "data/*/*.parquet")))
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "action"]) for f in files])
    actions = np.stack(df["action"].values)
    steps = np.concatenate(
        [np.abs(np.diff(np.stack(g["action"].values), axis=0)) for _, g in df.groupby("episode_index")]
    )

    envelope, step = {}, {}
    for i, n in enumerate(NAMES):
        lo, hi = np.percentile(actions[:, i], [0.5, 99.5])
        m = ENVELOPE_MARGIN_GRIP if n == "gripper" else ENVELOPE_MARGIN_DEG
        envelope[n] = [round(float(max(lo - m, hard[n][0])), 2), round(float(min(hi + m, hard[n][1])), 2)]
        step[n] = round(float(np.percentile(steps[:, i], 99.9) * STEP_HEADROOM), 2)

    out = {
        "source": {"dataset": args.repo, "episodes": int(df.episode_index.nunique()), "frames": len(df)},
        "units": "degrees for arm joints, 0-100 for the gripper",
        "joints": NAMES,
        "hard": hard,
        "envelope": envelope,
        "step": step,
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
