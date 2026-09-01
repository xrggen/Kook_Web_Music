#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CLOUD_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _cloud_path(value: str, default: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return str(default.resolve())
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = CLOUD_DIR / path
    return str(path.resolve())


def _load_configuration() -> None:
    env_file = Path(os.environ.get("CLOUD_ENV_FILE", CLOUD_DIR / ".env")).expanduser()
    if not env_file.is_absolute():
        env_file = ROOT / env_file
    load_dotenv(env_file, override=False)
    os.environ.setdefault("HOST", "127.0.0.1")
    os.environ.setdefault("PORT", "18473")
    os.environ.setdefault("EDGE_RELAY_HOST", "127.0.0.1")
    os.environ.setdefault("EDGE_RELAY_PORT", "18476")
    os.environ.setdefault("EDGE_PUBLIC_WSS_PORT_START", "28470")
    os.environ.setdefault("EDGE_PUBLIC_WSS_PORT_END", "28479")
    os.environ["AUTH_DATABASE_PATH"] = _cloud_path(os.environ.get("AUTH_DATABASE_PATH", ""), CLOUD_DIR / "data" / "kook_music.db")
    os.environ["INITIAL_ADMIN_CREDENTIAL_PATH"] = _cloud_path(os.environ.get("INITIAL_ADMIN_CREDENTIAL_PATH", ""), CLOUD_DIR / "data" / "bootstrap-admin.json")
    os.environ.setdefault("AUTH_COOKIE_SECURE", "true")
    os.environ.setdefault("AUTH_TRUST_PROXY_HEADERS", "true")
    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))


def main() -> None:
    _load_configuration()
    from cloud.app import create_app
    from cloud.relay import RelayHub

    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    relay_host = os.environ["EDGE_RELAY_HOST"].strip() or "127.0.0.1"
    relay_port = int(os.environ["EDGE_RELAY_PORT"])
    public_start = int(os.environ["EDGE_PUBLIC_WSS_PORT_START"])
    public_end = int(os.environ["EDGE_PUBLIC_WSS_PORT_END"])
    if not (1024 <= public_start <= public_end <= 65535) or public_end - public_start + 1 > 32:
        raise RuntimeError("invalid EDGE_PUBLIC_WSS_PORT_START/END")
    hub = RelayHub(relay_host, relay_port)
    hub.start()
    application = create_app(hub)
    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", "18473"))
    logging.getLogger(__name__).info(
        "Cloud control plane http=%s:%d relay=%s:%d public_wss_pool=%d-%d",
        host, port, relay_host, relay_port, public_start, public_end,
    )
    application.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
