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
from .config_store import EdgeConfigStore, EdgeRelayConfig
from .local_control import LocalControlClient, LocalControlError
from .secret_store import EdgeSecretStore

LOGGER = logging.getLogger(__name__)


class FatalRelayError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class EdgeAgentSupervisor:
    """Owns one active outbound WSS while rotating through a configurable port pool."""

    def __init__(self, platform_dir: Path, local_port: int, config_store: EdgeConfigStore, secret_store: EdgeSecretStore):
        self.platform_dir = Path(platform_dir).resolve()
        self.local = LocalControlClient(self.platform_dir, local_port)
        self.config_store = config_store
        self.secret_store = secret_store
        self.version = os.environ.get("APP_VERSION", "desktop-ui-v2").strip() or "desktop-ui-v2"
        self.heartbeat_interval = max(5.0, float(os.environ.get("EDGE_HEARTBEAT_INTERVAL", "15")))
        self.runtime_sync_interval = max(2.0, float(os.environ.get("EDGE_RUNTIME_SYNC_INTERVAL", "5")))
        self.topology_sync_interval = max(30.0, float(os.environ.get("EDGE_TOPOLOGY_SYNC_INTERVAL", "300")))
        self.boot_id = str(uuid.uuid4())
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reconfigure = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._seq = 0
        self._result_cache: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._topology: dict[str, Any] = {"guilds": [], "channels": {}}
        self._target_locks: dict[str, asyncio.Lock] = {}
        self._heartbeat_sent: dict[str, float] = {}
        self._state_lock = threading.RLock()
        self._status: dict[str, Any] = {
            "state": "starting",
            "active_port": None,
            "connected_since": None,
            "last_heartbeat_at": None,
            "latency_ms": None,
            "reconnect_count": 0,
            "last_error_code": None,
            "last_error": None,
        }
        self._port_health: dict[int, dict[str, Any]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="edge-relay-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.reload()

    def reload(self) -> None:
        self._reconfigure.set()
        loop, ws = self._loop, self._ws
        if loop and ws and not ws.closed:
            asyncio.run_coroutine_threadsafe(ws.close(code=4000, message=b"reconfigure"), loop)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_forever())
        except Exception:
            LOGGER.exception("Edge agent supervisor terminated unexpectedly")
            self._set_status(state="failed", last_error_code="SUPERVISOR_FAILED")

    def _set_status(self, **updates) -> None:
        with self._state_lock:
            self._status.update(updates)

    def _set_port_health(self, port: int, state: str, code: str | None = None, detail: str | None = None) -> None:
        with self._state_lock:
            self._port_health[int(port)] = {
                "port": int(port), "state": state, "code": code,
                "detail": (detail or "")[:160], "checked_at": time.time(),
            }

    def status(self) -> dict[str, Any]:
        cfg = self.config_store.get()
        with self._state_lock:
            result = dict(self._status)
            result["ports"] = [
                self._port_health.get(port, {"port": port, "state": "unknown", "code": None, "detail": "", "checked_at": None})
                for port in range(cfg.port_start, cfg.port_end + 1)
            ]
        result.update({
            "enabled": cfg.enabled, "host": cfg.host, "port_start": cfg.port_start,
            "port_end": cfg.port_end, "path": cfg.path, "tls_verify": cfg.tls_verify,
            "agent_id": cfg.agent_id, "agent_name": cfg.agent_name,
            "preferred_port": cfg.preferred_port, "token_configured": self.secret_store.configured(),
            "protocol_version": PROTOCOL_VERSION, "version": self.version, "boot_id": self.boot_id,
        })
        return result

    @staticmethod
    def _ssl_option(cfg: EdgeRelayConfig):
        if cfg.tls_verify:
            return ssl.create_default_context()
        LOGGER.warning("Edge relay TLS certificate verification is disabled")
        return False

    @staticmethod
    def _classify_exception(exc: Exception) -> tuple[str, bool]:
        if isinstance(exc, FatalRelayError):
            return exc.code, True
        if isinstance(exc, aiohttp.WSServerHandshakeError):
            if exc.status in {401, 403}:
                return "AUTH_FAILED", True
            if 400 <= exc.status < 500:
                return f"HTTP_{exc.status}", True
            return f"HTTP_{exc.status}", False
        if isinstance(exc, aiohttp.ClientConnectorCertificateError):
            return "TLS_CERTIFICATE_ERROR", True
        if isinstance(exc, aiohttp.ClientSSLError):
            return "TLS_ERROR", True
        if isinstance(exc, asyncio.TimeoutError):
            return "TCP_TIMEOUT", False
        if isinstance(exc, aiohttp.ClientConnectorError):
            return "NETWORK_UNREACHABLE", False
        return type(exc).__name__.upper(), False

    async def _wait_or_reconfigure(self, delay: float) -> bool:
        triggered = await asyncio.to_thread(self._reconfigure.wait, delay)
        if triggered:
            self._reconfigure.clear()
        return triggered

    def _candidate_ports(self, cfg: EdgeRelayConfig) -> list[int]:
        ports = list(range(cfg.port_start, cfg.port_end + 1))
        preferred = cfg.preferred_port
        if preferred in ports:
            ports.remove(preferred)
        random.shuffle(ports)
        return ([preferred] if preferred is not None else []) + ports

    async def _run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        backoff_round = 0
        while not self._stop.is_set():
            cfg = self.config_store.get()
            if not cfg.enabled:
                self._set_status(state="disabled", active_port=None, connected_since=None)
                await self._wait_or_reconfigure(2.0)
                continue
            token = self.secret_store.read()
            if len(token) < 32:
                self._set_status(state="configuration_error", active_port=None, last_error_code="TOKEN_MISSING", last_error="Agent Token 未配置或长度不足")
                await self._wait_or_reconfigure(5.0)
                continue
            try:
                await asyncio.to_thread(self.local.wait_until_ready, 60.0)
            except Exception as exc:
                self._set_status(state="local_runtime_unavailable", last_error_code="LOCAL_RUNTIME_UNAVAILABLE", last_error=str(exc)[:160])
                await self._wait_or_reconfigure(5.0)
                continue

            fatal = False
            connected_in_round = False
            for port in self._candidate_ports(cfg):
                if self._stop.is_set() or self._reconfigure.is_set():
                    self._reconfigure.clear()
                    break
                self._set_status(state="connecting", active_port=None)
                try:
                    await self._connect_once(cfg, token, port)
                    connected_in_round = True
                    backoff_round = 0
                    if self._reconfigure.is_set():
                        self._reconfigure.clear()
                        break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    code, fatal = self._classify_exception(exc)
                    self._set_port_health(port, "failed", code, str(exc))
                    self._set_status(
                        state="configuration_error" if fatal else "disconnected",
                        active_port=None, connected_since=None, last_error_code=code,
                        last_error=str(exc)[:160], reconnect_count=int(self._status.get("reconnect_count") or 0) + 1,
                    )
                    LOGGER.warning("Edge relay port %d failed (%s)", port, code)
                    if fatal:
                        break
                    continue

            if self._stop.is_set():
                break
            if fatal:
                await self._wait_or_reconfigure(30.0)
                continue
            if connected_in_round:
                await self._wait_or_reconfigure(1.0)
                continue
            backoff_round += 1
            base = min(30.0, 2 ** min(backoff_round - 1, 5))
            await self._wait_or_reconfigure(base + random.uniform(0.0, min(3.0, base * 0.25)))

    async def _connect_once(self, cfg: EdgeRelayConfig, token: str, port: int) -> None:
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=None)
        headers = {"Authorization": f"Bearer {token}", "X-Agent-ID": cfg.agent_id, "User-Agent": "kook-edge-agent/2"}
        url = cfg.url_for(port)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(
                url, headers=headers, heartbeat=20.0, autoping=True,
                ssl=self._ssl_option(cfg), max_msg_size=MAX_MESSAGE_BYTES,
            ) as ws:
                self._ws = ws
                now = time.time()
                self.config_store.set_preferred_port(port)
                self._set_port_health(port, "active")
                self._set_status(state="connected", active_port=port, connected_since=now, last_error_code=None, last_error=None)
                LOGGER.info("Edge relay connected: host=%s port=%d", cfg.host, port)
                await self._send(ws, new_envelope("hello", payload={
                    "agent_id": cfg.agent_id, "name": cfg.agent_name, "version": self.version,
                    "protocol_version": PROTOCOL_VERSION, "boot_id": self.boot_id,
                    "active_port": port, "capabilities": sorted(ACTIONS),
                }))
                await self._send_full_state(ws, cfg)
                tasks = [
                    asyncio.create_task(self._heartbeat_loop(ws)),
                    asyncio.create_task(self._runtime_sync_loop(ws)),
                    asyncio.create_task(self._topology_sync_loop(ws, cfg)),
                ]
                try:
                    async for message in ws:
                        if self._reconfigure.is_set():
                            break
                        if message.type in {aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY}:
                            await self._handle_message(ws, message.data, cfg)
                        elif message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    self._ws = None
                    self._set_status(state="disconnected", active_port=None, connected_since=None)

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
            heartbeat_id = uuid.uuid4().hex
            self._heartbeat_sent[heartbeat_id] = time.monotonic()
            await self._send(ws, new_envelope("heartbeat", id=heartbeat_id, payload={"boot_id": self.boot_id}))

    async def _runtime_sync_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed and not self._stop.is_set():
            await asyncio.sleep(self.runtime_sync_interval)
            try:
                payload = await asyncio.to_thread(self._build_runtime_state)
                await self._emit(ws, "state.runtime", payload)
            except Exception as exc:
                LOGGER.warning("Runtime state sync failed: %s", type(exc).__name__)

    async def _topology_sync_loop(self, ws: aiohttp.ClientWebSocketResponse, cfg: EdgeRelayConfig) -> None:
        while not ws.closed and not self._stop.is_set():
            await asyncio.sleep(self.topology_sync_interval)
            try:
                await self._send_full_state(ws, cfg)
            except Exception as exc:
                LOGGER.warning("Topology state sync failed: %s", type(exc).__name__)

    async def _send_full_state(self, ws: aiohttp.ClientWebSocketResponse, cfg: EdgeRelayConfig) -> None:
        payload = await asyncio.to_thread(self._build_full_state, cfg)
        await self._emit(ws, "state.full", payload)

    def _invoke_json(self, action: str, *, query: dict | None = None, body: dict | None = None) -> dict:
        result = self.local.invoke(action, {"query": query or {}, "json": body or {}})
        payload = result.get("json")
        return payload if isinstance(payload, dict) else {}

    def _build_full_state(self, cfg: EdgeRelayConfig) -> dict[str, Any]:
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
                "agent_id": cfg.agent_id, "name": cfg.agent_name, "version": self.version,
                "protocol_version": PROTOCOL_VERSION, "boot_id": self.boot_id,
                "active_port": self._status.get("active_port"),
            },
            "guilds": guilds, "channels": channels_by_guild,
            "runtime": self._build_runtime_state(), "accounts": self._build_account_state(),
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
                playlists[str(channel_id)] = self._invoke_json("playlist.current", query={"guild_id": guild_id, "channel_id": str(channel_id)})
        return {
            "active": active_by_guild, "playlists": playlists,
            "stats": self._invoke_json("runtime.stats"), "debug": self._invoke_json("runtime.debug"),
            "generated_at": time.time(),
        }

    def _build_account_state(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for platform, action in (("netease", "netease.account.status"), ("qq", "qq.account.status"), ("bili", "bili.account.status")):
            try:
                result[platform] = self._invoke_json(action)
            except Exception as exc:
                result[platform] = {"available": False, "error": type(exc).__name__}
        return result

    async def _handle_message(self, ws: aiohttp.ClientWebSocketResponse, raw: str | bytes, cfg: EdgeRelayConfig) -> None:
        try:
            message = decode_message(raw)
        except ProtocolError:
            await ws.close(code=4002, message=b"protocol error")
            return
        if message["type"] == "command":
            asyncio.create_task(self._handle_command(ws, message))
        elif message["type"] == "hello_ack":
            payload = message.get("payload") or {}
            if int(payload.get("protocol_version", 0)) != PROTOCOL_VERSION:
                raise FatalRelayError("PROTOCOL_MISMATCH", "Cloud relay protocol version mismatch")
        elif message["type"] == "heartbeat_ack":
            heartbeat_id = str(message.get("id", ""))
            sent = self._heartbeat_sent.pop(heartbeat_id, None)
            if sent is not None:
                self._set_status(last_heartbeat_at=time.time(), latency_ms=round((time.monotonic() - sent) * 1000, 1))

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

    def test_ports(self) -> list[dict[str, Any]]:
        return asyncio.run(self._test_ports_async(self.config_store.get()))

    async def _test_ports_async(self, cfg: EdgeRelayConfig) -> list[dict[str, Any]]:
        timeout = aiohttp.ClientTimeout(total=4, connect=3, sock_connect=3)
        ssl_option = self._ssl_option(cfg)

        async def probe(port: int) -> dict[str, Any]:
            started = time.monotonic()
            try:
                probe_url = f"https://{cfg.host}:{port}{cfg.path}"
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(probe_url, ssl=ssl_option, allow_redirects=False) as response:
                        reachable = response.status in {400, 401, 403, 426}
                        state = "reachable" if reachable else "http_error"
                        code = None if reachable else f"HTTP_{response.status}"
                        detail = f"HTTP {response.status}"
            except Exception as exc:
                code, _fatal = self._classify_exception(exc)
                state, detail = "failed", str(exc)[:160]
            result = {"port": port, "state": state, "code": code, "detail": detail, "latency_ms": round((time.monotonic() - started) * 1000, 1)}
            self._set_port_health(port, state, code, detail)
            return result

        return await asyncio.gather(*(probe(port) for port in range(cfg.port_start, cfg.port_end + 1)))


EdgeAgent = EdgeAgentSupervisor
