"""Campaign runner tests with a fake LeRobot recorder (no arms or cameras)."""

import json
import threading
import time

import pytest

from worker import campaign as cm
from worker import studio


class FakeProc:
    """Stands in for studio.proc: 'records' by bumping total_episodes in info.json."""

    def __init__(self, root, fail_on_batch=None):
        self.root, self.fail_on_batch = root, fail_on_batch
        self.running, self.kind, self.exit_code, self.stopped_by_user = False, None, None, False
        self.logs, self.batches = [], 0

    def start(self, kind, cmd):
        self.kind, self.batches = kind, self.batches + 1
        repo = next(a.split("=", 1)[1] for a in cmd if a.startswith("--dataset.repo_id="))
        n = int(next(a.split("=", 1)[1] for a in cmd if a.startswith("--dataset.num_episodes=")))
        info = self.root / repo / "meta/info.json"
        info.parent.mkdir(parents=True, exist_ok=True)
        total = json.loads(info.read_text())["total_episodes"] if info.exists() else 0
        failing = self.batches == self.fail_on_batch
        info.write_text(json.dumps({"total_episodes": total + (1 if failing else n)}))
        self.exit_code = 1 if failing else 0
        self.logs = [(1, "TimeoutError: OpenCVCamera(1) latest frame is too old")] if failing else []
        self.running = True
        threading.Timer(0.05, lambda: setattr(self, "running", False)).start()

    def stop(self):
        self.stopped_by_user = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "DATA_HOME", tmp_path / "data")
    monkeypatch.setattr(studio, "require_ports", lambda: None)
    monkeypatch.setattr(cm, "STATE_FILE", tmp_path / "campaign.json")
    monkeypatch.setattr(studio, "proc", studio.proc)  # restored after each test
    return tmp_path


def make(env, fail_on_batch=None):
    proc = FakeProc(env / "data", fail_on_batch)
    studio.proc = proc
    c = cm.Campaign()
    c.config = cm.Config(
        repo="team/remind-sort", batchSize=2, breakSeconds=0, visionCheck=False, autoUpload=False,
        targets=[cm.Target(id="tea", task="t", object="tea box", target=3), cm.Target(id="coffee", task="c", object="coffee box", target=3)],
    )
    return c, proc


def operator(c, until):
    """Simulated teammate: says 'ready' whenever the campaign waits for it."""
    def loop():
        while time.time() < until:
            if c.state in ("setup", "waiting_ready"):
                c.ready.set()
            time.sleep(0.02)
    threading.Thread(target=loop, daemon=True).start()


def wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_runs_all_batches_to_target(env):
    c, proc = make(env)
    operator(c, time.time() + 10)
    c.start()
    assert wait_for(lambda: c.state == "done")
    assert c.progress == {"tea": 3, "coffee": 3}
    assert proc.batches == 4  # 2+1 per target, interleaved
    assert studio.episode_count("team/remind-sort") == 6


def test_failure_pauses_and_keeps_episodes(env):
    c, proc = make(env, fail_on_batch=2)
    operator(c, time.time() + 10)
    c.start()
    assert wait_for(lambda: c.state == "paused")
    assert "camera lagged" in c.message
    assert sum(c.progress.values()) == 3  # 2 from batch 1 + 1 saved before the failure
    c.start()  # operator fixed it and resumes
    assert wait_for(lambda: c.state == "done")
    assert c.progress == {"tea": 3, "coffee": 3}


def test_progress_survives_restart(env):
    c, _ = make(env)
    operator(c, time.time() + 10)
    c.start()
    assert wait_for(lambda: c.state == "done")
    again = cm.Campaign()
    assert again.progress == {"tea": 3, "coffee": 3}


def test_stop_while_waiting_for_ready_never_records(env):
    c, proc = make(env)
    c.start()
    assert wait_for(lambda: c.state in ("setup", "waiting_ready"))
    c.stop()
    assert wait_for(lambda: not (c.thread and c.thread.is_alive()))
    time.sleep(0.2)
    assert proc.batches == 0, "stop must not start a recording"
    assert c.progress == {}


def test_gripper_fault_after_full_batch_is_cleared_and_recording_continues(env, monkeypatch):
    c, proc = make(env)
    real_start = proc.start

    def start_with_gripper_fault(kind, cmd):
        real_start(kind, cmd)
        proc.exit_code = 1  # all episodes saved, then the shutdown hit the gripper overload
        proc.logs = [(1, "RuntimeError: Failed to write 'Torque_Enable' on id_=6 with '0' after 6 tries. [RxPacketError] Overload error!")]

    proc.start = start_with_gripper_fault
    cleared = []
    monkeypatch.setattr(cm, "auto_clear_gripper", lambda: cleared.append(1))  # returns None = success
    operator(c, time.time() + 10)
    c.start()
    assert wait_for(lambda: c.state == "done")
    assert c.progress == {"tea": 3, "coffee": 3} and len(cleared) == 4


def test_other_motor_fault_still_pauses(env, monkeypatch):
    c, proc = make(env)
    real_start = proc.start

    def start_with_elbow_fault(kind, cmd):
        real_start(kind, cmd)
        proc.exit_code = 1
        proc.logs = [(1, "RuntimeError: Failed to write 'Torque_Enable' on id_=3 with '0'. [RxPacketError] Overload error!")]

    proc.start = start_with_elbow_fault
    monkeypatch.setattr(cm, "auto_clear_gripper", lambda: "another motor needs attention")
    operator(c, time.time() + 10)
    c.start()
    assert wait_for(lambda: c.state == "paused")
    assert "Batch saved" in c.message
