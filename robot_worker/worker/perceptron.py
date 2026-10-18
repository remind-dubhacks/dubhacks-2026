"""Minimal client for the Perceptron Robotics participant API. See docs/PERCEPTRON_API.md.

The team API key is used only for control-plane calls (contract, session grant). Inference calls
use the short-lived session tokens from the grant and never see the team key."""

import json
import time
from dataclasses import dataclass

import httpx

BASE_URL = "https://robotics.perceptron.inc"


@dataclass
class Grant:
    endpoint_url: str
    application_session_token: str
    modal_session_token: str
    session_id: str
    expires_at: float

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.application_session_token}",
            "Modal-Authorization": f"Bearer {self.modal_session_token}",
        }


class PerceptronClient:
    def __init__(self, team_api_key: str, deployment_id: str, base_url: str = BASE_URL) -> None:
        self.deployment_id = deployment_id
        self.control = httpx.Client(
            base_url=base_url, headers={"Authorization": f"Bearer {team_api_key}"}, timeout=30
        )
        self.contract: dict | None = None

    # ----- control plane (team key) -----

    def deployment(self) -> dict:
        return self._json(self.control.get(f"/v1/deployments/{self.deployment_id}"))

    def fetch_contract(self) -> dict:
        self.contract = self._json(self.control.get(f"/v1/deployments/{self.deployment_id}/contract"))
        return self.contract

    def grant(self, session_id: str, ttl_seconds: int = 3600) -> Grant:
        data = self._json(
            self.control.post(
                f"/v1/deployments/{self.deployment_id}/sessions",
                json={"session_id": session_id, "ttl_seconds": ttl_seconds},
            )
        )
        return Grant(
            endpoint_url=data["endpoint_url"].rstrip("/"),
            application_session_token=data["application_session_token"],
            modal_session_token=data["modal_session_token"],
            session_id=data["session_id"],
            expires_at=time.time() + ttl_seconds,
        )

    # ----- inference (session tokens) -----

    def create_session(self, grant: Grant, instruction: str, contract_id: str, rtc_enabled: bool = False) -> dict:
        return self._json(
            httpx.post(
                f"{grant.endpoint_url}/deployments/{self.deployment_id}/sessions",
                headers=grant.headers(),
                json={"instruction": instruction, "rtc_enabled": rtc_enabled, "contract_id": contract_id},
                timeout=60,
            )
        )

    def predict(self, grant: Grant, metadata: dict, side_png: bytes, wrist_png: bytes) -> dict:
        return self._json(
            httpx.post(
                f"{grant.endpoint_url}/sessions/{grant.session_id}/predict",
                headers=grant.headers(),
                data={"metadata": json.dumps(metadata)},
                files={"side": ("side.png", side_png, "image/png"), "wrist": ("wrist.png", wrist_png, "image/png")},
                timeout=30,
            )
        )

    def reset(self, grant: Grant) -> None:
        httpx.post(f"{grant.endpoint_url}/sessions/{grant.session_id}/reset", headers=grant.headers(), timeout=15)

    def delete_session(self, grant: Grant) -> None:
        httpx.delete(f"{grant.endpoint_url}/sessions/{grant.session_id}", headers=grant.headers(), timeout=15)

    @staticmethod
    def _json(r: httpx.Response) -> dict:
        r.raise_for_status()
        return r.json()
