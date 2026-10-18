"""Correctness checks for robot moves in the memory game: shuffle math, the action guard, the grasp
monitor, the camera row check and the executor wiring. Tests marked `recorded` replay the real
recordings and skip when the dataset is not on this machine."""

import itertools
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from worker import executors, shuffle_math
from worker.motion_guard import JOINTS, ActionGuard, GraspMonitor, GuardError, Limits, motors_ok
from worker.row_check import read_row
from worker.shuffle_math import SHUFFLES, MoveError, apply_moves, expected_end, permutation, shuffle_for, verdict

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "row"
DATASET = Path.home() / ".cache/huggingface/lerobot/remind/remind-shuffle"
recorded = pytest.mark.skipif(not (DATASET / "data").exists(), reason="recorded dataset not on this machine")
OBJECTS = ["black", "white", "purple"]

# END rows from docs/RECORDING_SETUP.md, starting from black · white · purple.
DOC_END = {
    "swap_lr": ["purple", "white", "black"],
    "swap_lm": ["white", "black", "purple"],
    "swap_mr": ["black", "purple", "white"],
    "rot_left": ["white", "purple", "black"],
    "rot_right": ["purple", "black", "white"],
}


# ---------------------------------------------------------------- shuffle math


@pytest.mark.parametrize("sid", list(SHUFFLES))
def test_moves_match_the_printed_setup_card(sid):
    assert expected_end(OBJECTS, sid) == DOC_END[sid]


@pytest.mark.parametrize("sid,start", [(s, list(p)) for s in SHUFFLES for p in itertools.permutations(OBJECTS)])
def test_every_shuffle_is_legal_from_every_start(sid, start):
    """All 6 starting orders x 5 shuffles: every move picks from a full slot, places into an empty
    one, the parking slot ends empty and nothing is lost or duplicated."""
    end = apply_moves([*start, None], SHUFFLES[sid].moves)
    assert end[3] is None
    assert sorted(end[:3]) == sorted(start)
    assert end[:3] != start  # a shuffle always changes the row


def test_the_five_shuffles_are_the_five_non_identity_permutations():
    perms = {permutation(s) for s in SHUFFLES}
    assert len(perms) == 5
    assert (1, 2, 3) not in perms
    assert perms == set(itertools.permutations((1, 2, 3))) - {(1, 2, 3)}


def test_every_end_order_maps_back_to_exactly_one_shuffle():
    for start in itertools.permutations(OBJECTS):
        for end in itertools.permutations(OBJECTS):
            sid = shuffle_for(list(start), list(end))
            assert (sid is None) == (end == start)
            if sid:
                assert expected_end(list(start), sid) == list(end)


def test_illegal_moves_are_rejected():
    with pytest.raises(MoveError, match="empty"):
        apply_moves(["a", "b", "c", None], [(4, 1)])
    with pytest.raises(MoveError, match="taken"):
        apply_moves(["a", "b", "c", None], [(1, 2)])
    with pytest.raises(MoveError, match="bad slots"):
        apply_moves(["a", "b", "c", None], [(1, 5)])
    with pytest.raises(MoveError):
        expected_end(["a", "a", "b"], "swap_lr")


def test_verdict():
    exp = ["purple", "white", "black"]
    assert verdict(exp, exp) == "ok"
    assert verdict(exp, ["white", "purple", "black"]) == "mismatch"
    assert verdict(exp, [None, None, None]) == "unsure"
    assert verdict(exp, ["white", None, None]) == "mismatch"  # one wrong object is enough
    assert verdict(exp, None) == "unsure"


# ---------------------------------------------------------------- action guard


@pytest.fixture
def limits():
    return Limits.load(ROOT / "motion_limits.json")


@pytest.fixture
def guard(limits):
    return ActionGuard(limits)


def middle(limits):
    return [(limits.envelope[j][0] + limits.envelope[j][1]) / 2 for j in JOINTS]


def test_limits_file_is_consistent(limits):
    for j in JOINTS:
        hlo, hhi = limits.hard[j]
        elo, ehi = limits.envelope[j]
        assert hlo <= elo < ehi <= hhi, j
        assert 0 < limits.step[j] <= 10, j  # under LeRobot's own max_relative_target


def test_a_safe_chunk_passes_unchanged(guard, limits):
    s = middle(limits)
    chunk = [[v + 0.5 * k for v in s] for k in range(1, 31)]
    safe, rep = guard.check_chunk(s, chunk)
    assert rep.clamped_envelope == rep.clamped_hard == rep.step_limited == 0
    assert all(math.isclose(a, b) for r1, r2 in zip(safe, chunk) for a, b in zip(r1, r2))


def test_out_of_range_targets_are_clamped_and_reach_the_limit_gradually(guard, limits):
    s = middle(limits)
    target = list(s)
    target[1] = limits.hard["shoulder_lift"][1] + 50  # far past the end stop
    safe, rep = guard.check_chunk(s, [target] * 30)
    lift = [a[1] for a in safe]
    assert rep.clamped_hard == 30
    assert max(lift) <= limits.envelope["shoulder_lift"][1] + 1e-9
    steps = np.abs(np.diff([s[1], *lift]))
    assert steps.max() <= limits.step["shoulder_lift"] + 1e-9


def test_big_jumps_are_cut_into_allowed_steps(guard, limits):
    s = middle(limits)
    jump = list(s)
    jump[0] = limits.envelope["shoulder_pan"][1]
    safe, rep = guard.check_chunk(s, [jump])
    assert rep.step_limited == 1
    assert math.isclose(safe[0][0] - s[0], limits.step["shoulder_pan"])


def test_a_chunk_mostly_outside_the_demonstrations_is_refused(guard, limits):
    s = middle(limits)
    wild = [limits.envelope[j][1] + 30 for j in JOINTS]
    with pytest.raises(GuardError) as e:
        guard.check_chunk(s, [wild] * 10)
    assert e.value.code == "policy_out_of_range"


@pytest.mark.parametrize(
    "chunk,code",
    [([], "empty_chunk"), ([[0.0] * 5], "bad_action"), ([[float("nan")] * 6], "bad_action"), ([[float("inf")] * 6], "bad_action")],
)
def test_malformed_chunks_are_refused(guard, limits, chunk, code):
    with pytest.raises(GuardError) as e:
        guard.check_chunk(middle(limits), chunk)
    assert e.value.code == code


def test_state_outside_the_envelope_is_pulled_back_not_jumped(guard, limits):
    s = middle(limits)
    s[0] = limits.envelope["shoulder_pan"][1] + 8  # arm already past the envelope (e.g. pushed)
    safe, _ = guard.check_chunk(s, [s] * 5)
    assert safe[0][0] >= s[0] - limits.step["shoulder_pan"] - 1e-9
    assert safe[-1][0] <= limits.hard["shoulder_pan"][1]


def test_motor_temperature():
    assert motors_ok({"gripper": 45.0, "wrist_flex": 59.9}) == (True, "")
    ok, why = motors_ok({"gripper": 61.0, "wrist_flex": 40.0})
    assert not ok and "gripper" in why


@recorded
def test_every_recorded_demonstration_passes_the_guard(guard):
    """The human demos are the definition of correct motion, so the guard must leave them alone."""
    import pandas as pd

    files = sorted((DATASET / "data").glob("*/*.parquet"))
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "action", "observation.state"]) for f in files])
    refused = 0
    out = vals = 0
    for _, g in df.groupby("episode_index"):
        acts = np.stack(g["action"].values).tolist()
        state = list(np.stack(g["observation.state"].values)[0])
        for k in range(0, len(acts), 30):
            try:
                _, rep = guard.check_chunk(state, acts[k : k + 30])
                out += rep.clamped_envelope
                vals += rep.values
            except GuardError:
                refused += 1
            state = acts[min(k + 29, len(acts) - 1)]
    assert refused == 0
    assert out / vals < 0.01


# ---------------------------------------------------------------- grasp monitor


def feed(mon, grips, pan=0.0, moving=True):
    for i, g in enumerate(grips):
        mon.update([pan + (i * 0.1 if moving else 0), 0, 0, 0, 0, g])


def test_grasp_and_release_are_counted():
    m = GraspMonitor()
    feed(m, [35] * 10 + [20] * 15 + [35] * 10)
    assert (m.grasps, m.releases, m.holding) == (1, 1, False)


def test_closing_on_nothing_is_not_a_grasp():
    m = GraspMonitor()
    feed(m, [35] * 10 + [11] * 20)
    assert m.grasps == 0 and not m.holding


def test_slipped_object_clears_holding():
    m = GraspMonitor()
    feed(m, [35] * 10 + [20] * 15 + [11] * 15)
    assert m.grasps == 1 and not m.holding


def test_holding_still_for_too_long_is_a_stall():
    m = GraspMonitor(fps=30, stall_seconds=2)
    feed(m, [20] * 10)
    feed(m, [20] * 70, moving=False)
    assert m.stalled


@recorded
def test_monitor_sees_grasps_in_every_recorded_demo():
    import pandas as pd

    files = sorted((DATASET / "data").glob("*/*.parquet"))
    df = pd.concat([pd.read_parquet(f, columns=["episode_index", "observation.state"]) for f in files])
    with_grasp = 0
    for _, g in df.groupby("episode_index"):
        m = GraspMonitor()
        for s in np.stack(g["observation.state"].values):
            m.update(list(s))
        with_grasp += m.grasps >= 2
    assert with_grasp >= 55  # every shuffle needs at least 3 pick-and-places


# ---------------------------------------------------------------- camera row check

# Real side-camera frames from the recordings: (file, shuffle, expected verdict)
FRAMES = [
    ("ep00_start.jpg", None, ["black", "white", "purple"]),
    ("ep00_end.jpg", "swap_lr", None),
    ("ep24_end.jpg", "swap_lm", None),
    ("ep28_end.jpg", "swap_mr", None),
    ("ep34_end.jpg", "rot_left", None),
    ("ep36_end.jpg", "rot_right", None),
]


@pytest.mark.parametrize("name,sid,order", FRAMES)
def test_row_is_read_correctly_from_real_frames(name, sid, order):
    row = read_row(cv2.imread(str(FIX / name)))
    expected = order or expected_end(OBJECTS, sid)
    assert row["order"] == expected
    assert verdict(expected, row["order"]) == "ok"


def test_wrong_shuffle_is_caught():
    row = read_row(cv2.imread(str(FIX / "ep00_end.jpg")))  # swap_lr result
    assert verdict(expected_end(OBJECTS, "swap_lm"), row["order"]) == "mismatch"


def test_partly_visible_row_is_unsure_not_guessed():
    row = read_row(cv2.imread(str(FIX / "ep05_end.jpg")))  # purple keyring is out of frame
    assert row["visible"] == 2
    assert verdict(expected_end(OBJECTS, "swap_lm"), row["order"]) == "unsure"


def test_empty_table_is_unsure():
    blank = np.full((480, 640, 3), 235, np.uint8)
    assert read_row(blank)["visible"] == 0


# ---------------------------------------------------------------- executor wiring


class FakeClient:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    grants = 0

    def grant(self, *a, **k):
        import types

        FakeClient.grants += 1
        return types.SimpleNamespace(expires_at=10**12)

    def reset(self, *a, **k):
        pass

    def create_session(self, *a, **k):
        pass

    def delete_session(self, *a, **k):
        pass

    def predict(self, *a, **k):
        return {"actions": self.chunks.pop(0) if self.chunks else [[0.0] * 6]}


TABLE = np.full((480, 640, 3), 235, np.uint8)


def hand_frame():
    f = TABLE.copy()
    f[150:400, 200:420] = (120, 150, 205)  # BGR skin tone
    return f


class FakeRobot:
    def __init__(self, state, side_png, end_grip=35.0, frames=None):
        self.state, self.side, self.end_grip, self.sent = state, side_png, end_grip, []
        self.frames = list(frames or [])

    def side_frame(self):
        return self.frames.pop(0) if self.frames else TABLE

    def observe(self):
        return list(self.state[:-1]) + [self.end_grip], self.side, b""

    def act(self, a):
        self.sent.append(a)


def make_exec(limits, chunks, side_png, end_grip=35.0, seconds=0.05):
    ex = executors.PerceptronExecutor.__new__(executors.PerceptronExecutor)
    ex.client = FakeClient(chunks)
    ex.contract_id = "c"
    ex.fps = 1000.0
    ex.max_seconds = seconds
    ex.guard = ActionGuard(limits)
    ex.robot = FakeRobot(middle(limits), side_png, end_grip)
    ex.last_check = None
    ex.hand_pauses = 0
    ex.stride = None
    ex.say = lambda text: None
    return ex


def png(name):
    return cv2.imencode(".png", cv2.imread(str(FIX / name)))[1].tobytes()


def test_executor_confirms_a_correct_shuffle(limits):
    ex = make_exec(limits, [[middle(limits)] * 30] * 50, png("ep00_end.jpg"))
    ex.execute({"instruction": SHUFFLES["swap_lr"].instruction, "shuffle": "swap_lr"}, executors.threading.Event())
    assert ex.last_check["verdict"] == "ok"
    assert ex.last_check["guard"]["chunks"] >= 1


def test_executor_fails_a_wrong_shuffle(limits):
    ex = make_exec(limits, [[middle(limits)] * 30] * 50, png("ep00_end.jpg"))
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": SHUFFLES["swap_lm"].instruction, "shuffle": "swap_lm"}, executors.threading.Event())
    assert e.value.code == "shuffle_mismatch"


def test_executor_never_sends_unsafe_targets(limits):
    wild = [limits.hard[j][1] + 100 for j in JOINTS]
    ok = middle(limits)
    chunk = [ok] * 27 + [wild] * 3  # 10% wild: clamped, not refused
    ex = make_exec(limits, [chunk] * 50, png("ep00_end.jpg"))
    ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    for a in ex.robot.sent:
        for v, j in zip(a, JOINTS):
            assert limits.hard[j][0] <= v <= limits.hard[j][1]


def test_executor_refuses_wild_policy_output(limits):
    wild = [limits.hard[j][1] + 100 for j in JOINTS]
    ex = make_exec(limits, [[wild] * 30], png("ep00_end.jpg"))
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x"}, executors.threading.Event())
    assert e.value.code == "policy_out_of_range"
    assert ex.robot.sent == []


def test_executor_flags_object_left_in_gripper(limits):
    ex = make_exec(limits, [[middle(limits)] * 30] * 50, png("ep00_end.jpg"), end_grip=20.0, seconds=0.5)
    ex.robot.state = middle(limits)
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert e.value.code in {"object_still_held", "arm_stalled"}


def test_mock_executor_reports_a_simulated_check():
    ex = executors.MockExecutor()
    ex.duration = 0
    ex.execute({"instruction": "x", "shuffle": "rot_right"}, executors.threading.Event())
    assert ex.last_check["expected"] == DOC_END["rot_right"]
    assert ex.last_check["simulated"] is True


def test_worker_allowlist_has_every_shuffle():
    allowed = shuffle_math.allowlist()
    assert set(allowed) == {("shuffle", sid) for sid in SHUFFLES}
    assert "shuffle_allowlist()" in (ROOT / "worker/main.py").read_text()


@recorded
def test_instructions_match_the_training_data_word_for_word():
    import pandas as pd

    tasks = set(pd.read_parquet(DATASET / "meta/tasks.parquet").index)
    assert {s.instruction for s in SHUFFLES.values()} == tasks
    assert json.loads((ROOT / "motion_limits.json").read_text())["source"]["dataset"] == "remind/remind-shuffle"


# ---------------------------------------------------------------- hands in the workspace

from worker import table_view  # noqa: E402


def test_skin_is_seen_and_the_table_is_not():
    assert table_view.hands_in(hand_frame())
    assert not table_view.hands_in(TABLE)
    for name in FIX.glob("*.jpg"):  # real recorded frames have no hands
        assert not table_view.hands_in(cv2.imread(str(name))), name.name


def test_look_reports_row_and_hands():
    out = table_view.look(cv2.imread(str(FIX / "ep00_end.jpg")))
    assert out["order"] == ["purple", "white", "black"] and out["hands"] is False


def test_robot_waits_for_a_hand_to_leave_then_carries_on(limits, monkeypatch):
    monkeypatch.setattr(executors, "HANDS_CLEAR_S", 0.0)
    ex = make_exec(limits, [[middle(limits)] * 30] * 50, png("ep00_end.jpg"))
    ex.robot.frames = [TABLE] + [hand_frame()] * 2 + [TABLE] * 3  # hand appears mid-chunk, then leaves
    said = []
    ex.say = said.append
    ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert ex.hand_pauses == 1
    assert said == ["I'll wait while your hand is on the table."]
    assert ex.last_check["handPauses"] == 1


def test_robot_never_moves_while_a_hand_stays(limits, monkeypatch):
    monkeypatch.setattr(executors, "HANDS_MAX_WAIT_S", 0.3)
    ex = make_exec(limits, [[middle(limits)] * 30] * 50, png("ep00_end.jpg"))
    ex.robot.frames = [hand_frame()] * 1000
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x"}, executors.threading.Event())
    assert e.value.code == "hands_in_workspace"
    assert ex.robot.sent == []


def test_stop_works_while_waiting_for_a_hand(limits):
    ex = make_exec(limits, [[middle(limits)] * 30], png("ep00_end.jpg"))
    ex.robot.frames = [hand_frame()] * 1000
    stop = executors.threading.Event()
    stop.set()
    with pytest.raises(executors.Stopped):
        ex.execute({"instruction": "x"}, stop)


def test_only_the_contract_stride_runs_before_predicting_again(limits):
    ex = make_exec(limits, [[middle(limits)] * 30] * 50, png("ep00_end.jpg"), seconds=0.2)
    ex.stride = 15
    calls = []
    real = ex.client.predict
    ex.client.predict = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert len(ex.robot.sent) == 15 * len(calls)


# ---------------------------------------------------------------- scripted fallback (no Perceptron)

from worker.shuffle_math import SCRIPT_POSES, scripted_steps  # noqa: E402


@pytest.mark.parametrize("sid", list(SHUFFLES))
def test_scripted_steps_play_the_same_moves_as_the_skill(sid):
    """Replaying the scripted gripper events on the row gives the shuffle's expected end."""
    row = [*OBJECTS, None]
    held = slot = None
    for step in scripted_steps(sid):
        if isinstance(step, str) and step.startswith("down_s"):
            slot = int(step[-1])
        elif isinstance(step, dict) and "gripper" in step and slot:
            if step["gripper"] < 20 and held is None:
                held, row[slot - 1] = row[slot - 1], None
                assert held is not None, f"{sid}: picked from empty slot {slot}"
            elif step["gripper"] >= 20 and held is not None:
                assert row[slot - 1] is None, f"{sid}: placed onto full slot {slot}"
                row[slot - 1], held = held, None
    assert row[:3] == expected_end(OBJECTS, sid) and row[3] is None and held is None
    assert scripted_steps(sid)[0] == "home" and scripted_steps(sid)[-1] == "home"
    assert {s for s in scripted_steps(sid) if isinstance(s, str)} <= set(SCRIPT_POSES)


class FakeArm(FakeRobot):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.path = []

    def move_to(self, target, stop=None, speed_scale=1.0):
        self.path.append(("move", dict(target)))

    def gripper(self, value, stop=None):
        self.path.append(("grip", value))


def taught(monkeypatch):
    poses = {p: {"shoulder_pan.pos": float(i)} for i, p in enumerate(SCRIPT_POSES)}
    monkeypatch.setattr("worker.robot.load_poses", lambda: {"poses": poses, "sequences": {}})
    return poses


class RefusingClient(FakeClient):
    def grant(self, *a, **k):
        raise RuntimeError("409 deployment_recovering")


def test_perceptron_refusal_falls_back_to_scripted_shuffle(limits, monkeypatch):
    taught(monkeypatch)
    ex = make_exec(limits, [], png("ep00_end.jpg"))
    ex.client = RefusingClient([])
    ex.robot = FakeArm(middle(limits), png("ep00_end.jpg"))
    ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert ex.last_check["mode"] == "scripted-fallback"
    assert "deployment_recovering" in ex.last_check["policyError"]
    grips = [v for k, v in ex.robot.path if k == "grip"]
    assert grips.count(shuffle_math.GRIP_CLOSE) == 3  # three pick-and-places for a swap


def test_no_fallback_without_taught_poses(limits, monkeypatch):
    monkeypatch.setattr("worker.robot.load_poses", lambda: {"poses": {}, "sequences": {}})
    ex = make_exec(limits, [], png("ep00_end.jpg"))
    ex.client = RefusingClient([])
    ex.robot = FakeArm(middle(limits), png("ep00_end.jpg"))
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert e.value.code == "policy_unavailable"
    assert ex.robot.path == []  # never moved


def test_scripted_executor_reports_missing_poses(monkeypatch):
    monkeypatch.setattr("worker.robot.load_poses", lambda: {"poses": {"home": {}}, "sequences": {}})
    ex = executors.ScriptedExecutor(robot=FakeArm([0] * 6, None))
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert e.value.code == "poses_missing" and "down_s4" in str(e.value)


def test_one_perceptron_session_is_reused_across_jobs(limits):
    """Closing a session puts the deployment into ~5 min of 'recovering', so jobs share one."""
    ex = make_exec(limits, [[middle(limits)] * 30] * 200, png("ep00_end.jpg"))
    before = FakeClient.grants
    for _ in range(3):
        ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert FakeClient.grants - before == 1


# ---------------------------------------------------------------- camera-guided picks

from worker import slot_locate  # noqa: E402


def test_pan_line_fits_the_taught_slots():
    slope, icpt = slot_locate.fit({1: 0.75, 2: 0.44, 3: 0.12}, {1: -13.0, 2: -1.1, 3: 15.1})
    assert slope < 0  # camera is mirrored: further right in the image = slot 1 = more negative pan
    assert abs(slope * 0.44 + icpt - (-1.1)) < 1.5


def test_pick_correction_follows_the_keyring_and_is_capped():
    cal = {1: 0.75, 2: 0.44, 3: 0.12}
    slope, _ = slot_locate.fit(cal, {1: -13.0, 2: -1.1, 3: 15.1})
    assert slot_locate.pan_correction(0.755, 2, cal, slope) == 0.0 or abs(slot_locate.pan_correction(0.445, 2, cal, slope)) < 1e-9
    small = slot_locate.pan_correction(0.40, 2, cal, slope)  # keyring a bit toward slot 3
    assert 0 < small < slot_locate.MAX_CORRECTION_DEG
    assert slot_locate.pan_correction(0.20, 2, cal, slope) == slot_locate.MAX_CORRECTION_DEG  # far off: capped
    assert slot_locate.pan_correction(0.05, 3, cal, slope) == 0.0  # cut off by the image edge: trust the pose
    assert slot_locate.pan_correction(0.5, 4, cal, slope) == 0.0  # slot 4 is out of view


class CameraArm(FakeArm):
    def __init__(self, positions, *a, **k):
        super().__init__([0] * 6, None)
        import types

        self.robot = types.SimpleNamespace(cameras={"side": object()})
        self.positions = positions

    def side_frame(self):
        return TABLE


def guided(monkeypatch, positions):
    poses = {p: {"shoulder_pan.pos": 0.0, "shoulder_lift.pos": 0.0} for p in SCRIPT_POSES}
    for s, pan in {1: -13.0, 2: -1.1, 3: 15.1, 4: 27.5}.items():
        for k in ("above", "down"):
            poses[f"{k}_s{s}"]["shoulder_pan.pos"] = pan
    data = {"poses": poses, "sequences": {}, "camera_x": {"1": 0.75, "2": 0.44, "3": 0.12}}
    monkeypatch.setattr("worker.robot.load_poses", lambda: data)
    monkeypatch.setattr("worker.row_check.find", lambda f: positions)
    monkeypatch.setattr("worker.row_check.read_row", lambda f: {"order": sorted(positions, key=lambda o: -positions[o][0]) if len(positions) == 3 else [None] * 3, "visible": len(positions), "seen": list(positions)})
    monkeypatch.setattr(executors, "shuffle_check", lambda spec, side: None)
    return executors.ScriptedExecutor(robot=CameraArm(positions))


def test_off_center_keyring_is_picked_where_it_really_is(monkeypatch):
    monkeypatch.setenv("PICK_CAMERA_CORRECTION", "1")
    ex = guided(monkeypatch, {"black": (0.72, 900), "white": (0.44, 900), "purple": (0.12, 900)})
    ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    first = ex.corrections[0]
    assert first["slot"] == 1 and first["object"] == "black" and first["panDeg"] > 0
    downs = [t for k, t in ex.robot.path if k == "move" and abs(t["shoulder_pan.pos"] - (-13.0 + first["panDeg"])) < 0.01]
    assert downs  # the slot-1 pick went to the corrected pan


def test_wrong_start_layout_never_moves(monkeypatch):
    ex = guided(monkeypatch, {"white": (0.75, 900), "black": (0.44, 900), "purple": (0.12, 900)})
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert e.value.code == "start_mismatch" and ex.robot.path == []


class GripArm(FakeArm):
    """Gripper reads 20 when holding, 11 when it closed on nothing (pattern per close)."""

    def __init__(self, holds):
        super().__init__([0] * 6, None)
        self.holds = list(holds)
        self.grip = 38.0

    def gripper(self, value, stop=None):
        super().gripper(value, stop)
        self.grip = (20.0 if (self.holds.pop(0) if self.holds else True) else 11.0) if value < 20 else value

    def joints(self):
        return {"gripper.pos": self.grip}


def test_missed_pick_is_retried_once(monkeypatch):
    taught(monkeypatch)
    ex = executors.ScriptedExecutor(robot=GripArm([False, True, True, True]))
    ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert [v for k, v in ex.robot.path if k == "grip"].count(shuffle_math.GRIP_CLOSE) == 4


def test_twice_missed_pick_stops_before_placing(monkeypatch):
    taught(monkeypatch)
    ex = executors.ScriptedExecutor(robot=GripArm([False, False]))
    with pytest.raises(executors.RobotError) as e:
        ex.execute({"instruction": "x", "shuffle": "swap_lr"}, executors.threading.Event())
    assert e.value.code == "grasp_missed" and "slot 1" in str(e.value)
    moved_to = [t for k, t in ex.robot.path if k == "move"]
    assert all(t.get("shoulder_pan.pos") != float(SCRIPT_POSES.index("down_s4")) for t in moved_to)  # never went to place


# ---------------------------------------------------------------- keyring on its spot (no tape)


def test_spot_check_names_the_keyring_and_the_direction():
    ref = {1: (0.757, 0.30), 2: (0.438, 0.30), 3: (0.104, 0.40)}
    ok = slot_locate.spot_problems({"black": (0.75, 0.31), "white": (0.44, 0.29), "purple": (0.10, 0.41)}, ["black", "white", "purple", None], ref)
    assert ok == []
    bad = slot_locate.spot_problems({"black": (0.69, 0.40), "white": (0.44, 0.29), "purple": (0.10, 0.41)}, ["black", "white", "purple", None], ref)
    assert len(bad) == 1 and bad[0]["object"] == "black"
    assert "sang trái" in bad[0]["sayVi"] and "lại gần robot" in bad[0]["sayVi"]


def test_find_xy_on_a_real_frame():
    xy = __import__("worker.row_check", fromlist=["find_xy"]).find_xy(cv2.imread(str(FIX / "ep00_start.jpg")))
    assert set(xy) == {"black", "white", "purple"}
    assert all(0 <= v <= 1 for p in xy.values() for v in p)


def test_spot_check_knows_each_keyrings_shape():
    """Calibrated black, white, purple; after swap_lr purple sits on slot 1 and black on slot 3."""
    ref = {1: (0.8627, 0.1972), 2: (0.6166, 0.2048), 3: (0.3446, 0.4367)}
    after = {"purple": (0.8627, 0.1972 + (0.4367 - 0.201)), "white": (0.6166, 0.2048), "black": (0.3446, 0.201)}
    assert slot_locate.spot_problems(after, ["purple", "white", "black", None], ref) == []
