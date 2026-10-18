import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def backboard_off(monkeypatch):
    """Tests run with Backboard off, whatever backend/.env says; Backboard tests opt in. Startup provisioning of
    assistants is skipped (tested directly in test_memory), so no test reaches the network."""
    from app.voice import memory

    async def no_provision(store):
        pass
    monkeypatch.setattr(settings, "voice_transport", "")
    monkeypatch.setattr(settings, "backboard_api_key", "")
    monkeypatch.setattr(memory, "provision", no_provision)
