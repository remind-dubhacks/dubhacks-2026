"""Remember the Order: errorless restore, random shuffles, camera order, voice integration."""

import random
from collections import Counter

import pytest

from app.games.find_remember import BANNED_WORDS
from app.games.order_memory import OrderMemory, order_from_detections, order_from_text
from app.voice import agent
from app.voice.tools import GameState


def kind(text: str) -> None:
    for w in BANNED_WORDS:
        assert w not in text.lower(), f"{w!r} in: {text}"


def to_restore(om: OrderMemory) -> None:
    om.start()
    om.say_back(" ".join(om.original))
    om.after_shuffle()


def test_study_names_left_to_right_and_invites_saying_back():
    om = OrderMemory(seed=1)
    s = om.start()
    assert s.phase == "study" and "from left to right" in s.say and "say them back" in s.say
    assert [m["to"] for m in s.moves] == ["left", "right"]


def test_restored_alone_with_camera():
    om = OrderMemory(seed=2)
    to_restore(om)
    assert om.current != om.original  # really mixed up
    s = om.check("done", observed=list(om.original))
    assert "exactly how they were" in s.say and om.log[-1].help == 0 and s.phase == "reminisce"


def test_partial_order_praises_what_is_right_then_offers_a_choice():
    om = OrderMemory(seed=3)
    om.level = 2
    to_restore(om)
    o = om.original
    wrong = [o[0], o[2], o[1]]  # first spot right, last two swapped
    s = om.check("done", observed=wrong)
    assert f"The {om.short(o[0])} is in just the right spot" in s.say and len(s.options) == 2
    assert o[1] in s.options and "in the middle" in s.say
    s2 = om.check(f"the {o[1]}")  # answers the choice correctly; the last spot follows
    assert f"Yes, the {o[1]} goes in the middle" in s2.say and f"And the {o[2]} goes on the right" in s2.say
    assert om.current == om.original and om.log[-1].help == 1


def test_without_camera_it_asks_for_words_before_helping():
    om = OrderMemory(seed=4)
    to_restore(om)
    ask = om.check("done")
    assert "tell me the order" in ask.say and om.help == 0
    s = om.check(" then ".join(om.original))
    assert "exactly how they were" in s.say


def test_unsure_goes_straight_to_gentle_help():
    om = OrderMemory(seed=5)
    to_restore(om)
    s = om.check("I don't know")
    assert s.say.startswith("That's okay.") and om.original[0] in s.options


def test_shuffle_patterns_are_varied_and_never_repeat_back_to_back():
    counts = Counter()
    for seed in range(300):
        om = OrderMemory(seed=seed)
        om.level = 2
        om.start()
        prev = None
        for _ in range(4):
            om.shuffle()
            assert om.current != om.original
            assert om.last_pattern != prev or prev is None
            if om.log == []:
                counts[om.last_pattern] += 1
            prev = om.last_pattern
            om.last_pattern = prev
    assert len(counts) == 5  # every way to mix 3 objects shows up


def test_after_needing_help_the_next_shuffle_is_an_easy_swap():
    om = OrderMemory(seed=7)
    om.level = 2
    om.start()
    om.log.append(type("R", (), {"help": 2})())  # last round needed help
    for _ in range(20):
        om.shuffle()
        moved = sum(a != b for a, b in zip(om.current, om.original))
        assert moved == 2


@pytest.mark.parametrize("seed", range(200))
def test_random_sessions_always_end_restored_and_kind(seed):
    rng = random.Random(seed)
    om = OrderMemory(seed=seed, max_rounds=3)
    step = om.start()
    said = [step.say]
    for _ in range(80):
        if step.phase == "done":
            break
        if step.phase == "study":
            step = om.say_back(rng.choice([" ".join(om.original), "um", " ".join(reversed(om.original))]))
        elif step.phase == "shuffle":
            step = om.after_shuffle()
        elif step.phase == "restore":
            cam = rng.choice([None, list(om.original), om.current, rng.sample(om.original, len(om.original)), om.original[:1]])
            step = om.check(rng.choice(["done", "I'm not sure", "", " ".join(om.original)]), observed=cam)
        elif step.phase == "reminisce":
            step = om.shared(rng.choice(["skip", "I wore it to dances", ""]))
        elif step.phase == "recall":
            step = om.recall(rng.choice(["the lipstick", "keychain", "no idea", "keycap"]))
        said.append(step.say)
    assert step.phase == "done"
    assert all(r.help in (0, 1, 2) for r in om.log) and len(om.log) <= 3
    for s in said:
        kind(s)


def test_camera_detections_to_left_to_right_order():
    dets = [
        {"name": "white keycap", "center": [0.8, 0.5], "score": 0.7},
        {"name": "lipstick", "center": [0.2, 0.5], "score": 0.9},
        {"name": "blue keychain", "center": [0.5, 0.4], "score": 0.8},
        {"name": "blue keychain", "center": [0.9, 0.9], "score": 0.6},  # weaker duplicate ignored
        {"name": None, "center": [0.1, 0.1], "score": 0.3},
    ]
    assert order_from_detections(dets, ["lipstick", "blue keychain", "white keycap"]) == ["lipstick", "blue keychain", "white keycap"]
    assert order_from_detections(dets[:2], ["lipstick", "blue keychain", "white keycap"]) is None  # never guess


def test_order_from_words():
    objs = ["lipstick", "blue keychain", "white keycap"]
    assert order_from_text("keycap first, then the lipstick and the keychain", objs) == ["white keycap", "lipstick", "blue keychain"]


# ---------------------------------------------------------------- voice integration (offline rules)


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(agent, "provider", lambda: "rules")


async def test_voice_memory_game_end_to_end(offline):
    st, hist = GameState(), []
    reply, _ = await agent.turn(st, hist, "Can we play the memory game?", None)
    assert st.game == "order_memory" and "from left to right" in reply
    original = list(st.fr.original)
    reply, _ = await agent.turn(st, hist, " ".join(original), None)
    assert "mixed up" in reply and "put them back" in reply  # simulated shuffle
    reply, _ = await agent.turn(st, hist, "done", original)  # table/camera now shows the original order
    assert "exactly how they were" in reply
    assert st.view()["exercise"]["summary"]["restoredAlone"] == 1


async def test_find_and_remember_still_starts_by_name(offline):
    st = GameState()
    await agent.turn(st, [], "let's play find and remember", None)
    assert st.game == "find_remember"
