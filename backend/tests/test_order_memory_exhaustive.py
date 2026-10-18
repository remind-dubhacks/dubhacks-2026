"""Remember the Order, exhaustively: every starting order x every shuffle x every way of putting
the objects back (camera, spoken order, "done" with no camera, unsure, partial camera reading),
and for each guided question every kind of answer (right, a different object, unsure).

Props: lipstick, blue keychain, white keycap.
  3 objects: 6 starting orders x 5 shuffles = 30 rows to restore
  2 objects: 6 starting orders x 1 shuffle  =  6 rows to restore
Each row is replayed through every restore path, so the suite walks well over a thousand sessions.
Checked every time: the moves really produce the mixed row, instructions say the right things,
guidance only offers sensible choices, the round always ends with the row restored, the help
level is classified correctly, and nothing spoken judges the person."""

import itertools
import re

import pytest

from app.games.find_remember import BANNED_WORDS, OBJECTS, at
from app.games.order_memory import OrderMemory

PROPS = ["lipstick", "blue keychain", "white keycap"]
SPOTS = {2: ["left", "right"], 3: ["left", "middle", "right"]}

ROWS = [(orig, pat) for n in (2, 3) for orig in itertools.permutations(PROPS, n)
        for pat in itertools.permutations(range(n)) if pat != tuple(range(n))]
SCENARIOS = {"count": 0}


def ids(case):
    orig, pat = case
    return "-".join(OBJECTS[o]["short"] for o in orig) + "/" + "".join(map(str, pat))


def kind(text: str, row: list[str]) -> None:
    low = text.lower()
    for w in BANNED_WORDS:
        assert w not in low, f"judging word {w!r} in: {text}"
    for o in OBJECTS:  # never mention an object that isn't on the table this round
        if re.search(rf"\bthe {re.escape(o)}\b", low):
            assert o in row, f"mentions {o} but row is {row}: {text}"


def game(orig: tuple[str, ...], pattern: tuple[int, ...]) -> OrderMemory:
    om = OrderMemory(objects=PROPS, seed=hash((orig, pattern)) % 10_000)
    om.level = 1 if len(orig) == 2 else 2
    om.round, om.original, om.current, om.phase = 1, list(orig), list(orig), "study"
    om.first_left = orig[0]
    return om


def mixed(orig, pattern):
    om = game(orig, pattern)
    step = om.shuffle(pattern=pattern)
    om.after_shuffle()
    return om, step


def drive_guided(om: OrderMemory, step, style: str, row: list[str], max_turns: int = 6):
    """Answer each guided question the way `style` says, until the row is restored."""
    said = [step.say]
    for _ in range(max_turns):
        if step.phase != "restore":
            break
        assert om.guide is not None, "a restore prompt without a question would leave the person stuck"
        spot = om.spots[om.guide]
        want = om.original[om.guide]
        assert len(step.options) == 2 and want in step.options, step.options
        assert all(om.original.index(o) not in om.placed for o in step.options), "offered an object already placed"
        assert at(spot) in step.say, f"question doesn't say which spot: {step.say}"
        other = next(o for o in step.options if o != want)
        answer = {"right": f"the {want}", "other": f"the {other}", "unsure": "I'm not sure"}[style]
        step = om.check(answer)
        said.append(step.say)
        if style == "right":
            assert f"Yes, the {want} goes {at(spot)}" in step.say
        else:
            assert f"It's the {want} {at(spot)}" in step.say
    for s in said:
        kind(s, row)
    return step


@pytest.mark.parametrize("case", ROWS, ids=[ids(c) for c in ROWS])
def test_every_row_every_shuffle_every_restore(case):
    orig, pattern = case
    n, spots, row = len(orig), SPOTS[len(orig)], list(orig)

    # --- study instructions name the row left to right and invite saying it back
    om = game(orig, pattern)
    om.round = 0
    om.rng.seed(0)
    s = om.start()
    assert om.spots == SPOTS[len(om.original)] and "from left to right" in s.say and "say them back" in s.say
    kind(s.say, om.original)

    # --- path G: saying the row back (exact / jumbled / nothing useful) is never judged
    for say in (" ".join(orig), " ".join(reversed(orig)), "um"):
        om = game(orig, pattern)
        nxt = om.say_back(say)
        chant = ", ".join(OBJECTS[o]["short"] for o in orig)
        if say == " ".join(orig):
            assert nxt.say.startswith("Lovely, just like that.")
        else:
            assert f"Let's say it once more together: {chant}." in nxt.say
        assert nxt.phase == "shuffle" and om.current != row
        kind(nxt.say, row)
        SCENARIOS["count"] += 1

    # --- the shuffle: a real mix, and the listed moves reproduce it exactly
    om, step = mixed(orig, pattern)
    assert om.current == [orig[i] for i in pattern] and om.current != row and sorted(om.current) == sorted(row)
    layout = dict(zip(spots, orig))
    for m in step.moves:
        assert m["from"] != m["to"] and layout[m["from"]] == m["object"]
    after = dict(layout)
    for m in step.moves:
        after[m["to"]] = m["object"]
    assert [after[sp] for sp in spots] == om.current
    assert {m["object"] for m in step.moves} == {o for i, o in enumerate(orig) if om.current[i] != o}
    assert "hands resting on your lap" in step.say
    kind(step.say, row)

    # --- path A: camera (or caregiver) reads every possible arrangement
    for obs in itertools.permutations(orig):
        obs = list(obs)
        for style in ("right", "other", "unsure"):
            om, _ = mixed(orig, pattern)
            first = om.check("done", observed=obs)
            SCENARIOS["count"] += 1
            if obs == row:
                assert "exactly how they were" in first.say and om.log[-1].help == 0
                kind(first.say, row)
                break  # nothing to guide
            right_now = [o for i, o in enumerate(orig) if obs[i] == o]
            if len(right_now) == 1:
                assert f"The {OBJECTS[right_now[0]]['short']} is in just the right spot" in first.say
            else:
                assert "Good effort" in first.say
            assert om.placed == [i for i, o in enumerate(orig) if obs[i] == o]
            end = drive_guided(om, first, style, row)
            assert end.phase == "reminisce" and om.current == row and "just like before" in end.say
            assert om.log[-1].help == (1 if style == "right" else 2)

    # --- path B: the person says an order out loud (no camera)
    for spoken in itertools.permutations(orig):
        om, _ = mixed(orig, pattern)
        first = om.check(" then ".join(spoken))
        SCENARIOS["count"] += 1
        if list(spoken) == row:
            assert "exactly how they were" in first.say and om.log[-1].help == 0
        else:
            end = drive_guided(om, first, "right", row)
            assert om.current == row and end.phase == "reminisce"

    # --- path C: "done" with no camera -> asks once for the order in words, then guides
    for style in ("right", "other", "unsure"):
        om, _ = mixed(orig, pattern)
        ask = om.check("done")
        assert "tell me the order" in ask.say and om.guide is None
        first = om.check("done")
        assert first.say.startswith("That's okay.") and om.guide == 0
        end = drive_guided(om, first, style, row)
        assert om.current == row and end.phase == "reminisce"
        SCENARIOS["count"] += 1

    # --- path D: unsure straight away -> gentle help from the left, no extra question
    for style in ("right", "other", "unsure"):
        om, _ = mixed(orig, pattern)
        first = om.check("I don't know")
        assert first.say.startswith("That's okay.") and "on the left" in first.say
        end = drive_guided(om, first, style, row)
        assert om.current == row
        SCENARIOS["count"] += 1

    # --- path E: the camera misses an object -> never treated as an answer
    om, _ = mixed(orig, pattern)
    partial = om.check("done", observed=list(orig[:-1]))
    assert "tell me the order" in partial.say and om.log == []
    SCENARIOS["count"] += 1

    # --- path F: camera shows the right order in the middle of guidance -> finishes at once
    if n == 3:
        om, _ = mixed(orig, pattern)
        first = om.check("I don't know")
        done = om.check("done", observed=row)
        assert "just like before" in done.say and om.current == row and om.log[-1].help == 1
        SCENARIOS["count"] += 1


def test_shuffle_rejects_non_mixes():
    om = game(tuple(PROPS), (1, 0, 2))
    with pytest.raises(ValueError):
        om.shuffle(pattern=(0, 1, 2))
    with pytest.raises(ValueError):
        om.shuffle(pattern=(0, 0, 1))


def test_random_shuffles_cover_every_pattern_fairly():
    from collections import Counter

    seen = Counter()
    for seed in range(3000):
        om = OrderMemory(objects=PROPS, seed=seed)
        om.level = 2
        om.start()
        om.shuffle()
        seen[om.last_pattern] += 1
    assert set(seen) == {p for p in itertools.permutations(range(3)) if p != (0, 1, 2)}
    assert min(seen.values()) > 3000 / 5 * 0.8  # roughly uniform


def test_two_objects_always_swap():
    for seed in range(50):
        om = OrderMemory(objects=PROPS, seed=seed)
        om.start()
        assert len(om.original) == 2
        om.shuffle()
        assert om.current == om.original[::-1]


def test_scenario_count_is_large():
    # Runs last in this module (pytest keeps file order).
    assert SCENARIOS["count"] >= 1000, SCENARIOS["count"]
