"""Live table watching for Remember the Order: which keyring is moving, right or wrong placement,
when the agent may speak, hesitation support, and the robot showing or mixing the row."""

import asyncio
import importlib.util
import itertools
from pathlib import Path

import pytest

from app.games import shuffles
from app.games.order_memory import OrderMemory, order_from_text
from app.games.table_watch import HESITATE_S, MIN_GAP_S, SETTLE_S, WRONG_GRACE_S, TableWatch
from app.voice import tools

B, W, P = "black keycap", "white keycap", "purple keycap"
ORIG = [B, W, P]
BANNED = ("wrong", "incorrect", "mistake", "no,", "fail")


def R(order, hands=False, seen=None):
    return {"order": order, "seen": seen if seen is not None else [o for o in order if o], "hands": hands}


def run(watch, script):
    """script: list of (t, reading). Returns all events with their times."""
    out = []
    for t, reading in script:
        out += [(t, e.to_dict()) for e in watch.feed(reading, t)]
    return out


def kinds(evts):
    return [e["kind"] for _, e in evts]


# ---------------------------------------------------------------- shuffle table


def test_backend_shuffles_match_the_robot_worker():
    path = Path(__file__).resolve().parents[2] / "robot_worker/worker/shuffle_math.py"
    spec = importlib.util.spec_from_file_location("shuffle_math", path)
    sm = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["shuffle_math"] = sm  # dataclasses look the module up while building the class
    spec.loader.exec_module(sm)
    for sid, pattern in shuffles.SHUFFLES.items():
        assert tuple(p - 1 for p in sm.permutation(sid)) == pattern, sid


@pytest.mark.parametrize("cur", [list(p) for p in itertools.permutations(ORIG) if list(p) != ORIG])
def test_robot_can_fix_every_mixed_row_in_one_move(cur):
    sid = shuffles.fix_for(cur, ORIG)
    pattern = shuffles.SHUFFLES[sid]
    assert [cur[i] for i in pattern] == ORIG


def test_fix_for_rejects_impossible_rows():
    assert shuffles.fix_for(ORIG, ORIG) is None
    assert shuffles.fix_for([B, W], [W, B]) is None
    assert shuffles.fix_for([B, B, P], ORIG) is None


def test_every_game_shuffle_is_a_trained_robot_skill():
    om = OrderMemory(fixed_start=ORIG, seed=1)
    om.start()
    for pattern in itertools.permutations(range(3)):
        if pattern != (0, 1, 2):
            om.shuffle(pattern=pattern)
            assert om.last_shuffle_id in shuffles.SHUFFLES


def test_robot_rounds_always_start_from_the_trained_layout():
    om = OrderMemory(fixed_start=ORIG, seed=3)
    for _ in range(3):
        om.start()
        assert om.original == ORIG


def test_keycaps_are_told_apart_in_speech():
    assert order_from_text("the purple one, then the black one, then the white keycap", ORIG) == [P, B, W]
    assert order_from_text("black, white, purple", ORIG) == [B, W, P]
    assert order_from_text("keycap", ORIG) == []  # ambiguous with three keycaps: never guess


# ---------------------------------------------------------------- watcher timing


def watch(row=(W, B, P)):
    return TableWatch(original=list(ORIG), row=list(row), t0=0.0)


def test_lifted_object_is_named_while_the_hand_is_there():
    w = watch()
    ev = run(w, [(1, R([None, None, None], hands=True, seen=[B, P]))])
    assert ev == [(1, {"kind": "lifted", "obj": W, "level": 0})]


def test_nothing_is_judged_while_hands_are_on_the_table():
    w = watch()
    ev = run(w, [(t, R([B, W, P], hands=True)) for t in range(1, 10)])
    assert "placed" not in kinds(ev) and "complete" not in kinds(ev)


def test_right_placement_is_reported_only_after_the_row_settles():
    w = watch((W, B, P))
    script = [(1, R([None, None, None], hands=True, seen=[B, P])), (2, R([B, W, P])), (2 + SETTLE_S - 0.1, R([B, W, P]))]
    assert "placed" not in kinds(run(w, script))
    ev = run(w, [(2 + SETTLE_S, R([B, W, P]))])
    assert {"kind": "placed", "obj": B, "spot": 0, "right": True, "level": 0} in [e for _, e in ev]
    assert "complete" in kinds(ev)


def test_wrong_placement_gets_a_grace_period_before_any_cue():
    w = watch((W, B, P))
    t = 1.0
    run(w, [(t, R([W, P, B])), (t + SETTLE_S, R([W, P, B]))])  # swapped the wrong pair
    quiet = run(w, [(t + SETTLE_S + WRONG_GRACE_S - 0.5, R([W, P, B]))])
    assert "wrong_stays" not in kinds(quiet)
    ev = run(w, [(t + SETTLE_S + WRONG_GRACE_S + 0.1, R([W, P, B]))])
    assert kinds(ev) == ["wrong_stays"]


def test_fixing_a_wrong_spot_cancels_its_cue():
    w = watch((W, B, P))
    run(w, [(1, R([W, P, B])), (1 + SETTLE_S, R([W, P, B]))])  # purple wrongly in the middle
    assert 1 in w.wrong_since
    run(w, [(4, R([P, W, B])), (4 + SETTLE_S, R([P, W, B]))])  # middle now right (white)
    assert 1 not in w.wrong_since
    ev = run(w, [(t, R([P, W, B])) for t in range(8, 30)])
    assert all(e.get("spot") != 1 for _, e in ev if e["kind"] == "wrong_stays")


def test_holding_a_keyring_for_long_gets_a_hint():
    w = watch()
    ev = run(w, [(t, R([None, None, None], hands=True, seen=[B, P])) for t in (1, 5)] + [(12, R([None] * 3, seen=[B, P]))])
    assert "holding" in kinds(ev)


def test_hesitation_support_escalates_and_never_repeats():
    w = watch()
    times = [HESITATE_S[0] - 1, HESITATE_S[0], HESITATE_S[0] + 5, HESITATE_S[1], HESITATE_S[2], HESITATE_S[2] + 30]
    ev = run(w, [(t, R([W, B, P])) for t in times])
    assert [e["level"] for _, e in ev if e["kind"] == "hesitate"] == [1, 2, 3]


def test_activity_resets_hesitation():
    w = watch()
    run(w, [(HESITATE_S[0], R([W, B, P]))])
    run(w, [(HESITATE_S[0] + 1, R([None] * 3, hands=True, seen=[W, B, P]))])
    ev = run(w, [(HESITATE_S[0] + 10, R([W, B, P]))])
    assert "hesitate" not in kinds(ev)


def test_cues_are_spaced_out():
    w = watch((W, B, P))
    w.last_cue = 100.0
    w.wrong_since = {0: 0.0}
    assert run(w, [(100 + MIN_GAP_S - 0.1, R([W, B, P]))]) == []


def test_a_partly_visible_row_is_never_judged():
    w = watch()
    ev = run(w, [(t, R([None, None, None], seen=[B, W])) for t in range(1, 6)])
    assert "placed" not in kinds(ev) and "complete" not in kinds(ev)


# ---------------------------------------------------------------- what the agent says


def started(pattern=(1, 0, 2)):
    om = OrderMemory(fixed_start=ORIG, seed=5)
    om.start()
    om.shuffle(pattern=pattern)
    om.after_shuffle()
    return om


def assert_kind(step):
    assert step is not None
    low = step.say.lower()
    assert not any(b in low for b in BANNED), step.say


def test_right_placement_gets_a_short_yes():
    om = started()
    step = om.live([{"kind": "placed", "obj": B, "spot": 0, "right": True}])
    assert_kind(step)
    assert step.say.startswith("Yes, the black one goes on the left")


def test_wrong_placement_alone_stays_quiet():
    om = started()
    assert om.live([{"kind": "placed", "obj": P, "spot": 0, "right": False}]) is None


def test_wrong_that_stays_gets_a_two_way_choice_with_the_right_answer_in_it():
    om = started()
    step = om.live([{"kind": "wrong_stays", "obj": W, "spot": 0}])
    assert_kind(step)
    assert set(step.options) == {B, W}


def test_holding_hint_offers_the_true_start_spot():
    om = started()
    step = om.live([{"kind": "holding", "obj": P}])
    assert_kind(step)
    assert "right" in step.options


@pytest.mark.parametrize("level", [1, 2, 3])
def test_hesitation_cues(level):
    om = started()
    step = om.live([{"kind": "hesitate", "level": level}])
    assert_kind(step)
    if level == 3:
        assert om.offered_show and "robot" in step.say


def test_complete_alone_is_full_praise_and_moves_on():
    om = started()
    step = om.live([{"kind": "placed", "obj": B, "spot": 0, "right": True}, {"kind": "complete"}])
    assert_kind(step)
    assert "exactly how they were" in step.say
    assert om.log[-1].help == 0 and om.phase == "reminisce"


def test_complete_after_help_counts_the_help():
    om = started()
    om.live([{"kind": "hesitate", "level": 2}])
    om.live([{"kind": "complete"}])
    assert om.log[-1].help == 1


def test_robot_showing_counts_as_together_and_rehearses():
    om = started()
    step = om.robot_showed()
    assert_kind(step)
    assert "say them together" in step.say and om.log[-1].help == 2


# ---------------------------------------------------------------- tools: watch loop and robot


def game(mover, monkeypatch):
    monkeypatch.setattr(tools, "FR_MOVER", mover)
    state = tools.GameState()
    asyncio.run(tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None))
    return state


def test_simulated_game_watches_and_finishes_from_the_table(monkeypatch):
    async def go():
        monkeypatch.setattr(tools, "FR_MOVER", "simulated")
        state = tools.GameState()
        await tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None)
        om = state.fr
        await tools.run_tool(state, "exercise_step", {"said": "lipstick"}, None)
        assert om.phase == "restore" and state.watch is not None
        row = R(list(om.original))
        await tools.watch_table(state, row, now=1.0)
        out = await tools.watch_table(state, row, now=1.0 + SETTLE_S)
        assert out["say"] and state.watch is None and om.phase == "reminisce"

    asyncio.run(go())


def test_robot_game_shuffles_with_the_robot_then_watches(monkeypatch):
    jobs = []

    async def fake_shuffle(sid, on_event=None):
        jobs.append(sid)
        return {"status": "succeeded", "check": {"verdict": "ok"}}

    async def go():
        monkeypatch.setattr(tools, "FR_MOVER", "robot")
        monkeypatch.setattr(tools, "robot_shuffle", fake_shuffle)
        state = tools.GameState()
        await tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None)
        om = state.fr
        assert om.original == ORIG
        await tools.run_tool(state, "exercise_step", {"said": "black, white, purple"}, None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert jobs == [om.last_shuffle_id]
        out = await tools.watch_table(state, R([None] * 3))
        assert "All mixed up" in out["say"] and state.watch is not None

        # the person hesitates long enough for the robot to offer, says yes, the robot shows
        state.watch.last_activity = -1000
        offer = await tools.watch_table(state, R(list(om.current)), now=0.0)
        assert "robot" in offer["say"]

        async def cam():
            return R(list(om.current))

        monkeypatch.setattr(tools, "camera_row", cam)
        mixed = list(om.current)
        r = await tools.run_tool(state, "exercise_step", {"said": "yes please"}, None)
        assert "watch together" in r["say"]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert jobs[-1] == shuffles.fix_for(mixed, ORIG)
        out = await tools.watch_table(state, None)
        assert "just like before" in out["say"] and om.log[-1].help == 2

    asyncio.run(go())


def test_robot_failure_calls_a_caregiver(monkeypatch):
    async def broken(sid, on_event=None):
        return {"status": "failed", "errorCode": "shuffle_mismatch"}

    async def go():
        monkeypatch.setattr(tools, "FR_MOVER", "robot")
        monkeypatch.setattr(tools, "robot_shuffle", broken)
        state = tools.GameState()
        await tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None)
        await tools.run_tool(state, "exercise_step", {"said": "black white purple"}, None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        out = await tools.watch_table(state, None)
        assert "caregiver" in out["say"] and state.alerts and state.robot["status"] == "failed"

    asyncio.run(go())


def test_watch_without_camera_is_quiet(monkeypatch):
    async def none():
        return None

    async def go():
        monkeypatch.setattr(tools, "FR_MOVER", "simulated")
        monkeypatch.setattr(tools, "camera_row", none)
        state = tools.GameState()
        await tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None)
        await tools.run_tool(state, "exercise_step", {"said": "x"}, None)
        out = await tools.watch_table(state, None)
        assert out["say"] is None and out.get("camera") is False

    asyncio.run(go())


def test_robot_failure_texts_the_caregiver_through_photon(monkeypatch):
    sent = []

    async def broken(sid, on_event=None):
        return {"status": "failed", "errorCode": "hands_in_workspace"}

    async def fake_alert(kind, session_id, message, to="", patient=""):
        sent.append((kind, to, patient, message))
        return True

    async def go():
        monkeypatch.setattr(tools, "FR_MOVER", "robot")
        monkeypatch.setattr(tools, "robot_shuffle", broken)
        monkeypatch.setattr(tools, "send_alert", fake_alert)
        state = tools.GameState(patient_name="Rose", caregiver_phone="+15555550100", session_id="s1")
        await tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None)
        await tools.run_tool(state, "exercise_step", {"said": "black white purple"}, None)
        for _ in range(4):
            await asyncio.sleep(0)
        assert sent and sent[0][0] == "needs_staff" and sent[0][1] == "+15555550100" and sent[0][2] == "Rose"
        assert "hands_in_workspace" in sent[0][3] and state.help_requested

    asyncio.run(go())


def test_robot_events_are_spoken_by_the_companion(monkeypatch):
    async def with_events(sid, on_event=None):
        on_event({"kind": "moving"})
        on_event({"kind": "paused_for_hand"})
        on_event({"kind": "resumed"})
        return {"status": "succeeded", "check": {"verdict": "ok"}}

    async def go():
        monkeypatch.setattr(tools, "FR_MOVER", "robot")
        monkeypatch.setattr(tools, "robot_shuffle", with_events)
        state = tools.GameState()
        await tools.run_tool(state, "start_game", {"game_id": "order_memory"}, None)
        await tools.run_tool(state, "exercise_step", {"said": "black white purple"}, None)
        for _ in range(4):
            await asyncio.sleep(0)
        out = await tools.watch_table(state, None)
        assert out["say"].startswith("I'll wait until the table is clear")
        assert "Carrying on" in out["say"] and "All mixed up" in out["say"]

    asyncio.run(go())


def test_overheating_arm_texts_the_caregiver_once(monkeypatch):
    sent = []

    async def fake_alert(kind, session_id, message, to="", patient=""):
        sent.append(message)
        return True

    class Resp:
        def json(self):
            return {"follower": {"gripper": {"ok": True, "tempC": 62}, "elbow_flex": {"ok": True, "tempC": 50}}}

    class Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def get(self, url, **k): return Resp()

    async def go():
        monkeypatch.setattr(tools, "send_alert", fake_alert)
        monkeypatch.setattr(tools.httpx, "AsyncClient", Client)
        state = tools.GameState(caregiver_phone="+15555550100", patient_name="Rose")
        assert "gripper at 62" in await tools.check_motors(state)
        assert await tools.check_motors(state) is None
        await asyncio.sleep(0)
        assert len(sent) == 1

    asyncio.run(go())


def test_session_summary_is_plain_facts_without_a_score():
    om = started()
    om.live([{"kind": "complete"}])
    state = tools.GameState(games_played=["order_memory", "faces"], fr=om,
                            observations=[{"engagement": "engaged", "note": "Talked about her sister."}])
    text = tools.session_summary(state)
    assert "Remember the Order: 1 rows (1 alone" in text and "Famous faces" in text and "sister" in text
    assert "score" not in text.lower() and "%" not in text
    assert tools.session_summary(tools.GameState()) == ""
