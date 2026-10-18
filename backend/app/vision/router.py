from fastapi import APIRouter
from pydantic import BaseModel

from ..games.reorder import evaluate
from .checker import read_order

router = APIRouter(prefix="/api/vision", tags=["vision"])

LOW_CONFIDENCE = 0.6


class CheckIn(BaseModel):
    target: list[str]
    imageB64: str | None = None  # omit to use the camera
    mockOrder: list[str] | None = None  # only honoured in VISION_MODE=mock


class CheckOut(BaseModel):
    order: list[str]
    correct: bool
    confidence: float
    needsConfirm: bool
    misplaced: list[str]
    reason: str


@router.post("/check", response_model=CheckOut)
async def check(body: CheckIn) -> CheckOut:
    reading = await read_order(body.target, body.imageB64, body.mockOrder)
    result = evaluate(body.target, reading.order)
    return CheckOut(
        order=reading.order,
        correct=result["correct"],
        confidence=reading.confidence,
        needsConfirm=reading.confidence < LOW_CONFIDENCE,
        misplaced=result["misplaced"],
        reason=result["reason"],
    )
