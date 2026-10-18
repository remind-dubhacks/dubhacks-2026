"""Find & Remember: the protocol's promises, checked.

- errorless: every round ends with the object found; nothing spoken ever judges an answer
- cueing ladder: open question -> two-way choice -> shown together
- adaptive difficulty, spaced recall, optional reminiscence, non-clinical summary
- the voice agent runs the exercise deterministically (no LLM needed) and puts stop/distress first"""

import random

import pytest

from app.games.find_remember import BANNED_WORDS, OBJECTS, FindRemember
from app.voice import agent
from app.voice.tools import GameState


def assert_kind(text: str) -> None:
    low = text.lower()
    for w in BANNED_WORDS:
        assert w not in low, f"banned word {w!r} in: {text}"


def play_round(fr: FindRemember, answer: str = "correct") -> list[str]:
    """Drive one round; answer is 'correct', 'unsure' or 'other'. Returns everything said."""
    said = []
    if fr.phase != "choose":
        said.append(fr.start().say)
    said.append(fr.choose(fr.short(list(fr.layout.values())[0])).say)
    said.append(fr.after_move().say)
    for _ in range(3):
        right = fr.where(fr.target)
        reply = right if answer == "correct" else "I don't know" if answer == "unsure" else next(s for s in fr.layout if s != right)
        step = fr.answer(reply)
        said.append(step.say)
        if step.phase == "act":
            break
    said.append(fr.did_task().say)
    said.append(fr.shared("I wrote letters to my sister").say)
    return said


def test_happy_round_flows_and_praises():
    fr = FindRemember(seed=1)
    intro = fr.start()
    assert intro.expect == "choice" and "Which one would you like" in intro.say
    pick = list(fr.layout.values())[0]
    watch = fr.choose(f"the {fr.short(pick)}")
    assert fr.target == pick and watch.moves and "Hands resting" in watch.say
    assert fr.after_move().say == f"Where is the {pick} now?"
    found = fr.answer(fr.where(pick))
    assert found.phase == "act" and "Well spotted" in found.say and "put it in the tray" in found.say
    memory = fr.did_task()
    assert memory.phase == "reminisce" and "You can skip" in memory.say
    assert fr.log[0].cue == 0


def test_errorless_ladder_never_judges_and_always_ends_found():
    fr = FindRemember(seed=2)
    fr.start()
    fr.choose("keychain")
    fr.after_move()
    choice = fr.answer("I'm not sure")
    assert choice.phase == "find" and len(choice.options) == 2 and fr.where(fr.target) in choice.options
    assert choice.say.startswith("That's okay.")
    other = next(o for o in choice.options if o != fr.where(fr.target))
    shown = fr.answer(other)
    assert shown.phase == "act" and "Let's find it together" in shown.say
    assert fr.log[-1].cue == 2
    for s in (choice.say, shown.say):
        assert_kind(s)


@pytest.mark.parametrize("seed", range(150))
def test_random_sessions_stay_kind_and_bounded(seed):
    rng = random.Random(seed)
    fr = FindRemember(seed=seed, max_rounds=4)
    step = fr.start()
    said = [step.say]
    for _ in range(60):
        if step.phase == "done":
            break
        reply = {
            "choose": lambda: rng.choice(["the pen", "keychain", "um", "the white one"]),
            "watch": lambda: "moved",
            "find": lambda: rng.choice(["left", "right", "middle", "I don't know", "", "over there"]),
            "act": lambda: rng.choice(["done", "ok", "I can't"]),
            "reminisce": lambda: rng.choice(["skip", "I used to write to my mum", ""]),
            "recall": lambda: rng.choice(["the pen", "the keychain", "no idea", "keycap"]),
        }[step.phase]()
        step = {"choose": fr.choose, "watch": lambda _: fr.after_move(), "find": fr.answer,
                "act": lambda r: fr.did_task(r != "I can't"), "reminisce": fr.shared, "recall": fr.recall}[step.phase](reply)
        said.append(step.say)
    assert step.phase == "done", "session must end on its own"
    assert len(fr.log) <= 4 and all(r.cue <= 2 for r in fr.log)
    for s in said:
        assert_kind(s)


def test_difficulty_adapts_both_ways():
    fr = FindRemember(seed=3, max_rounds=10)
    play_round(fr, "correct")
    play_round(fr, "correct")
    assert fr.level == 2  # two easy finds -> one more object next round
    while fr.phase == "recall":
        fr.recall(fr.tray[0])
    play_round(fr, "other")  # needed to be shown -> easier again
    assert fr.level == 1


def test_spaced_recall_expands_after_success_and_shrinks_after_help():
    fr = FindRemember(seed=4, max_rounds=10)
    first = play_round(fr)
    assert "first thing we put in the tray" not in first[-1]  # spaced: not straight away
    said = play_round(fr)
    assert "What was the first thing we put in the tray?" in said[-1]
    asked_at = fr.round
    nxt = fr.recall(fr.tray[0])
    assert "What a good memory" in nxt.say and fr.recall_due == asked_at + 2  # interval grows
    fr2 = FindRemember(seed=5, max_rounds=10)
    play_round(fr2)
    play_round(fr2)
    choice = fr2.recall("I can't remember")
    assert choice.phase == "recall" and fr2.tray[0] in choice.options
    asked_at = fr2.round
    reveal = fr2.recall("hmm")
    assert f"It was the {fr2.tray[0]}" in reveal.say and fr2.recall_due == asked_at + 1 and fr2.recall_step == 0  # shrinks


def test_reminiscence_is_optional_and_never_corrected():
    fr = FindRemember(seed=6)
    play_round(fr)
    assert fr.log[-1].shared_memory is True
    fr2 = FindRemember(seed=6)
    fr2.start(); fr2.choose("anything"); fr2.after_move(); fr2.answer(fr2.where(fr2.target)); fr2.did_task()
    assert fr2.shared("skip").say.startswith("Of course")
    assert fr2.log[-1].shared_memory is False


def test_summary_is_non_clinical():
    fr = FindRemember(seed=7)
    play_round(fr)
    s = fr.summary()
    assert "Not a clinical score" in s["note"] and "time" not in str(s).lower()


def test_every_object_has_opinion_and_memory_prompts():
    for name, o in OBJECTS.items():
        assert o["use"].endswith("?") and len(o["memories"]) >= 2
        for p in [o["use"], *o["memories"]]:
            assert_kind(p)


# ---------------------------------------------------------------- voice agent integration (rules, no key)


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(agent, "provider", lambda: "rules")


async def test_voice_runs_the_exercise_offline(offline):
    st, hist = GameState(), []
    reply, _ = await agent.turn(st, hist, "Let's play find and remember", None)
    assert "Which one would you like" in reply and st.phase == "exercise"
    pick = list(st.fr.layout.values())[0]
    reply, calls = await agent.turn(st, hist, f"the {pick}", None)
    assert calls[0]["name"] == "exercise_step" and f"Where is the {pick} now?" in reply  # simulated mover
    reply, _ = await agent.turn(st, hist, f"on the {st.fr.where(pick)}", None)
    assert "Well spotted" in reply
    assert st.view()["exercise"]["summary"]["rounds"] == 1


async def test_stop_and_distress_come_first(offline):
    st = GameState()
    await agent.turn(st, [], "play find and remember", None)
    reply, calls = await agent.turn(st, [], "I'm tired, I want to stop", None)
    assert calls[0]["name"] in ("stop", "alert_caregiver")
    st2 = GameState()
    await agent.turn(st2, [], "play find and remember", None)
    reply, calls = await agent.turn(st2, [], "this makes me upset", None)
    assert calls[0]["name"] == "alert_caregiver" and "caregiver" in reply and st2.help_requested


async def test_i_dont_remember_does_not_start_a_game(offline):
    st = GameState()
    await agent.turn(st, [], "I don't remember", None)
    assert st.game is None
