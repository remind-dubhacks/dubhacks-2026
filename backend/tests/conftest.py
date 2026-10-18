import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def direct_gemini(monkeypatch):
    """Tests run on the direct Gemini transport with Backboard off, whatever backend/.env says; Backboard tests opt in."""
    monkeypatch.setattr(settings, "voice_transport", "gemini")
    monkeypatch.setattr(settings, "backboard_api_key", "")
