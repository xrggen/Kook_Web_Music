from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PORT_START = 28470
DEFAULT_PORT_END = 28479
DEFAULT_PATH = "/edge/v1/connect"


def _bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EdgeRelayConfig:
    enabled: bool
    host: str
    port_start: int
    port_end: int
    path: str
    tls_verify: bool
    agent_id: str
    agent_name: str
    preferred_port: int | None = None

    def ports(self) -> list[int]:
        ports = list(range(self.port_start, self.port_end + 1))
        if self.preferred_port in ports:
            ports.remove(self.preferred_port)
            ports.insert(0, self.preferred_port)
        return ports

    def url_for(self, port: int) -> str:
        return f"wss://{self.host}:{int(port)}{self.path}"

    def public_dict(self) -> dict:
        data = asdict(self)
        data["ports"] = list(range(self.port_start, self.port_end + 1))
        return data


class EdgeConfigStore:
    """Persistent Edge relay configuration, independent from the Web auth database."""

    def __init__(self, platform_dir: Path):
        self.platform_dir = Path(platform_dir).resolve()
        self.data_dir = self.platform_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        configured = os.environ.get("EDGE_CONFIG_DATABASE_PATH", "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = self.platform_dir / path
            self.path = path.resolve()
        else:
            self.path = (self.data_dir / "edge_config.db").resolve()
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def _init(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS edge_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    host TEXT NOT NULL,
                    port_start INTEGER NOT NULL,
                    port_end INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    tls_verify INTEGER NOT NULL DEFAULT 1 CHECK(tls_verify IN (0,1)),
                    agent_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    preferred_port INTEGER,
                    updated_at INTEGER NOT NULL
                );
            """)
            row = db.execute("SELECT 1 FROM edge_settings WHERE id=1").fetchone()
            if row is None:
                cfg = self._bootstrap_from_env()
                db.execute(
                    """INSERT INTO edge_settings(
                        id,enabled,host,port_start,port_end,path,tls_verify,
                        agent_id,agent_name,preferred_port,updated_at
                    ) VALUES(1,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        1 if cfg.enabled else 0, cfg.host, cfg.port_start, cfg.port_end,
                        cfg.path, 1 if cfg.tls_verify else 0, cfg.agent_id,
                        cfg.agent_name, cfg.preferred_port, int(time.time())
                    ),
                )

    def _bootstrap_from_env(self) -> EdgeRelayConfig:
        host = os.environ.get("EDGE_RELAY_HOST", "").strip()
        start = os.environ.get("EDGE_RELAY_PORT_START", "").strip()
        end = os.environ.get("EDGE_RELAY_PORT_END", "").strip()
        path = os.environ.get("EDGE_RELAY_PATH", DEFAULT_PATH).strip() or DEFAULT_PATH

        legacy = os.environ.get("EDGE_RELAY_URL", "").strip()
        if legacy and not host:
            parsed = urlsplit(legacy)
            if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
                raise ValueError("EDGE_RELAY_URL must be an absolute ws:// or wss:// URL")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("EDGE_RELAY_URL must not contain credentials, query or fragment")
            host = parsed.hostname
            legacy_port = parsed.port or (443 if parsed.scheme == "wss" else 80)
            start = end = str(legacy_port)
            path = parsed.path or DEFAULT_PATH

        host = host or "music.example.com"
        port_start = int(start or DEFAULT_PORT_START)
        port_end = int(end or DEFAULT_PORT_END)
        return self._validated(
            enabled=_bool(os.environ.get("EDGE_RELAY_ENABLED", "true"), True),
            host=host,
            port_start=port_start,
            port_end=port_end,
            path=path,
            tls_verify=_bool(os.environ.get("EDGE_RELAY_TLS_VERIFY", "true"), True),
            agent_id=os.environ.get("EDGE_AGENT_ID", "edge-main").strip() or "edge-main",
            agent_name=os.environ.get("EDGE_AGENT_NAME", "Primary Edge").strip() or "Primary Edge",
            preferred_port=None,
        )

    @staticmethod
    def _validated(**values) -> EdgeRelayConfig:
        host = str(values["host"]).strip().rstrip(".")
        if not host or len(host) > 253 or any(ch in host for ch in "/?#@"):
            raise ValueError("Cloud 主机名无效")
        start, end = int(values["port_start"]), int(values["port_end"])
        if not (1024 <= start <= 65535 and 1024 <= end <= 65535 and start <= end):
            raise ValueError("WSS 端口范围必须位于 1024-65535")
        if end - start + 1 > 32:
            raise ValueError("单个端口池最多允许 32 个端口")
        path = str(values["path"]).strip() or DEFAULT_PATH
        if not path.startswith("/") or "?" in path or "#" in path or len(path) > 128:
            raise ValueError("WSS 路径无效")
        agent_id = str(values["agent_id"]).strip()
        agent_name = str(values["agent_name"]).strip()
        if not agent_id or len(agent_id) > 128 or any(ch.isspace() for ch in agent_id):
            raise ValueError("Agent ID 无效")
        if not agent_name or len(agent_name) > 128:
            raise ValueError("Agent 名称无效")
        preferred = values.get("preferred_port")
        preferred = int(preferred) if preferred not in (None, "") else None
        if preferred is not None and not (start <= preferred <= end):
            preferred = None
        return EdgeRelayConfig(
            enabled=bool(values["enabled"]),
            host=host, port_start=start, port_end=end, path=path,
            tls_verify=bool(values["tls_verify"]),
            agent_id=agent_id, agent_name=agent_name,
            preferred_port=preferred,
        )

    def get(self) -> EdgeRelayConfig:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM edge_settings WHERE id=1").fetchone()
        return self._validated(
            enabled=bool(row["enabled"]), host=row["host"],
            port_start=row["port_start"], port_end=row["port_end"], path=row["path"],
            tls_verify=bool(row["tls_verify"]), agent_id=row["agent_id"],
            agent_name=row["agent_name"], preferred_port=row["preferred_port"],
        )

    def update(self, payload: dict) -> EdgeRelayConfig:
        current = self.get()
        values = {
            "enabled": payload.get("enabled", current.enabled),
            "host": payload.get("host", current.host),
            "port_start": payload.get("port_start", current.port_start),
            "port_end": payload.get("port_end", current.port_end),
            "path": payload.get("path", current.path),
            "tls_verify": payload.get("tls_verify", current.tls_verify),
            "agent_id": payload.get("agent_id", current.agent_id),
            "agent_name": payload.get("agent_name", current.agent_name),
            "preferred_port": current.preferred_port,
        }
        cfg = self._validated(**values)
        with self._lock, self._connect() as db:
            db.execute(
                """UPDATE edge_settings SET enabled=?,host=?,port_start=?,port_end=?,
                   path=?,tls_verify=?,agent_id=?,agent_name=?,preferred_port=?,updated_at=?
                   WHERE id=1""",
                (
                    1 if cfg.enabled else 0, cfg.host, cfg.port_start, cfg.port_end,
                    cfg.path, 1 if cfg.tls_verify else 0, cfg.agent_id, cfg.agent_name,
                    cfg.preferred_port, int(time.time())
                ),
            )
        return cfg

    def set_preferred_port(self, port: int | None) -> None:
        cfg = self.get()
        value = int(port) if port is not None and cfg.port_start <= int(port) <= cfg.port_end else None
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE edge_settings SET preferred_port=?,updated_at=? WHERE id=1",
                (value, int(time.time())),
            )
