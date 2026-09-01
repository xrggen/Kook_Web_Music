from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable

_LOCK = threading.RLock()


def _db_path() -> Path:
    configured = os.environ.get("AUTH_DATABASE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent / "data" / "kook_music.db").resolve()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_registry() -> None:
    with _LOCK, _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS edge_agents (
                agent_id TEXT PRIMARY KEY,
                display_name TEXT,
                token_hash TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                version TEXT,
                protocol_version INTEGER,
                connected INTEGER NOT NULL DEFAULT 0 CHECK(connected IN (0,1)),
                last_seen_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS edge_agent_guilds (
                kook_guild_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL REFERENCES edge_agents(agent_id) ON DELETE CASCADE,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_edge_agent_guilds_agent
                ON edge_agent_guilds(agent_id);
            """
        )
    bootstrap_from_environment()


def _configured_agents() -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    raw = os.environ.get("EDGE_AGENTS_JSON", "").strip()
    if raw:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError("EDGE_AGENTS_JSON must be an object")
        for agent_id, item in payload.items():
            if isinstance(item, str):
                token, name = item, str(agent_id)
            elif isinstance(item, dict):
                token = str(item.get("token", ""))
                name = str(item.get("name", agent_id))
            else:
                raise RuntimeError("invalid EDGE_AGENTS_JSON entry")
            items.append((str(agent_id), token, name))

    agent_id = os.environ.get("EDGE_AGENT_ID", "edge-main").strip() or "edge-main"
    token = os.environ.get("EDGE_AGENT_TOKEN", "").strip()
    name = os.environ.get("EDGE_AGENT_NAME", agent_id).strip() or agent_id
    if token:
        items.append((agent_id, token, name))

    dedup: dict[str, tuple[str, str, str]] = {}
    for item in items:
        dedup[item[0]] = item
    return list(dedup.values())


def bootstrap_from_environment() -> None:
    configured = _configured_agents()
    if not configured:
        raise RuntimeError(
            "Cloud requires EDGE_AGENT_TOKEN or EDGE_AGENTS_JSON; "
            "plaintext tokens are read from environment only and stored as hashes"
        )
    now = int(time.time())
    with _LOCK, _connect() as db:
        for agent_id, token, display_name in configured:
            if not agent_id or len(agent_id) > 128 or not token or len(token) < 32:
                raise RuntimeError("edge agent id/token configuration is invalid")
            db.execute(
                """
                INSERT INTO edge_agents(
                    agent_id,display_name,token_hash,enabled,connected,created_at,updated_at
                ) VALUES(?,?,?,1,0,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    token_hash=excluded.token_hash,
                    updated_at=excluded.updated_at
                """,
                (agent_id, display_name[:255], _token_hash(token), now, now),
            )


def authenticate(agent_id: str, token: str) -> bool:
    if not agent_id or not token:
        return False
    with _LOCK, _connect() as db:
        row = db.execute(
            "SELECT token_hash,enabled FROM edge_agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
    if not row or not row["enabled"]:
        return False
    return hmac.compare_digest(str(row["token_hash"]), _token_hash(token))


def mark_connected(agent_id: str, *, version: str = "", protocol_version: int | None = None) -> None:
    now = int(time.time())
    with _LOCK, _connect() as db:
        db.execute(
            """
            UPDATE edge_agents
            SET connected=1,last_seen_at=?,version=?,protocol_version=?,updated_at=?
            WHERE agent_id=?
            """,
            (now, version[:128], protocol_version, now, agent_id),
        )


def mark_seen(agent_id: str) -> None:
    now = int(time.time())
    with _LOCK, _connect() as db:
        db.execute(
            "UPDATE edge_agents SET last_seen_at=?,updated_at=? WHERE agent_id=?",
            (now, now, agent_id),
        )


def mark_disconnected(agent_id: str) -> None:
    now = int(time.time())
    with _LOCK, _connect() as db:
        db.execute(
            "UPDATE edge_agents SET connected=0,updated_at=? WHERE agent_id=?",
            (now, agent_id),
        )


def sync_agent_guilds(agent_id: str, guilds: Iterable[dict]) -> None:
    now = int(time.time())
    ids = {
        str(item.get("id", "")).strip()
        for item in guilds
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    with _LOCK, _connect() as db:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            db.execute(
                f"DELETE FROM edge_agent_guilds WHERE agent_id=? AND kook_guild_id NOT IN ({placeholders})",
                (agent_id, *sorted(ids)),
            )
        else:
            db.execute("DELETE FROM edge_agent_guilds WHERE agent_id=?", (agent_id,))
        for guild_id in ids:
            db.execute(
                """
                INSERT INTO edge_agent_guilds(kook_guild_id,agent_id,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(kook_guild_id) DO UPDATE SET
                    agent_id=excluded.agent_id,
                    updated_at=excluded.updated_at
                """,
                (guild_id, agent_id, now),
            )


def agent_for_guild(guild_id: str) -> str | None:
    with _LOCK, _connect() as db:
        row = db.execute(
            """
            SELECT g.agent_id
            FROM edge_agent_guilds g
            JOIN edge_agents a ON a.agent_id=g.agent_id
            WHERE g.kook_guild_id=? AND a.enabled=1
            """,
            (str(guild_id),),
        ).fetchone()
    return str(row[0]) if row else None


def list_agents() -> list[dict]:
    with _LOCK, _connect() as db:
        rows = db.execute(
            """
            SELECT agent_id,display_name,enabled,connected,version,protocol_version,
                   last_seen_at,created_at,updated_at
            FROM edge_agents ORDER BY agent_id
            """
        ).fetchall()
    return [dict(row) for row in rows]
