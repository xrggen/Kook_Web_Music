from __future__ import annotations

import os
import time
from typing import Any

from flask import jsonify, request

from shared.relay_protocol import HTTP_ROUTE_ACTIONS, action_spec

from .relay import EdgeCommandTimeout, EdgeOfflineError, RelayHub


class RuntimeProxy:
    def __init__(self, hub: RelayHub, auth_module):
        self.hub = hub
        self.auth = auth_module
        self.default_agent_id = os.environ.get("EDGE_AGENT_ID", "edge-main").strip() or "edge-main"
        self.cache_max_age = max(2.0, float(os.environ.get("CLOUD_STATE_CACHE_MAX_AGE", "20")))

    def _agent_for_request(self) -> str:
        guild_id = request.args.get("guild_id")
        if request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, dict):
                guild_id = body.get("guild_id") or guild_id
        if guild_id:
            mapped = self.hub.agent_for_guild(str(guild_id))
            if mapped:
                return mapped
        return self.default_agent_id

    @staticmethod
    def _query_payload() -> dict[str, str | list[str]]:
        result: dict[str, str | list[str]] = {}
        for key in request.args:
            values = request.args.getlist(key)
            result[key] = values if len(values) > 1 else values[0]
        return result

    @staticmethod
    def _json_payload() -> dict[str, Any]:
        if request.method in {"GET", "HEAD"}:
            return {}
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}

    def _cache_response(self, agent_id: str, action: str):
        state = self.hub.state_snapshot(agent_id)
        if not state:
            return None
        age = time.time() - float(state.get("last_event_at") or 0.0)
        if age > self.cache_max_age and self.hub.is_connected(agent_id):
            return None
        full = state.get("full") or {}
        runtime = state.get("runtime") or {}

        if action == "guild.list":
            guilds = full.get("guilds")
            if isinstance(guilds, list):
                return {"success": True, "guilds": guilds, "edge_stale": not self.hub.is_connected(agent_id)}
        if action == "channel.list":
            guild_id = str(request.args.get("guild_id", ""))
            channels = (full.get("channels") or {}).get(guild_id)
            if isinstance(channels, list):
                return {"success": True, "channels": channels, "edge_stale": not self.hub.is_connected(agent_id)}
        if action == "channel.active":
            guild_id = str(request.args.get("guild_id", ""))
            active = (runtime.get("active") or {}).get(guild_id)
            if isinstance(active, dict):
                return {"success": True, "active": active, "edge_stale": not self.hub.is_connected(agent_id)}
        if action == "playlist.current":
            channel_id = str(request.args.get("channel_id", ""))
            playlist = (runtime.get("playlists") or {}).get(channel_id)
            if isinstance(playlist, dict):
                response = dict(playlist)
                response.setdefault("success", True)
                response["edge_stale"] = not self.hub.is_connected(agent_id)
                return response
        return None

    def _sync_topology(self, action: str, body: dict[str, Any]) -> None:
        if action == "guild.list":
            guilds = body.get("guilds")
            if isinstance(guilds, list):
                for guild in guilds:
                    if not isinstance(guild, dict):
                        continue
                    guild_id = str(guild.get("id", "")).strip()
                    if guild_id:
                        self.auth.sync_guild(guild_id, str(guild.get("name", "")))
        elif action == "channel.list":
            guild_id = str(request.args.get("guild_id", "")).strip()
            channels = body.get("channels")
            if guild_id and isinstance(channels, list):
                for channel in channels:
                    if not isinstance(channel, dict):
                        continue
                    channel_id = str(channel.get("id", "")).strip()
                    if channel_id:
                        self.auth.sync_channel(guild_id, channel_id, str(channel.get("name", "")), "voice")

    def invoke(self, action: str):
        agent_id = self._agent_for_request()
        spec = action_spec(action)
        if spec.method == "GET":
            cached = self._cache_response(agent_id, action)
            if cached is not None:
                self._sync_topology(action, cached)
                return jsonify(cached), 200

        if not self.hub.is_connected(agent_id):
            return jsonify({"success": False, "error": "后端执行节点离线", "code": "EDGE_OFFLINE", "agent_id": agent_id}), 503

        payload = {"query": self._query_payload(), "json": self._json_payload()}
        try:
            result = self.hub.call(agent_id, action, payload, timeout=spec.timeout)
        except EdgeOfflineError:
            return jsonify({"success": False, "error": "后端执行节点离线", "code": "EDGE_OFFLINE"}), 503
        except EdgeCommandTimeout:
            return jsonify({"success": False, "error": "后端执行节点响应超时", "code": "EDGE_TIMEOUT"}), 504

        if not result.get("ok"):
            error = result.get("error") or {}
            return jsonify({"success": False, "error": str(error.get("message") or "后端执行失败"), "code": str(error.get("code") or "EDGE_ERROR")}), 502

        edge_payload = result.get("payload") or {}
        status = int(edge_payload.get("status") or 502)
        body = edge_payload.get("json")
        if not isinstance(body, dict):
            body = {"success": False, "error": "后端返回无效响应"}
            status = 502
        self._sync_topology(action, body)
        return jsonify(body), status


def register_runtime_proxy_routes(app, proxy: RuntimeProxy) -> None:
    for (method, path), action in HTTP_ROUTE_ACTIONS.items():
        endpoint = "edge_proxy_" + action.replace(".", "_")

        def handler(_action=action):
            return proxy.invoke(_action)

        app.add_url_rule(path, endpoint, handler, methods=[method])

    @app.get("/api/edge/status")
    def edge_status():
        return jsonify({"success": True, "agents": proxy.hub.status()})

    @app.get("/api/edge/state")
    def edge_state():
        return jsonify({"success": True, "agents": proxy.hub.all_state()})
