"""KOOK websocket recovery for the pinned khl.py receiver; no payload logging."""
import asyncio
import contextlib
import json
import threading
import time
import zlib

from aiohttp import WSMsgType


class GatewayMonitor:
    def __init__(self, receiver, health, logger):
        self.receiver = receiver
        self.health = health
        self.logger = logger
        self.ws = None
        self.hello = None
        self.pong = None
        self._lock = threading.Lock()
        self._state = "starting"
        self._error = None
        self._events = 0
        self._messages = 0
        self._denied = 0
        self._last_event = None
        self._last_message = None
        self._reconnects = 0
        self._retry_delay = 1.0

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            return {
                "state": self._state, "error_code": self._error,
                "events_received": self._events, "messages_received": self._messages,
                "messages_denied": self._denied, "reconnects": self._reconnects,
                "last_event_age": None if self._last_event is None else max(0, now - self._last_event),
                "last_message_age": None if self._last_message is None else max(0, now - self._last_message),
            }

    def record_message(self, allowed):
        with self._lock:
            self._messages += 1
            self._denied += int(not allowed)
            self._last_message = time.monotonic()

    def _set_state(self, state, code=None):
        with self._lock:
            self._state, self._error = state, code
        if state != "connected":
            self.health.mark_bot_state("reconnecting", code or state)

    async def reconnect(self, code):
        self._set_state("reconnecting", code)
        self.receiver._NEWEST_SN = 0
        self.logger.warning("[KOOK网关] 重新连接，原因=%s", code)
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()

    async def handle_raw(self, raw):
        if raw.type not in {WSMsgType.TEXT, WSMsgType.BINARY}:
            return
        try:
            data = raw.data
            if raw.type == WSMsgType.BINARY and self.receiver.compress:
                data = zlib.decompress(data)
            package = json.loads(data)
            if not isinstance(package, dict):
                raise ValueError()
        except (ValueError, TypeError, zlib.error, UnicodeError):
            await self.reconnect("INVALID_PACKET")
            return
        signal = package.get("s")
        if signal == 5:
            # A new gateway session must not reuse the old session's sequence.
            queue = self.receiver.pkg_queue
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break
            await self.reconnect("SERVER_RECONNECT")
            return
        if signal == 1:
            detail = package.get("d")
            if not isinstance(detail, dict) or detail.get("code") != 0:
                await self.reconnect("HELLO_REJECTED")
                return
            self.hello.set()
            self._set_state("connected")
            self._retry_delay = 1.0
            self.health.mark_gateway_activity()
            self.logger.info("[KOOK网关] HELLO 验证成功，开始接收事件")
        elif signal == 3:
            if self.hello.is_set():
                self.pong.set()
                self.health.mark_gateway_activity()
        elif signal == 0:
            if not self.hello.is_set():
                await self.reconnect("EVENT_BEFORE_HELLO")
                return
            sequence, event = package.get("sn"), package.get("d")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or not isinstance(event, dict):
                await self.reconnect("INVALID_EVENT")
                return
            self.receiver._NEWEST_SN = sequence
            await self.receiver.pkg_queue.put(event)
            with self._lock:
                self._events += 1
                self._last_event = time.monotonic()
            self.health.mark_gateway_activity()

    async def heartbeat(self):
        try:
            await asyncio.wait_for(self.hello.wait(), timeout=6.0)
            while not self.ws.closed:
                await asyncio.sleep(26.0)
                if self.ws.closed:
                    return
                self.pong.clear()
                await self.ws.send_json({"s": 2, "sn": self.receiver._NEWEST_SN})
                await asyncio.wait_for(self.pong.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            await self.reconnect("PONG_TIMEOUT" if self.hello.is_set() else "HELLO_TIMEOUT")
        except (ConnectionError, OSError, RuntimeError):
            await self.reconnect("HEARTBEAT_FAILED")

    async def connect(self, session):
        self.hello, self.pong = asyncio.Event(), asyncio.Event()
        self.receiver._NEWEST_SN = 0
        self._set_state("connecting")
        heartbeat = None
        try:
            if not self.receiver._RAW_GATEWAY:
                self._set_state("reconnecting", "GATEWAY_UNAVAILABLE")
                return
            async with session.ws_connect(self.receiver._RAW_GATEWAY) as ws:
                self.ws = ws
                heartbeat = asyncio.create_task(self.heartbeat())
                async for raw in ws:
                    await self.handle_raw(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The SDK's exception text can include the credential-bearing URL.
            self._set_state("reconnecting", "CONNECT_FAILED")
            self.logger.warning("[KOOK网关] 连接中断，异常类型=%s", type(exc).__name__)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
            self.ws = None
            self._set_state("reconnecting", self.snapshot()["error_code"] or "CONNECTION_CLOSED")
            with self._lock:
                self._reconnects += 1
            await asyncio.sleep(self._retry_delay)
            self._retry_delay = min(30.0, self._retry_delay * 2)


def install_gateway_monitor(receiver, health, logger):
    existing = getattr(receiver, "_kook_music_monitor", None)
    if existing is not None:
        return existing
    if getattr(receiver, "type", None) != "websocket":
        return None
    monitor = GatewayMonitor(receiver, health, logger)
    original_get_gateway = receiver._get_gateway

    async def get_gateway(session):
        receiver._RAW_GATEWAY = ""
        await original_get_gateway(session)

    receiver._get_gateway = get_gateway
    receiver._handle_raw = monitor.handle_raw
    receiver._connect_gateway_and_handle_msg = monitor.connect
    receiver._kook_music_monitor = monitor
    health.mark_gateway_probe_available()
    return monitor
