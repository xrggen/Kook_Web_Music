from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "windows"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

import auth as control_auth

from .relay import RelayHub
from .runtime_proxy import RuntimeProxy, register_runtime_proxy_routes


def create_app(hub: RelayHub) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(WINDOWS_DIR / "templates"),
        static_folder=str(WINDOWS_DIR / "static"),
        static_url_path="/static",
    )
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "").strip() or os.urandom(32)
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_REQUEST_BYTES", 1024 * 1024))
    app.extensions["edge_relay_hub"] = hub

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/library")
    def library():
        return render_template("library.html")

    @app.get("/account")
    def account():
        return render_template("account.html")

    @app.get("/status")
    def status():
        return render_template("status.html")

    @app.get("/settings")
    def settings():
        return render_template("settings.html")

    @app.get("/monitor")
    def monitor():
        return render_template("status.html")

    @app.get("/healthz")
    def healthz():
        agents = hub.status()
        connected = any(bool(item.get("connected")) for item in agents)
        return jsonify({"status": "ok", "role": "cloud", "edge_connected": connected, "agents": len(agents)})

    proxy = RuntimeProxy(hub, control_auth)
    register_runtime_proxy_routes(app, proxy)
    control_auth.register_auth(app)
    return app
