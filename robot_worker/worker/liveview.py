"""Always-live Rerun view of the robot cameras.

One Rerun viewer stays open on RERUN_PORT. LeRobot runs (teleop/record) stream into it via
--display_ip/--display_port, and whenever LeRobot isn't using the cameras this thread streams the
side and wrist cameras into the same viewer, so the window never goes dark between batches.
It hands the cameras back (releases them) whenever anything else needs them."""

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("liveview")

RERUN_HOST = "127.0.0.1"
RERUN_PORT = int(os.getenv("RERUN_PORT", "9876"))
FPS = float(os.getenv("LIVE_VIEW_FPS", "10"))
ROOT = Path(__file__).resolve().parent.parent


def viewer_running() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((RERUN_HOST, RERUN_PORT)) == 0


def ensure_viewer() -> bool:
    """Start one Rerun viewer window if none is listening. Returns True when one is available."""
    if viewer_running():
        return True
    exe = shutil.which("rerun", path=str(ROOT / ".venv/bin")) or shutil.which("rerun")
    if not exe:
        log.warning("rerun CLI not found; install the hardware extra")
        return False
    subprocess.Popen([exe, "--port", str(RERUN_PORT), "--memory-limit", "15%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        if viewer_running():
            return True
        time.sleep(0.25)
    return False


def display_args() -> list[str]:
    """Extra lerobot-record / lerobot-teleoperate flags so runs stream into the shared viewer."""
    return [f"--display_ip={RERUN_HOST}", f"--display_port={RERUN_PORT}"] if ensure_viewer() else []


class LiveView:
    def __init__(self, busy, cameras) -> None:
        """`busy()` -> True while LeRobot owns the cameras; `cameras()` -> {"side": idx, "wrist": idx}."""
        self.busy, self.cameras = busy, cameras
        self.enabled = os.getenv("LIVE_VIEW", "1") == "1"
        self.holding = False  # True while this thread has the cameras open
        self.paused_until = 0.0  # previews/vision ask us to step aside
        self.gen = 0  # bump to make the loop release cameras now
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def release(self, hold_off: float = 2.0, timeout: float = 4.0) -> None:
        """Close our cameras (e.g. before LeRobot or a preview opens them)."""
        self.paused_until = time.time() + hold_off
        self.gen += 1
        end = time.time() + timeout
        while self.holding and time.time() < end:
            time.sleep(0.05)

    def status(self) -> dict:
        return {"enabled": self.enabled, "streaming": self.holding, "viewer": viewer_running(), "port": RERUN_PORT, "error": self.error}

    def _should_stream(self) -> bool:
        return self.enabled and not self.busy() and time.time() >= self.paused_until

    def _run(self) -> None:
        import cv2
        import rerun as rr

        connected = False
        while True:
            if not self._should_stream():
                time.sleep(0.3)
                continue
            if not ensure_viewer():
                self.error = "Rerun viewer not available"
                time.sleep(3)
                continue
            if not connected:
                rr.init("remind_live", spawn=False)
                rr.connect_grpc(url=f"rerun+http://{RERUN_HOST}:{RERUN_PORT}/proxy")
                connected = True
            gen = self.gen
            caps = {}
            for name, idx in self.cameras().items():
                cap = cv2.VideoCapture(idx)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                caps[name] = cap
            self.holding, self.error = True, None
            try:
                while self._should_stream() and gen == self.gen:
                    for name, cap in caps.items():
                        ok, frame = cap.read()
                        if ok:
                            rr.log(f"live/{name}", rr.Image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).compress(jpeg_quality=75))
                    time.sleep(1 / FPS)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                log.exception("live view failed")
                time.sleep(2)
            finally:
                for cap in caps.values():
                    cap.release()
                self.holding = False
