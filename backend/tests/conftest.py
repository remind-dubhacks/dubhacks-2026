import os

# Tests never depend on the local backend/.env for game setup or the database (load_dotenv won't override these).
os.environ["FIND_REMEMBER_MOVER"] = "simulated"
os.environ["FIND_REMEMBER_OBJECTS"] = "blue keychain,lipstick,white keycap"
os.environ["MONGODB_URI"] = ""

import pytest  # noqa: E402

from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def backboard_off(monkeypatch):
    """Tests run with Backboard off, whatever backend/.env says; Backboard tests opt in. Startup provisioning of
    assistants is skipped (tested directly in test_memory), so no test reaches the network."""
    import httpx

    from app.voice import memory

    async def no_provision(store):
        pass
    memory._verified.clear()
    # Backboard REST calls fail (as if Backboard were down) unless a test installs its own fake
    monkeypatch.setattr(memory, "_transport", httpx.MockTransport(lambda r: httpx.Response(503)))
    monkeypatch.setattr(settings, "voice_transport", "")
    monkeypatch.setattr(settings, "backboard_api_key", "")
    monkeypatch.setattr(memory, "provision", no_provision)


@pytest.fixture(autouse=True)
def robot_is_ready(monkeypatch):
    """Robot-mode tests assume the arm is ready; tests of the offline fallback override this."""
    from app.voice import tools

    async def ready(max_age_s: float = 15.0) -> bool:
        return True
    monkeypatch.setattr(tools, "robot_ready", ready)
