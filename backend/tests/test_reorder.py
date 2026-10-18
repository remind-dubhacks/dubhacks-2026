from app.games.reorder import evaluate, shuffled

T = ["cup", "apple", "book"]


def test_shuffle_never_solved():
    for seed in range(50):
        assert shuffled(T, seed) != T


def test_correct():
    assert evaluate(T, T)["correct"]


def test_wrong_has_reason():
    r = evaluate(T, ["apple", "cup", "book"])
    assert not r["correct"] and r["misplaced"] == ["cup", "apple"] and "cup" in r["reason"]
