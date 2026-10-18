"""Job executors. Both are cancellable via a threading.Event and never retry on their own."""

import os
import random
import threading
import time
import uuid


class RobotError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class Stopped(Exception):
    pass


class MockExecutor:
    """Simulates a pick-and-place so the UI and backend can be built before the arm is ready."""

    mode = "mock"

    def __init__(self) -> None:
        self.duration = float(os.getenv("MOCK_DURATION_S", "4"))
        self.fail_rate = float(os.getenv("MOCK_FAIL_RATE", "0"))

    def ready(self) -> bool:
        return True

    def execute(self, instruction: str, stop: threading.Event) -> None:
        end = time.monotonic() + self.duration
        while time.monotonic() < end:
            if stop.wait(0.1):
                raise Stopped()
        if random.random() < self.fail_rate:
            raise RobotError("grasp_failed", "simulated grasp failure")


class PerceptronExecutor:
    """Runs the Perceptron-hosted policy on the real SO-101 for one episode."""

    mode = "perceptron"

    def __init__(self) -> None:
        from .perceptron import PerceptronClient
        from .robot import SO101

        self.client = PerceptronClient(os.environ["PERCEPTRON_API_KEY"], os.environ["PERCEPTRON_DEPLOYMENT_ID"])
        contract = self.client.fetch_contract()
        self.contract_id = contract.get("contract_id") or contract["id"]
        self.fps = float(os.getenv("CONTROL_FPS", "30"))
        self.max_seconds = float(os.getenv("MAX_EPISODE_SECONDS", "25"))
        self.robot = SO101()

    def ready(self) -> bool:
        return self.client.deployment().get("status") == "ready"

    def execute(self, instruction: str, stop: threading.Event) -> None:
        grant = self.client.grant(f"remind-{uuid.uuid4().hex[:12]}", ttl_seconds=600)
        try:
            self.client.create_session(grant, instruction, self.contract_id)
            t0 = time.monotonic()
            seq = 0
            while time.monotonic() - t0 < self.max_seconds:
                if stop.is_set():
                    raise Stopped()
                state, side, wrist = self.robot.observe()
                result = self.client.predict(
                    grant,
                    {
                        "contract_id": self.contract_id,
                        "observation_id": f"obs-{seq:05d}",
                        "sequence": seq,
                        "timestamp_seconds": time.monotonic() - t0,
                        "state": state,
                        "image_encoding": "png",
                    },
                    side,
                    wrist,
                )
                seq += 1
                # TODO: confirm the action-chunk field name and execution timing in the contract.
                chunk = result.get("actions") or result.get("action_chunk") or []
                if not chunk:
                    raise RobotError("empty_action_chunk", str(result)[:200])
                for action in chunk:
                    if stop.is_set():
                        raise Stopped()
                    self.robot.act(action)
                    time.sleep(1 / self.fps)
            # The policy ran its full episode budget. Whether the box is actually in the tray is
            # confirmed by a caregiver (REQUIRE_VERIFICATION), never assumed here.
        except Stopped:
            raise
        except RobotError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RobotError("policy_error", str(e)) from e
        finally:
            try:
                self.client.delete_session(grant)
            except Exception:  # noqa: BLE001
                pass
