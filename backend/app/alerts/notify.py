"""Text the caregiver through Photon. The Photon SDK is TypeScript, so the backend calls the small
sidecar in `photon/` (POST /send). Without PHOTON_SERVICE_URL this only logs."""
import logging
import re
from datetime import datetime

import httpx

from ..config import settings

log = logging.getLogger("remind.alerts")


def normalize_phone(raw: str) -> str:
    """'(206) 230-3852' -> '+12062303852'. 10 digits are assumed to be US; anything with a + is kept as typed."""
    digits = re.sub(r"\D", "", raw or "")
    if (raw or "").strip().startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits if digits else ""


async def send_alert(kind: str, session_id: str, message: str, to: str = "", patient: str = "") -> bool:
    """kind: needs_staff | help_requested | repeated_failure. Returns True if a text was handed to Photon."""
    log.warning("ALERT [%s] session=%s patient=%s: %s", kind, session_id, patient, message)
    if not to:
        return False
    who = f"{patient}: " if patient else ""
    now = datetime.now().astimezone()  # server's local time, e.g. "2:41 PM" (no %-I: it fails on Windows)
    when = f"{now.hour % 12 or 12}:{now:%M %p}"
    error = await send_text(to, f"ReMind alert, {when}, {who}{message}")
    if error:
        log.warning("Photon send failed: %s", error)
    return error is None


async def send_text(to: str, text: str) -> str | None:
    """Hand one text to the Photon bridge. Returns None on success, otherwise a short reason."""
    if not settings.photon_service_url:
        return "PHOTON_SERVICE_URL is not set on the backend"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{settings.photon_service_url.rstrip('/')}/send", json={"to": to, "text": text})
    except httpx.HTTPError:
        return "Could not reach the Photon bridge (is `npm start` running in photon/?)"
    if r.is_success:
        return None
    try:
        return str(r.json().get("error") or r.text)[:200]
    except ValueError:
        return r.text[:200]
