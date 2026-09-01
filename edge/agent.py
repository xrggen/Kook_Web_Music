from __future__ import annotations

import asyncio
import collections
import logging
import os
import random
import ssl
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from shared.relay_protocol import (
    ACTIONS,
    MAX_MESSAGE_BYTES,
    PLAYBACK_WRITE_ACTIONS,
    PROTOCOL_VERSION,
    ProtocolError,
    action_spec,
    decode_message,
    encode_message,
    new_envelope,
)
from .local_control import LocalControlClient, LocalControlError

LOGGER = logging.getLogger(__name__)


class EdgeAgent:
    def __init__(self, platform_dir: Path, local_port: int):
        self.platform_dir = Path(platform_dir).resolve()
        self.local = LocalControlClient(self.platform_dir, local_port)
        self.agent_id = os.environ.get("EDGE_AGENT_ID", "edge-main").strip() or "edge-main"
        self.agent_name = os.environ.get("EDGE_AGENT_NAME", self.agent_id).strip() or self.agent_id
        self.token = os.environ.get("EDGE_AGENT_TOKEN", "").strip()
        self.relay_url = os.environ.get("EDGE_RELAY_URL", "").strip()
        self.version = os.environ.get("APP_VERSION", "desktop-ui-v2").strip() or "desktop-ui-v2"
        self.heartbeat_interval = max(5.0, float(os.environ.get("EDGE_HEARTBEAT_INTERVAL", "15")))
        self.runtime_sync_interval = max(2.0, float(os.environ.get("EDGE_RUNTIME_SYNC_INTERVAL", "5")))
        self.topology_sync_interval = max(30.0, float(os.environ.get("EDGE_TOPOLOGY_SYNC_INTERVAL", "300")))
        self.tls_verify = os.environ.get("EDGE_RELAY_TLS_VERIFY", "true").strip().lower() not in {"0", "false", "no", "off"}
        self.boot_id = str(uuid.uuid4())
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._seq = 0
        self._result_cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._topology: dict[str, Any] = {"guilds": [], "channels": {}}
        self._target_locks: dict[str, asyncio.Lock] = {}

        if not self.relay_url:
            raise RuntimeError("EDGE_RELAY_URL is required")
        if len(self.token) < 32:
            raise RuntimeError("EDGE_AGENT_TOKEN must contain at least 32 characters")
        relay = urlsplit(self.relay_url)
        if relay.scheme not in {"ws", "wss"} or not relay.hostname:
            raise RuntimeError("EDGE_RELAY_URL must be an absolute ws:// or wss:// URL")
        if relay.username or relay.password or relay.query or relay.fragment:
            raise RuntimeError(
                "EDGE_RELAY_URL must not contain credentials, query parameters or fragments"
            )
        if relay.path.rstrip("/") != "/edge/v1/connect":
            raise RuntimeError("EDGE_RELAY_URL path must be /edge/v1/connect")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="edge-relay-agent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_forever())
        except Exception:
            LOGGER.exception("Edge agent terminated unexpectedly")

    def _ssl_option(self):
        if self.relay_url.startswith("ws://"):
            return None
        if self.tls_verify:
            return ssl.create_default_context()
        LOGGER.warning("EDGE_RELAY_TLS_VERIFY=false; TLS certificate verification is disabled")
        return False

    async def _run_forever(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.local.wait_until_ready, 60.0)
                await self._connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                base = min(30.0, 2 ** min(attempt - 1, 5))
                delay = base + random.uniform(0.0, min(3.0, base * 0.25))
                LOGGER.warning("Edge relay disconnected (%s); reconnecting in %.1fs", type(exc).__name__, delay)
                await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        timeout = aiohttp.ClientTimeout(total=None, connect=15, sock_connect=15, sock_read=None)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Agent-ID": self.agent_id,
            "User-Agent": "kook-edge-agent/1",
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                self.relay_url,
                headers=headers,
                heartbeat=20.0,
                autoping=True,
                ssl=self._ssl_option(),
                max_msg_size=MAX_MESSAGE_BYTES,
            ) as ws:
                LOGGER.info("Edge relay connected: %s", self.relay_url)
                await self._send(
                    ws,
                    new_envelope(
                        "hello",
                        payload={
                            "agent_id": self.agent_id,
                            "name": self.agent_name,
                            "version": self.version,
                            "protocol_version": PROTOCOL_VERSION,
                            "boot_id": self.boot_id,
                            "capabilities": sorted(ACTIONS),
                        },
                    ),
                )
                await self._send_full_state(ws)
                tasks = [
                    asyncio.create_task(self._heartbeat_loop(ws)),
                    asyncio.create_task(self._runtime_sync_loop(ws)),
                    asyncio.create_task(self._topology_sync_loop(ws)),
                ]
                try:
                    async for message in ws:
                        if message.type in {aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY}:
                            await self._handle_message(ws, message.data)
                        elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def _send(self, ws: aiohttp.ClientWebSocketResponse, message: dict[str, Any]) -> None:
        await ws.send_str(encode_message(message))

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def _emit(self, ws: aiohttp.ClientWebSocketResponse, event: str, payload: dict[str, Any]) -> None:
        await self._send(ws, new_envelope("event", seq=self._next_seq(), event=event, payload=payload))

    async def _heartbeat_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed and not self._stop.is_set():
            await asyncio.sleep(self.heartbeat_interval)
            await self._send(ws, new_envelope("heartbeat", id=uuid.uuid4().hex, payload={"boot_id": self.boot_id, "monotonic": time.monotonic()}))

    async def _runtime_sync_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed and not self._stop.is_set():
            await asyncio.sleep(self.runtime_sync_interval)
            try:
                payload = await asyncio.to_thread(self._build_runtime_state)
                await self._emit(ws, "state.runtime", payload)
            except Exception as exc:
                LOGGER.warning("Runtime state sync failed: %s", type(exc).__name__)

    async def _topology_sync_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed and not self._stop.is_set():
            await asyncio.sleep(self.topology_sync_interval)
            try:
                await self._send_full_state(ws)
            except Exception as exc:
                LOGGER.warning("Topology state sync failed: %s", type(exc).__name__)

    async def _send_full_state(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        payload = await asyncio.to_thread(self._build_full_state)
        await self._emit(ws, "state.full", payload)

    def _invoke_json(self, action: str, *, query: dict | None = None, body: dict | None = None) -> dict:
        result = self.local.invoke(action, {"query": query or {}, "json": body or {}})
        payload = result.get("json")
        return payload if isinstance(payload, dict) else {}

    def _build_full_state(self) -> dict[str, Any]:
        guild_result = self._invoke_json("guild.list")
        guilds = guild_result.get("guilds") if isinstance(guild_result.get("guilds"), list) else []
        channels_by_guild: dict[str, list[dict]] = {}
        for guild in guilds:
            if not isinstance(guild, dict):
                continue
            guild_id = str(guild.get("id", "")).strip()
            if not guild_id:
                continue
            channel_result = self._invoke_json("channel.list", query={"guild_id": guild_id})
            channels = channel_result.get("channels") if isinstance(channel_result.get("channels"), list) else []
            channels_by_guild[guild_id] = channels
        self._topology = {"guilds": guilds, "channels": channels_by_guild}
        return {
            "agent": {
                "agent_id": self.agent_id,
                "name": self.agent_name,
                "version": self.version,
                "protocol_version": PROTOCOL_VERSION,
                "boot_id": self.boot_id,
            },
            "guilds": guilds,
            "channels": channels_by_guild,
            "runtime": self._build_runtime_state(),
            "accounts": self._build_account_state(),
            "generated_at": time.time(),
        }

    def _build_runtime_state(self) -> dict[str, Any]:
        active_by_guild: dict[str, dict[str, str]] = {}
        playlists: dict[str, dict[str, Any]] = {}
        for guild in self._topology.get("guilds", []):
            if not isinstance(guild, dict):
                continue
            guild_id = str(guild.get("id", "")).strip()
            if not guild_id:
                continue
            active_result = self._invoke_json("channel.active", query={"guild_id": guild_id})
            active = active_result.get("active") if isinstance(active_result.get("active"), dict) else {}
            active_by_guild[guild_id] = active
            for channel_id in active:
                playlists[str(channel_id)] = self._invoke_json(
                    "playlist.current",
                    query={"guild_id": guild_id, "channel_id": str(channel_id)},
                )
        return {
            "active": active_by_guild,
            "playlists": playlists,
            "stats": self._invoke_json("runtime.stats"),
            "debug": self._invoke_json("runtime.debug"),
            "generated_at": time.time(),
        }

    def _build_account_state(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for platform, action in (
            ("netease", "netease.account.status"),
            ("qq", "qq.account.status"),
            ("bili", "bili.account.status"),
        ):
            try:
                result[platform] = self._invoke_json(action)
            except Exception as exc:
                result[platform] = {"available": False, "error": type(exc).__name__}
        return result

    async def _handle_message(self, ws: aiohttp.ClientWebSocketResponse, raw: str | bytes) -> None:
        try:
            message = decode_message(raw)
        except ProtocolError:
            await ws.close(code=4002, message=b"protocol error")
            return
        if message["type"] == "command":
            asyncio.create_task(self._handle_command(ws, message))
        elif message["type"] == "hello_ack":
            LOGGER.info("Cloud acknowledged edge agent %s", self.agent_id)

    def _cache_result(self, command_id: str, message: dict[str, Any]) -> None:
        self._result_cache[command_id] = message
        self._result_cache.move_to_end(command_id)
        while len(self._result_cache) > 1024:
            self._result_cache.popitem(last=False)

    async def _handle_command(self, ws: aiohttp.ClientWebSocketResponse, message: dict[str, Any]) -> None:
        command_id = str(message.get("id", ""))
        action = str(message.get("action", ""))
        if not command_id:
            return
        cached = self._result_cache.get(command_id)
        if cached is not None:
            await self._send(ws, cached)
            return
        try:
            action_spec(action)
            deadline = float(message.get("deadline") or 0.0)
            if deadline and time.time() > deadline:
                raise TimeoutError("command deadline exceeded")
            payload = message.get("payload")
            if action in PLAYBACK_WRITE_ACTIONS:
                body = payload.get("json", {}) if isinstance(payload, dict) else {}
                target = str(body.get("channel_id") or body.get("guild_id") or "global")
                lock = self._target_locks.setdefault(target, asyncio.Lock())
                async with lock:
                    local_result = await asyncio.to_thread(self.local.invoke, action, payload)
            else:
                local_result = await asyncio.to_thread(self.local.invoke, action, payload)
            result_message = new_envelope("result", id=command_id, ok=True, payload=local_result)
        except TimeoutError:
            result_message = new_envelope("result", id=command_id, ok=False, error={"code": "DEADLINE_EXCEEDED", "message": "command expired"})
        except (ProtocolError, LocalControlError) as exc:
            result_message = new_envelope("result", id=command_id, ok=False, error={"code": "EDGE_REQUEST_FAILED", "message": str(exc)[:256]})
        except Exception as exc:
            LOGGER.exception("Edge command failed: %s", action)
            result_message = new_envelope("result", id=command_id, ok=False, error={"code": "EDGE_INTERNAL_ERROR", "message": type(exc).__name__})
        self._cache_result(command_id, result_message)
        await self._send(ws, result_message)
