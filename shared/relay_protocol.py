from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
DEFAULT_COMMAND_TIMEOUT = 15.0


@dataclass(frozen=True)
class ActionSpec:
    method: str
    path: str
    timeout: float = DEFAULT_COMMAND_TIMEOUT
    cache_kind: str | None = None


ACTIONS: dict[str, ActionSpec] = {
    "guild.list": ActionSpec("GET", "/api/guilds", 15.0, "guilds"),
    "channel.list": ActionSpec("GET", "/api/channels", 15.0, "channels"),
    "channel.active": ActionSpec("GET", "/api/channels/active", 8.0, "active"),
    "playback.join": ActionSpec("POST", "/api/join", 12.0),
    "playback.leave": ActionSpec("POST", "/api/leave", 12.0),
    "music.search": ActionSpec("GET", "/api/search", 25.0),
    "playback.play": ActionSpec("POST", "/api/play", 30.0),
    "playlist.add": ActionSpec("POST", "/api/playlist/add", 30.0),
    "playlist.import": ActionSpec("POST", "/api/playlist", 90.0),
    "playlist.current": ActionSpec("GET", "/api/playlist/current", 8.0, "playlist"),
    "playlist.repeat": ActionSpec("POST", "/api/playlist/repeat", 10.0),
    "playlist.promote": ActionSpec("POST", "/api/playlist/promote", 10.0),
    "playlist.remove": ActionSpec("POST", "/api/remove", 10.0),
    "playlist.clear": ActionSpec("POST", "/api/clear", 10.0),
    "playback.pause": ActionSpec("POST", "/api/pause", 10.0),
    "playback.resume": ActionSpec("POST", "/api/resume", 10.0),
    "playback.skip": ActionSpec("POST", "/api/skip", 10.0),
    "playback.stop": ActionSpec("POST", "/api/stop", 10.0),
    "playback.seek": ActionSpec("POST", "/api/seek", 10.0),
    "netease.account.status": ActionSpec("GET", "/api/account/status", 15.0),
    "netease.account.detail": ActionSpec("GET", "/api/account/detail", 15.0),
    "netease.account.level": ActionSpec("GET", "/api/account/level", 15.0),
    "netease.account.subcount": ActionSpec("GET", "/api/account/subcount", 15.0),
    "netease.account.playlists": ActionSpec("GET", "/api/account/playlists", 25.0),
    "netease.account.qr_key": ActionSpec("POST", "/api/account/qr/key", 20.0),
    "netease.account.qr_create": ActionSpec("POST", "/api/account/qr/create", 20.0),
    "netease.account.qr_check": ActionSpec("POST", "/api/account/qr/check", 20.0),
    "netease.account.captcha_send": ActionSpec("POST", "/api/account/cellphone/captcha", 20.0),
    "netease.account.captcha_verify": ActionSpec("POST", "/api/account/cellphone/verify", 20.0),
    "netease.account.cellphone_login": ActionSpec("POST", "/api/account/cellphone/login", 30.0),
    "netease.account.signin": ActionSpec("POST", "/api/account/signin", 20.0),
    "netease.account.cookie": ActionSpec("POST", "/api/account/cookie", 15.0),
    "netease.account.logout": ActionSpec("POST", "/api/account/logout", 20.0),
    "qq.account.status": ActionSpec("GET", "/api/qq/account/status", 15.0),
    "qq.account.profile": ActionSpec("GET", "/api/qq/account/profile", 15.0),
    "qq.account.playlists": ActionSpec("GET", "/api/qq/account/playlists", 25.0),
    "qq.account.qr_create": ActionSpec("POST", "/api/qq/account/qr/create", 20.0),
    "qq.account.qr_check": ActionSpec("POST", "/api/qq/account/qr/check", 20.0),
    "qq.account.cookie": ActionSpec("POST", "/api/qq/account/cookie", 15.0),
    "qq.account.refresh": ActionSpec("POST", "/api/qq/account/refresh", 30.0),
    "qq.account.logout": ActionSpec("POST", "/api/qq/account/logout", 20.0),
    "bili.account.status": ActionSpec("GET", "/api/bili/account/status", 15.0),
    "bili.account.profile": ActionSpec("GET", "/api/bili/account/profile", 15.0),
    "bili.account.playlists": ActionSpec("GET", "/api/bili/account/playlists", 25.0),
    "bili.account.qr_create": ActionSpec("POST", "/api/bili/account/qr/create", 20.0),
    "bili.account.qr_check": ActionSpec("POST", "/api/bili/account/qr/check", 20.0),
    "bili.account.cookie": ActionSpec("POST", "/api/bili/account/cookie", 15.0),
    "bili.account.logout": ActionSpec("POST", "/api/bili/account/logout", 20.0),
    "runtime.stats": ActionSpec("GET", "/api/stats", 10.0),
    "runtime.system_status": ActionSpec("GET", "/api/system/status", 10.0),
    "runtime.debug": ActionSpec("GET", "/api/debug", 10.0),
    "runtime.logs": ActionSpec("GET", "/api/logs", 15.0),
    "runtime.logs_clear": ActionSpec("POST", "/api/logs/clear", 10.0),
    "runtime.cleanup": ActionSpec("POST", "/api/system/cleanup", 20.0),
    "runtime.cleanup_config": ActionSpec("POST", "/api/system/cleanup/config", 10.0),
    "runtime.terminal_output": ActionSpec("GET", "/api/terminal/output", 15.0),
    "runtime.cache_test": ActionSpec("POST", "/api/cache/test", 15.0),
}

HTTP_ROUTE_ACTIONS: dict[tuple[str, str], str] = {
    (spec.method, spec.path): action for action, spec in ACTIONS.items()
}

WRITE_ACTIONS = frozenset(
    action for action, spec in ACTIONS.items() if spec.method in {"POST", "PUT", "PATCH", "DELETE"}
)
PLAYBACK_WRITE_ACTIONS = frozenset(
    action for action in WRITE_ACTIONS if action.startswith(("playback.", "playlist."))
)
TOPOLOGY_ACTIONS = frozenset({"guild.list", "channel.list", "channel.active"})
CACHEABLE_ACTIONS = frozenset(
    action for action, spec in ACTIONS.items() if spec.cache_kind is not None
)


class ProtocolError(ValueError):
    pass


def new_envelope(message_type: str, **fields: Any) -> dict[str, Any]:
    message = {"v": PROTOCOL_VERSION, "type": message_type, "ts": time.time()}
    message.update(fields)
    return message


def encode_message(message: dict[str, Any]) -> str:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("relay message exceeds maximum size")
    return raw


def decode_message(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ProtocolError("relay message exceeds maximum size")
        raw = raw.decode("utf-8")
    elif len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("relay message exceeds maximum size")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("invalid relay json") from exc
    if not isinstance(value, dict):
        raise ProtocolError("relay envelope must be an object")
    if value.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    message_type = value.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise ProtocolError("missing relay message type")
    return value


def action_spec(action: str) -> ActionSpec:
    try:
        return ACTIONS[action]
    except KeyError as exc:
        raise ProtocolError("unsupported action") from exc


def validate_rpc_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"query": {}, "json": {}}
    if not isinstance(payload, dict):
        raise ProtocolError("command payload must be an object")
    query = payload.get("query") or {}
    body = payload.get("json") or {}
    if not isinstance(query, dict) or not isinstance(body, dict):
        raise ProtocolError("query/json must be objects")
    if len(query) > 32 or len(body) > 128:
        raise ProtocolError("command payload has too many fields")

    clean_query: dict[str, str | list[str]] = {}
    for key, value in query.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise ProtocolError("invalid query key")
        if isinstance(value, list):
            if len(value) > 16 or not all(isinstance(item, str) and len(item) <= 4096 for item in value):
                raise ProtocolError("invalid query value")
            clean_query[key] = value
        elif isinstance(value, str) and len(value) <= 4096:
            clean_query[key] = value
        else:
            raise ProtocolError("invalid query value")

    clean = {"query": clean_query, "json": body}
    encode_message(new_envelope("payload_check", payload=clean))
    return clean
