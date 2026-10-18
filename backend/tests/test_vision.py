from fastapi.testclient import TestClient

from app import main


def test_check_mock():
    with TestClient(main.app) as c:
        ok = c.post("/api/vision/check", json={"target": ["a", "b"]}).json()
        bad = c.post("/api/vision/check", json={"target": ["a", "b"], "mockOrder": ["b", "a"]}).json()
    assert ok["correct"] and not bad["correct"] and bad["reason"]
