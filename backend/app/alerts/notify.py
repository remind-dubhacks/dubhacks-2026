"""Message the caregiver (Photon). Logs only until the real integration is added."""
import logging

log = logging.getLogger("remind.alerts")


async def send_alert(kind: str, session_id: str, message: str) -> None:
    """kind: needs_staff | help_requested | repeated_failure"""
    log.warning("ALERT [%s] session=%s: %s", kind, session_id, message)
