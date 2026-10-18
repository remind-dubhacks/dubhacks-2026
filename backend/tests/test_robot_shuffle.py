import asyncio

import pytest

from app import robot_client
from app.config import settings
from app.voice import tools
from app.voice.tools import GameState, run_tool


class FakeWorker:
    def __init__(self, ready=True, outcome="succeeded"):
        self.ready, self.outcome, self.jobs, self.stopped, self.polls = ready, outcome, {}, False, 0

    async def health(self):
        return {"ready": self.ready, "busy": False, "mode": "fake"}

    async def submit(self, job_id, action_id, object_id):
        assert (action_id, object_id) == (settings.robot_shuffle_action, settings.robot_shuffle_object)  # fixed, never user/LLM text
        self.jobs[job_id] = {"status": "running"}
        return self.jobs[job_id]

    async def status(self, job_id):
        self.polls += 1
        return {"status": self.outcome if self.polls >= 2 else "running"}

    async def stop(self):
        self.stopped = True
        return {}


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(settings, "use_robot_worker", True)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(tools.asyncio, "sleep", lambda s: real_sleep(0))  # no real waiting in tests
    w = FakeWorker()
    for n in ("health", "submit", "status", "stop"):
        monkeypatch.setattr(robot_client, n, getattr(w, n))
    return w


async def test_shuffle_runs_in_background_and_notifies(worker):
    state, notes = GameState(), []

    async def notify(t):
        notes.append(t)

    state.notify = notify
    res = await run_tool(state, "start_game", {"game_id": "reorder"}, None)
    assert res["status"] == "shuffling" and "target_order" not in res  # order not revealed yet
    assert state.phase == "shuffling"
    early = await run_tool(state, "check_arrangement", {}, None)
    assert not early["ok"] and "still moving" in early["error"]
    await state.watcher
    assert state.phase == "awaiting" and "finished mixing" in notes[0]


async def test_chat_gets_pending_note(worker):
    state = GameState()
    await run_tool(state, "start_game", {"game_id": "reorder"}, None)
    await state.watcher
    assert state.pending_note and state.view()["pendingNote"]


async def test_robot_failure_alerts_caregiver(worker):
    worker.outcome = "failed"
    state = GameState()
    await run_tool(state, "start_game", {"game_id": "reorder"}, None)
    await state.watcher
    assert state.phase == "needs_staff" and state.help_requested


async def test_worker_not_ready(worker):
    worker.ready = False
    res = await run_tool(GameState(), "start_game", {"game_id": "reorder"}, None)
    assert not res["ok"] and "not ready" in res["error"]


async def test_stop_halts_robot(worker):
    state = GameState()
    await run_tool(state, "start_game", {"game_id": "reorder"}, None)
    await run_tool(state, "stop", {}, None)
    assert worker.stopped and state.phase == "stopped"
