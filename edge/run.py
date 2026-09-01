#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import ChoiceLoader, FileSystemLoader

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
    load_dotenv(edge_env, override=True)

    os.environ.setdefault("EDGE_LOCAL_WEB_HOST", "127.0.0.1")
    os.environ.setdefault("EDGE_LOCAL_PORT", os.environ.get("PORT", "18473"))
    os.environ["HOST"] = os.environ["EDGE_LOCAL_WEB_HOST"]
    os.environ["PORT"] = os.environ["EDGE_LOCAL_PORT"]
    os.environ.setdefault("AUTH_COOKIE_SECURE", "false")
    os.environ.setdefault("AUTH_TRUST_PROXY_HEADERS", "false")


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
    from edge.agent import EdgeAgentSupervisor
    from edge.config_store import EdgeConfigStore
    from edge.management import register_edge_management
    from edge.secret_store import EdgeSecretStore

    os.chdir(platform_dir)
    platform_run._install_shutdown_hooks()
    platform_run.start_music_api()
    platform_run.start_qq_music_api()

    application = create_app()
    application.jinja_loader = ChoiceLoader([
        FileSystemLoader(str(EDGE_DIR / "templates")),
        application.jinja_loader,
    ])
    application.jinja_env.globals["deployment_role"] = "edge"

    runtime_health.mark_supervisor_ready()
    platform_run._start_watchdog_once()

    local_port = int(os.environ["PORT"])
    config_store = EdgeConfigStore(platform_dir)
    secret_store = EdgeSecretStore(platform_dir)
    supervisor = EdgeAgentSupervisor(platform_dir, local_port, config_store, secret_store)
    register_edge_management(application, supervisor, config_store, secret_store, EDGE_DIR)
    application.extensions["edge_agent_supervisor"] = supervisor
    application.extensions["edge_config_store"] = config_store
    supervisor.start()

    host = os.environ.get("EDGE_LOCAL_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    logging.getLogger(__name__).info("Edge Local WebUI listening on http://%s:%d", host, local_port)
    logging.getLogger(__name__).info("Edge remote supervisor started; local WebUI/Bot/playback remain independent from Cloud")
    application.run(host=host, port=local_port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
