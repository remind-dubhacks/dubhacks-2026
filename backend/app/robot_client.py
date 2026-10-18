import httpx

from .config import settings


class RobotWorkerError(Exception):
    pass


async def _request(method: str, path: str, **kw) -> dict:
    try:
        async with httpx.AsyncClient(base_url=settings.robot_worker_url, timeout=5) as client:
            r = await client.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise RobotWorkerError(f"robot worker unreachable: {e}") from e
    if r.status_code >= 400:
        raise RobotWorkerError(f"robot worker {r.status_code}: {r.text}")
    return r.json()


async def health() -> dict:
    return await _request("GET", "/health")


async def submit(job_id: str, action_id: str, object_id: str) -> dict:
    return await _request("POST", "/jobs", json={"jobId": job_id, "actionId": action_id, "objectId": object_id})


async def status(job_id: str) -> dict:
    return await _request("GET", f"/jobs/{job_id}")


async def stop() -> dict:
    return await _request("POST", "/stop")
