from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

from shared.relay_protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    action_spec,
    decode_message,
    encode_message,
    new_envelope,
    validate_rpc_payload,
)

from . import agent_registry

LOGGER = logging.getLogger(__name__)


class EdgeOfflineError(RuntimeError):
    pass


class EdgeCommandTimeout(RuntimeError):
    pass


@dataclass
class AgentConnection:
    agent_id: str
    ws: web.WebSocketResponse
    boot_id: str = ""
    version: str = ""
    connected_at: float = field(default_factory=time.time)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class RelayHub:
    def __init__(self, host: str = "127.0.0.1", port: int = 18476):
        self.host = host
        self.port = int(port)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._connections: dict[str, AgentConnection] = {}
        self._state: dict[str, dict[str, Any]] = {}
        self._state_lock = threading.RLock()
        self._runner: web.AppRunner | None = None

    def start(self, timeout: float = 10.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        agent_registry.init_registry()
        self._thread = threading.Thread(target=self._thread_main, name="cloud-edge-relay", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("edge relay failed to start")

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
            self._ready.set()
            loop.run_forever()
        except Exception:
            LOGGER.exception("Edge relay stopped unexpectedly")
            self._ready.set()
        finally:
            if self._runner is not None:
                try:
                    loop.run_until_complete(self._runner.cleanup())
                except Exception:
                    LOGGER.exception("Edge relay cleanup failed")
            loop.close()

    async def _serve(self) -> None:
        app = web.Application(client_max_size=MAX_MESSAGE_BYTES)
        app.router.add_get("/edge/v1/connect", self._websocket_handler)
        app.router.add_get("/healthz", self._relay_health)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        LOGGER.info("Edge relay listening on ws://%s:%d/edge/v1/connect", self.host, self.port)

    async def _relay_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "protocol": PROTOCOL_VERSION})

    @staticmethod
    def _bearer_token(request: web.Request) -> str:
        value = request.headers.get("Authorization", "")
        return value[7:].strip() if value.startswith("Bearer ") else ""

    async def _websocket_handler(self, request: web.Request) -> web.StreamResponse:
        agent_id = request.headers.get("X-Agent-ID", "").strip()
        token = self._bearer_token(request)
        if not agent_registry.authenticate(agent_id, token):
            LOGGER.warning("Rejected edge relay authentication for agent_id=%r", agent_id[:128])
            raise web.HTTPUnauthorized(text="unauthorized")

        ws = web.WebSocketResponse(heartbeat=20.0, receive_timeout=60.0, max_msg_size=MAX_MESSAGE_BYTES, autoping=True)
        await ws.prepare(request)

        old = self._connections.get(agent_id)
        if old and not old.ws.closed:
            await old.ws.close(code=4001, message=b"superseded")

        connection = AgentConnection(agent_id=agent_id, ws=ws)
        self._connections[agent_id] = connection
        agent_registry.mark_connected(agent_id, protocol_version=PROTOCOL_VERSION)
        LOGGER.info("Edge connected: %s", agent_id)
        try:
            async for message in ws:
                if message.type in {WSMsgType.TEXT, WSMsgType.BINARY}:
                    await self._handle_message(connection, message.data)
                elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                    break
        finally:
            if self._connections.get(agent_id) is connection:
                self._connections.pop(agent_id, None)
            agent_registry.mark_disconnected(agent_id)
            for future in list(connection.pending.values()):
                if not future.done():
                    future.set_exception(EdgeOfflineError("edge disconnected"))
            connection.pending.clear()
            LOGGER.info("Edge disconnected: %s", agent_id)
        return ws

    async def _handle_message(self, connection: AgentConnection, raw: str | bytes) -> None:
        try:
            message = decode_message(raw)
        except ProtocolError:
            await connection.ws.close(code=4002, message=b"protocol error")
            return
        agent_registry.mark_seen(connection.agent_id)
        message_type = message["type"]

        if message_type == "hello":
            payload = message.get("payload") or {}
            if not isinstance(payload, dict) or str(payload.get("agent_id", "")) != connection.agent_id:
                await connection.ws.close(code=4003, message=b"agent mismatch")
                return
            connection.boot_id = str(payload.get("boot_id", ""))[:128]
            connection.version = str(payload.get("version", ""))[:128]
            agent_registry.mark_connected(connection.agent_id, version=connection.version, protocol_version=PROTOCOL_VERSION)
            await connection.ws.send_str(encode_message(new_envelope("hello_ack", payload={"agent_id": connection.agent_id, "protocol_version": PROTOCOL_VERSION, "server_time": time.time()})))
            return

        if message_type == "heartbeat":
            await connection.ws.send_str(encode_message(new_envelope("heartbeat_ack", id=message.get("id"), payload={"server_time": time.time()})))
            return

        if message_type == "result":
            command_id = str(message.get("id", ""))
            future = connection.pending.get(command_id)
            if future and not future.done():
                future.set_result(message)
            return

        if message_type == "event":
            event_name = str(message.get("event", ""))
            payload = message.get("payload")
            if isinstance(payload, dict):
                self._apply_event(connection.agent_id, event_name, payload, message)

    def _apply_event(self, agent_id: str, event_name: str, payload: dict[str, Any], envelope: dict[str, Any]) -> None:
        now = time.time()
        with self._state_lock:
            state = self._state.setdefault(agent_id, {"agent_id": agent_id, "full": {}, "runtime": {}, "last_event_at": now, "seq": 0})
            seq = int(envelope.get("seq") or 0)
            if seq and seq < int(state.get("seq") or 0):
                return
            if seq:
                state["seq"] = seq
            state["last_event_at"] = now
            if event_name == "state.full":
                state["full"] = copy.deepcopy(payload)
                state["runtime"] = copy.deepcopy(payload.get("runtime") or {})
                guilds = payload.get("guilds") or []
                if isinstance(guilds, list):
                    agent_registry.sync_agent_guilds(agent_id, guilds)
            elif event_name == "state.runtime":
                state["runtime"] = copy.deepcopy(payload)
            elif event_name == "state.account":
                state["accounts"] = copy.deepcopy(payload)

    async def _call_async(self, agent_id: str, action: str, payload: dict[str, Any] | None, timeout: float | None) -> dict[str, Any]:
        import secrets
        spec = action_spec(action)
        connection = self._connections.get(agent_id)
        if connection is None or connection.ws.closed:
            raise EdgeOfflineError(f"edge {agent_id} is offline")
        cleaned = validate_rpc_payload(payload)
        command_id = secrets.token_urlsafe(18)
        effective_timeout = float(timeout if timeout is not None else spec.timeout)
        future = asyncio.get_running_loop().create_future()
        connection.pending[command_id] = future
        try:
            await connection.ws.send_str(encode_message(new_envelope("command", id=command_id, action=action, deadline=time.time() + effective_timeout, payload=cleaned)))
            try:
                return await asyncio.wait_for(future, timeout=effective_timeout)
            except asyncio.TimeoutError as exc:
                raise EdgeCommandTimeout(f"edge command timed out: {action}") from exc
        finally:
            connection.pending.pop(command_id, None)

    def call(self, agent_id: str, action: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        if self._loop is None or not self._ready.is_set():
            raise EdgeOfflineError("relay is not ready")
        spec = action_spec(action)
        future = asyncio.run_coroutine_threadsafe(self._call_async(agent_id, action, payload, timeout), self._loop)
        try:
            return future.result(timeout=float(timeout if timeout is not None else spec.timeout) + 2.0)
        except TimeoutError as exc:
            future.cancel()
            raise EdgeCommandTimeout(f"edge command timed out: {action}") from exc

    def is_connected(self, agent_id: str) -> bool:
        connection = self._connections.get(agent_id)
        return bool(connection and not connection.ws.closed)

    def state_snapshot(self, agent_id: str) -> dict[str, Any]:
        with self._state_lock:
            return copy.deepcopy(self._state.get(agent_id, {}))

    def all_state(self) -> dict[str, Any]:
        with self._state_lock:
            return copy.deepcopy(self._state)

    def status(self) -> list[dict[str, Any]]:
        rows = agent_registry.list_agents()
        for row in rows:
            row["connected"] = self.is_connected(str(row["agent_id"]))
            snapshot = self.state_snapshot(str(row["agent_id"]))
            row["last_event_at"] = snapshot.get("last_event_at")
            row["state_seq"] = snapshot.get("seq", 0)
        return rows

    def agent_for_guild(self, guild_id: str) -> str | None:
        return agent_registry.agent_for_guild(guild_id)
