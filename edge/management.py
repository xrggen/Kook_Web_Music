from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from .agent import EdgeAgentSupervisor
from .config_store import EdgeConfigStore
from .secret_store import EdgeSecretStore

LOGGER = logging.getLogger(__name__)


def register_edge_management(app, supervisor: EdgeAgentSupervisor, config_store: EdgeConfigStore, secret_store: EdgeSecretStore, edge_dir: Path) -> None:
    bp = Blueprint("edge_management", __name__)

    @bp.get("/api/admin/edge/config")
    def get_config():
        cfg = config_store.get()
        return jsonify({"success": True, "config": cfg.public_dict(), "token_configured": secret_store.configured()})

    @bp.patch("/api/admin/edge/config")
    def update_config():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"success": False, "error": "请求体必须是 JSON 对象"}), 400
        try:
            cfg = config_store.update(payload)
        except (TypeError, ValueError) as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        supervisor.reload()
        return jsonify({"success": True, "config": cfg.public_dict(), "reconnecting": True})

    @bp.post("/api/admin/edge/token")
    def update_token():
        payload = request.get_json(silent=True)
        token = str((payload or {}).get("token", "")).strip() if isinstance(payload, dict) else ""
        try:
            secret_store.write(token)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        supervisor.reload()
        return jsonify({"success": True, "token_configured": True, "reconnecting": True})

    @bp.post("/api/admin/edge/reconnect")
    def reconnect():
        supervisor.reload()
        return jsonify({"success": True, "reconnecting": True})

    @bp.post("/api/admin/edge/test-ports")
    def test_ports():
        try:
            results = supervisor.test_ports()
        except Exception as exc:
            LOGGER.warning("Edge WSS port-pool test failed: %s", type(exc).__name__)
            return jsonify({"success": False, "error": type(exc).__name__}), 502
        return jsonify({"success": True, "ports": results})

    @bp.get("/api/admin/edge/status")
    def status():
        return jsonify({"success": True, "edge": supervisor.status()})

    @bp.get("/edge-static/<path:filename>")
    def edge_static(filename: str):
        return send_from_directory(str(Path(edge_dir) / "static"), filename, max_age=300)

    app.register_blueprint(bp)
