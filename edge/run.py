#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EDGE_DIR = Path(__file__).resolve().parent


def _platform_dir() -> Path:
    configured = os.environ.get("EDGE_PLATFORM_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        return path.resolve()
    return (ROOT / ("windows" if sys.platform == "win32" else "Ubuntu")).resolve()


def _load_configuration(platform_dir: Path) -> None:
    load_dotenv(platform_dir / ".env", override=False)
    edge_env = Path(os.environ.get("EDGE_ENV_FILE", EDGE_DIR / ".env")).expanduser()
    if not edge_env.is_absolute():
        edge_env = ROOT / edge_env
    load_dotenv(edge_env, override=False)

    local_port = os.environ.get("EDGE_LOCAL_PORT", "18473").strip() or "18473"
    os.environ["HOST"] = "127.0.0.1"
    os.environ["PORT"] = local_port
    edge_db = os.environ.get("EDGE_LOCAL_AUTH_DATABASE_PATH", "").strip()
    if not edge_db:
        edge_db = str(platform_dir / "data" / "edge_internal.db")
    os.environ["AUTH_DATABASE_PATH"] = str(Path(edge_db).expanduser().resolve())
    os.environ["INITIAL_ADMIN_USERNAME"] = "edge_local_admin"
    os.environ["INITIAL_ADMIN_PASSWORD"] = secrets.token_urlsafe(36) + "!Aa1"
    os.environ["AUTH_COOKIE_SECURE"] = "false"
    os.environ["AUTH_TRUST_PROXY_HEADERS"] = "false"


def main() -> None:
    platform_dir = _platform_dir()
    if not platform_dir.is_dir():
        raise RuntimeError(f"platform directory not found: {platform_dir}")
    _load_configuration(platform_dir)

    platform_text = str(platform_dir)
    if platform_text not in sys.path:
        sys.path.insert(0, platform_text)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    import run as platform_run
    from app import create_app
    from runtime_health import runtime_health
    from edge.agent import EdgeAgent

    os.chdir(platform_dir)
    platform_run._install_shutdown_hooks()
    platform_run.start_music_api()
    platform_run.start_qq_music_api()

    application = create_app()
    runtime_health.mark_supervisor_ready()
    platform_run._start_watchdog_once()

    local_port = int(os.environ["PORT"])
    agent = EdgeAgent(platform_dir, local_port)
    agent.start()

    logging.getLogger(__name__).info(
        "Edge local control API is loopback-only: http://127.0.0.1:%d", local_port
    )
    logging.getLogger(__name__).info(
        "Edge outbound relay target configured (agent_id=%s)",
        os.environ.get("EDGE_AGENT_ID", "edge-main"),
    )
    application.run(host="127.0.0.1", port=local_port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
