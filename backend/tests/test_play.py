"""Playground API: run Remember the Order by tapping, simulated mover (no robot)."""

from fastapi.testclient import TestClient

from app import main
from app.games.table_watch import SETTLE_S


def test_playground_round_with_table_screen():
    with TestClient(main.app) as c:
        r = c.post("/api/play/start", json={"sessionId": "p1", "mover": "simulated"}).json()
        screen = r["state"]["screen"]
        assert screen["kind"] == "table" and screen["phase"] == "study" and len(screen["row"]) >= 2
        original = r["state"]["exercise"]["answer"]
        r = c.post("/api/play/say", json={"sessionId": "p1", "text": " ".join(original)}).json()
        assert r["state"]["screen"]["status"].startswith("Your turn")
        reading = {"order": original, "seen": original, "hands": False}
        c.post("/api/play/watch", json={"sessionId": "p1", "reading": reading})
        import time
        time.sleep(SETTLE_S + 0.1)
        r = c.post("/api/play/watch", json={"sessionId": "p1", "reading": reading}).json()
        assert r["say"] and r["state"]["exercise"]["phase"] == "reminisce"
        assert c.post("/api/play/stop", json={"sessionId": "p1"}).json()["ok"]


def test_playground_rejects_unknown_mover_and_session():
    with TestClient(main.app) as c:
        assert c.post("/api/play/start", json={"sessionId": "p2", "mover": "teleport"}).status_code == 422
        assert c.post("/api/play/say", json={"sessionId": "nope", "text": "hi"}).status_code == 404
