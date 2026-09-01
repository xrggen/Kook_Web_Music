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


def _load_configuration() -> None:
    env_file = Path(os.environ.get("CLOUD_ENV_FILE", CLOUD_DIR / ".env")).expanduser()
    if not env_file.is_absolute():
        env_file = ROOT / env_file
    load_dotenv(env_file, override=False)
    os.environ.setdefault("HOST", "127.0.0.1")
    os.environ.setdefault("PORT", "18473")
    os.environ.setdefault("AUTH_DATABASE_PATH", str((CLOUD_DIR / "data" / "kook_music.db").resolve()))
    os.environ.setdefault("INITIAL_ADMIN_CREDENTIAL_PATH", str((CLOUD_DIR / "data" / "bootstrap-admin.json").resolve()))
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
    relay_host = os.environ.get("EDGE_RELAY_HOST", "127.0.0.1").strip() or "127.0.0.1"
    relay_port = int(os.environ.get("EDGE_RELAY_PORT", "18476"))
    hub = RelayHub(relay_host, relay_port)
    hub.start()
    application = create_app(hub)
    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", "18473"))
    logging.getLogger(__name__).info("Cloud control plane listening on http://%s:%d; relay=%s:%d", host, port, relay_host, relay_port)
    application.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
