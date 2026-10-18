"""Fire-and-forget work that must not hold up a request (memory seeding, the after-call digest, closing Backboard).
The server waits for it on shutdown, so a `--reload` restart does not drop a memory that is being saved."""
import asyncio
import logging

log = logging.getLogger("remind.tasks")

_pending: set[asyncio.Task] = set()


def background(coro) -> None:
    """Run coro without waiting, keeping a reference so the task is not garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def drain(timeout_s: float = 10.0) -> None:
    """Wait (up to timeout_s) for background work still running, e.g. on shutdown."""
    if not _pending:
        return
    log.info("waiting for %d background task(s) before shutdown", len(_pending))
    _, unfinished = await asyncio.wait(set(_pending), timeout=timeout_s)
    if unfinished:
        log.warning("%d background task(s) did not finish within %.0f s and were dropped", len(unfinished), timeout_s)
