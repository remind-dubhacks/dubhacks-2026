"""Spoken prompts from the robot laptop itself (macOS `say`), so the operator hears instructions
without needing a browser tab open or clicked. One queue, one speaker, duplicates dropped.
SERVER_VOICE=0 turns it off (the Studio page then speaks instead)."""

import os
import queue
import shutil
import subprocess
import threading
import time

ENABLED = os.getenv("SERVER_VOICE", "1") == "1" and shutil.which("say") is not None
RATE = os.getenv("SERVER_VOICE_RATE", "180")  # words per minute

_q: "queue.Queue[str]" = queue.Queue()
_current: subprocess.Popen | None = None
_last = {"text": "", "t": 0.0}
_lock = threading.Lock()


def speak(text: str, interrupt: bool = False) -> None:
    if not ENABLED or not text:
        return
    with _lock:
        if text == _last["text"] and time.time() - _last["t"] < 8:
            return
        _last.update(text=text, t=time.time())
    if interrupt:
        while not _q.empty():
            try:
                _q.get_nowait()
            except queue.Empty:
                break
        if _current and _current.poll() is None:
            _current.terminate()
    _q.put(text)


def _worker() -> None:
    global _current
    while True:
        text = _q.get()
        try:
            _current = subprocess.Popen(["say", "-r", RATE, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _current.wait()
        except Exception:  # noqa: BLE001
            time.sleep(0.5)


if ENABLED:
    threading.Thread(target=_worker, daemon=True).start()
