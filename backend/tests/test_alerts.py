"""Caregiver texts: the alert text is built on every OS, and alert_caregiver hands it to Photon."""

import asyncio
import re

from app.alerts import notify
from app.voice import tools


async def test_send_alert_builds_text(monkeypatch):
    sent = []

    async def fake_send(to, text):
        sent.append((to, text))

    monkeypatch.setattr(notify, "send_text", fake_send)
    assert await notify.send_alert("help_requested", "s", "Resident is thirsty", to="+15551234567", patient="Rose")
    to, text = sent[0]
    assert to == "+15551234567"
    assert re.fullmatch(r"ReMind alert, (1[0-2]|[1-9]):\d\d (AM|PM), Rose: Resident is thirsty", text)


async def test_alert_caregiver_texts_and_records_failure(monkeypatch):
    sent = []

    async def fake_send(to, text):
        sent.append(to)
        return "Photon said no"

    monkeypatch.setattr(notify, "send_text", fake_send)
    state = tools.GameState(caregiver_phone="+15551234567", patient_name="Rose", session_id="s")
    res = await tools.run_tool(state, "alert_caregiver", {"reason": "Resident is thirsty"}, None)
    assert res["ok"]
    await asyncio.gather(*tools._tasks)
    assert sent == ["+15551234567"]
    assert state.alerts == ["Resident is thirsty", "Text to caregiver failed (see backend log)"]
