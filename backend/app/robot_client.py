import httpx

from .config import settings


class RobotWorkerError(Exception):
    pass


async def _request(method: str, path: str, timeout: float = 5, **kw) -> dict:
    try:
        async with httpx.AsyncClient(base_url=settings.robot_worker_url, timeout=timeout) as client:
            r = await client.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise RobotWorkerError(f"robot worker unreachable: {e}") from e
    if r.status_code >= 400:
        raise RobotWorkerError(f"robot worker {r.status_code}: {r.text}")
    return r.json()


async def health() -> dict:
    # In perceptron mode the worker asks Perceptron whether the model is ready, which can take ~20 s.
    return await _request("GET", "/health", timeout=30)


async def submit(job_id: str, action_id: str, object_id: str, start: list[str] | None = None) -> dict:
    body = {"jobId": job_id, "actionId": action_id, "objectId": object_id}
    if start:  # shuffles: the row before the move (black/white/purple), so the camera checks it right
        body["start"] = start
    return await _request("POST", "/jobs", json=body)


async def status(job_id: str) -> dict:
    return await _request("GET", f"/jobs/{job_id}")


async def stop() -> dict:
    return await _request("POST", "/stop")
