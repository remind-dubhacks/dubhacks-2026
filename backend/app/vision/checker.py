"""Read the left-to-right object order from a camera image.

`read_order` is the one function to replace with the real Perceptron / camera pipeline.
The mock returns `mock_order` (or the target) so the rest of the app can be built first.
"""
import os
from dataclasses import dataclass


@dataclass
class Reading:
    order: list[str]
    confidence: float


def vision_mode() -> str:
    return os.getenv("VISION_MODE", "mock")  # mock | perceptron


async def read_order(
    expected_ids: list[str], image_b64: str | None = None, mock_order: list[str] | None = None
) -> Reading:
    if vision_mode() == "mock":
        return Reading(order=list(mock_order or expected_ids), confidence=1.0)
    raise NotImplementedError("Real vision not wired yet: capture a frame and call the detector here")
