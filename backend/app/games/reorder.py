"""Reorder game rules: pick a target order, shuffle it, judge an observed order."""
import random

DEFAULT_OBJECTS = ["cup", "apple", "book"]  # placeholder prop set; confirm with the real props
MAX_TRIALS = 3


def shuffled(target: list[str], seed: int | None = None) -> list[str]:
    """Random permutation of `target` that is never already solved."""
    if len(target) < 2:
        return list(target)
    rng = random.Random(seed)
    order = list(target)
    while order == target:
        rng.shuffle(order)
    return order


def evaluate(target: list[str], observed: list[str]) -> dict:
    """Compare a detected left-to-right order with the target.

    Returns {correct, misplaced, reason}; `reason` is plain, kind wording the agent can speak.
    """
    if sorted(observed) != sorted(target):
        return {"correct": False, "misplaced": [], "reason": "I couldn't see all the objects clearly."}
    misplaced = [t for t, o in zip(target, observed) if t != o]
    if not misplaced:
        return {"correct": True, "misplaced": [], "reason": ""}
    first = next(i for i, (t, o) in enumerate(zip(target, observed)) if t != o)
    reason = f"The {target[first]} should be in spot {first + 1}, where the {observed[first]} is now."
    return {"correct": False, "misplaced": misplaced, "reason": reason}


def attempts_left(attempt: int, max_trials: int = MAX_TRIALS) -> int:
    return max(0, max_trials - attempt)
