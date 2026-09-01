from __future__ import annotations

import importlib
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

from shared.relay_protocol import action_spec, validate_rpc_payload


class LocalControlError(RuntimeError):
    pass


class LocalControlClient:
    """Trusted loopback client for the existing Edge Flask runtime."""

    SERVICE_USER = "edge_local_admin"

    def __init__(self, platform_dir: Path, port: int):
        self.platform_dir = Path(platform_dir).resolve()
        self.port = int(port)
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._session = requests.Session()
        self._session_lock = threading.RLock()
        self._issued_at = 0.0
        platform_text = str(self.platform_dir)
        if platform_text not in sys.path:
            sys.path.insert(0, platform_text)
        self.auth = importlib.import_module("auth")

    def _provision_service_session(self) -> None:
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self.auth._connect() as db:
            row = db.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE",
                (self.SERVICE_USER,),
            ).fetchone()
            if row is None:
                cursor = db.execute(
                    """
                    INSERT INTO users(
                        username,password_hash,role,enabled,must_change_password,
                        auth_version,created_at,updated_at,last_login_at
                    ) VALUES(?,?, 'admin',1,0,1,?,?,?)
                    """,
                    (
                        self.SERVICE_USER,
                        self.auth.hash_password(secrets.token_urlsafe(36) + "!Aa1"),
                        now,
                        now,
                        now,
                    ),
                )
                user_id = int(cursor.lastrowid)
                auth_version = 1
            else:
                user_id = int(row["id"])
                auth_version = int(row["auth_version"]) + 1
                db.execute(
                    """
                    UPDATE users
                    SET role='admin',enabled=1,must_change_password=0,
                        auth_version=?,updated_at=?
                    WHERE id=?
                    """,
                    (auth_version, now, user_id),
                )
            db.execute(
                "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
            db.execute(
                """
                INSERT INTO sessions(
                    user_id,token_hash,csrf_hash,auth_version,created_at,last_seen_at,
                    idle_expires_at,absolute_expires_at,revoked_at,ip_address,user_agent
                ) VALUES(?,?,?,?,?,?,?,?,NULL,?,?)
                """,
                (
                    user_id,
                    self.auth._token_hash(token),
                    self.auth._token_hash(csrf),
                    auth_version,
                    now,
                    now,
                    now + 86400,
                    now + 86400,
                    "127.0.0.1",
                    "kook-edge-agent/1",
                ),
            )

        self._session.cookies.clear()
        self._session.cookies.set(self.auth.SESSION_COOKIE, token, path="/")
        self._session.cookies.set(self.auth.CSRF_COOKIE, csrf, path="/")
        self._session.headers.update(
            {
                "User-Agent": "kook-edge-agent/1",
                "X-CSRF-Token": csrf,
                "Accept": "application/json",
            }
        )
        self._issued_at = time.monotonic()

    def ensure_session(self) -> None:
        with self._session_lock:
            if self._issued_at == 0.0 or time.monotonic() - self._issued_at >= 12 * 3600:
                self._provision_service_session()

    def ready(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/healthz", timeout=(1.0, 2.0))
            return response.status_code == 200
        except requests.RequestException:
            return False

    def wait_until_ready(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ready():
                self.ensure_session()
                return
            time.sleep(0.5)
        raise LocalControlError("edge local runtime did not become ready")

    @staticmethod
    def _decode_response(response: requests.Response) -> Any:
        if len(response.content) > 4 * 1024 * 1024:
            raise LocalControlError("edge local response is too large")
        try:
            return response.json()
        except ValueError as exc:
            raise LocalControlError(
                f"edge local runtime returned non-json response ({response.status_code})"
            ) from exc

    def invoke(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = action_spec(action)
        cleaned = validate_rpc_payload(payload)
        self.ensure_session()

        def request_once() -> requests.Response:
            kwargs: dict[str, Any] = {
                "params": cleaned["query"],
                "timeout": (3.0, max(5.0, float(spec.timeout))),
                "allow_redirects": False,
            }
            if spec.method not in {"GET", "HEAD"}:
                kwargs["json"] = cleaned["json"]
            return self._session.request(spec.method, f"{self.base_url}{spec.path}", **kwargs)

        with self._session_lock:
            try:
                response = request_once()
                if response.status_code in {401, 403, 428}:
                    self._provision_service_session()
                    response = request_once()
            except requests.RequestException as exc:
                raise LocalControlError(f"edge local request failed: {action}") from exc

        return {"status": int(response.status_code), "json": self._decode_response(response)}
