import asyncio
import ast
import json
import logging
import sys
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aiohttp import WSMsgType
from khl import Bot, Message

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))
from bot_gateway import GatewayMonitor, install_gateway_monitor
from runtime_health import RuntimeHealth


def packet(signal, detail=None, sequence=None, compressed=False):
    data = {"s": signal, "d": detail}
    if sequence is not None:
        data['sn'] = sequence
    raw = json.dumps(data)
    return SimpleNamespace(type=WSMsgType.BINARY if compressed else WSMsgType.TEXT,
                           data=zlib.compress(raw.encode()) if compressed else raw)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.receiver = SimpleNamespace(type='websocket', compress=True, _NEWEST_SN=45,
                                        _RAW_GATEWAY='wss://synthetic.invalid', pkg_queue=asyncio.Queue())
        self.health = RuntimeHealth()
        self.logger = mock.Mock(spec=logging.Logger)
        self.monitor = GatewayMonitor(self.receiver, self.health, self.logger)
        self.monitor.ws = SimpleNamespace(closed=False, close=mock.AsyncMock(), send_json=mock.AsyncMock())
        self.monitor.hello, self.monitor.pong = asyncio.Event(), asyncio.Event()

    async def test_hello_and_pong_validate_connection(self):
        await self.monitor.handle_raw(packet(3))
        self.assertIsNone(self.health.snapshot().gateway_heartbeat_at)
        await self.monitor.handle_raw(packet(1, {'code': 0, 'session_id': 'not-exported'}))
        await self.monitor.handle_raw(packet(3))
        self.assertTrue(self.monitor.pong.is_set())
        self.assertEqual('online', self.health.snapshot().bot_state)

    async def test_reconnect_signal_closes_socket_and_clears_old_queue(self):
        await self.receiver.pkg_queue.put({'old_event': True})
        await self.monitor.handle_raw(packet(5))
        self.monitor.ws.close.assert_awaited_once()
        self.assertEqual(0, self.receiver._NEWEST_SN)
        self.assertTrue(self.receiver.pkg_queue.empty())
        await asyncio.wait_for(self.receiver.pkg_queue.join(), timeout=0.1)
        self.assertEqual('SERVER_RECONNECT', self.monitor.snapshot()['error_code'])
        self.assertEqual('reconnecting', self.health.snapshot().bot_state)

    async def test_failed_hello_is_not_reported_online(self):
        await self.monitor.handle_raw(packet(1, {'code': 40103}))
        self.assertIsNone(self.health.snapshot().gateway_heartbeat_at)
        self.assertEqual('HELLO_REJECTED', self.monitor.snapshot()['error_code'])
        self.monitor.ws.close.assert_awaited_once()

    async def test_compressed_event_reaches_sdk_queue_without_exporting_payload(self):
        await self.monitor.handle_raw(packet(1, {'code': 0}))
        event = {'type': 1, 'content': '/ping synthetic-private-text', 'author_id': 'synthetic-user'}
        await self.monitor.handle_raw(packet(0, event, sequence=73, compressed=True))
        self.assertEqual(event, self.receiver.pkg_queue.get_nowait())
        self.assertEqual(73, self.receiver._NEWEST_SN)
        snapshot = self.monitor.snapshot()
        self.assertEqual(1, snapshot['events_received'])
        self.assertNotIn('synthetic', json.dumps(snapshot))

    async def test_event_before_hello_is_rejected(self):
        await self.monitor.handle_raw(packet(0, {'type': 1}, sequence=1))
        self.assertTrue(self.receiver.pkg_queue.empty())
        self.assertEqual('EVENT_BEFORE_HELLO', self.monitor.snapshot()['error_code'])

    async def test_invalid_packet_does_not_refresh_health(self):
        await self.monitor.handle_raw(SimpleNamespace(type=WSMsgType.BINARY, data=b'broken'))
        self.assertIsNone(self.health.snapshot().gateway_heartbeat_at)
        self.assertEqual('INVALID_PACKET', self.monitor.snapshot()['error_code'])

    async def test_hello_timeout_closes_connection(self):
        async def timeout(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError()
        with mock.patch('bot_gateway.asyncio.wait_for', side_effect=timeout):
            await self.monitor.heartbeat()
        self.assertEqual('HELLO_TIMEOUT', self.monitor.snapshot()['error_code'])

    async def test_missing_pong_closes_connection(self):
        self.monitor.hello.set()
        attempts = 0
        async def timeout(awaitable, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return await awaitable
            awaitable.close()
            raise asyncio.TimeoutError()
        with mock.patch('bot_gateway.asyncio.wait_for', side_effect=timeout), mock.patch('bot_gateway.asyncio.sleep', new=mock.AsyncMock()):
            await self.monitor.heartbeat()
        self.assertEqual('PONG_TIMEOUT', self.monitor.snapshot()['error_code'])
        self.monitor.ws.send_json.assert_awaited_once()

    async def test_connection_failure_does_not_log_gateway_url(self):
        session = SimpleNamespace(ws_connect=mock.Mock(side_effect=RuntimeError('secret-bearing-url')))
        with mock.patch('bot_gateway.asyncio.sleep', new=mock.AsyncMock()):
            await self.monitor.connect(session)
        self.assertEqual('CONNECT_FAILED', self.monitor.snapshot()['error_code'])
        self.assertNotIn('secret-bearing-url', str(self.logger.mock_calls))

    async def test_connection_cleanup_cancels_heartbeat(self):
        class Socket:
            closed = False
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                self.closed = True
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration
        session = SimpleNamespace(ws_connect=mock.Mock(return_value=Socket()))
        before = asyncio.all_tasks()
        with mock.patch('bot_gateway.asyncio.sleep', new=mock.AsyncMock()):
            await self.monitor.connect(session)
        self.assertEqual(before, asyncio.all_tasks())
        self.assertIsNone(self.monitor.ws)
        self.assertEqual(0, self.receiver._NEWEST_SN)

    async def test_installation_is_idempotent_and_clears_stale_gateway_url(self):
        self.receiver._get_gateway = mock.AsyncMock()
        monitor = install_gateway_monitor(self.receiver, self.health, self.logger)
        self.assertIs(monitor, install_gateway_monitor(self.receiver, self.health, self.logger))
        await self.receiver._get_gateway(object())
        self.assertEqual('', self.receiver._RAW_GATEWAY)

    async def test_message_diagnostics_expose_only_counts(self):
        self.monitor.record_message(True)
        self.monitor.record_message(False)
        self.assertEqual(2, self.monitor.snapshot()['messages_received'])
        self.assertEqual(1, self.monitor.snapshot()['messages_denied'])

    async def test_event_dispatches_ping_through_installed_sdk(self):
        bot = Bot(token='synthetic-test-value')
        bot.loop = bot.client.loop = asyncio.get_running_loop()
        bot.client.ignore_self_msg = False
        receiver = bot.client.gate.receiver
        receiver.pkg_queue = bot.client._pkg_queue
        monitor = install_gateway_monitor(receiver, self.health, self.logger)
        monitor.hello, monitor.pong = asyncio.Event(), asyncio.Event()
        completed = asyncio.Event()

        @bot.command(name='ping')
        async def ping(msg: Message):
            self.assertEqual('/ping', msg.content)
            completed.set()

        await monitor.handle_raw(packet(1, {'code': 0}))
        await monitor.handle_raw(packet(0, {
            'channel_type': 'GROUP', 'type': 9, 'target_id': 'test-channel',
            'author_id': 'test-user', 'content': '/ping', 'msg_id': 'test-message',
            'extra': {'channel_name': 'test', 'guild_id': 'test-guild',
                      'author': {'id': 'test-user', 'username': 'test', 'roles': []}},
        }, sequence=1, compressed=True))
        event = receiver.pkg_queue.get_nowait()
        await bot.client._consume_pkg(event)
        await asyncio.wait_for(completed.wait(), timeout=1.0)

    async def test_pinned_sdk_ignores_reconnect_until_monitor_is_installed(self):
        bot = Bot(token='synthetic-test-value')
        receiver = bot.client.gate.receiver
        receiver.pkg_queue = asyncio.Queue()
        receiver._NEWEST_SN = 45
        await receiver._handle_raw(packet(5, compressed=True))
        self.assertEqual(45, receiver._NEWEST_SN)
        monitor = install_gateway_monitor(receiver, self.health, self.logger)
        monitor.ws = self.monitor.ws
        await receiver._handle_raw(packet(5, compressed=True))
        self.assertEqual(0, receiver._NEWEST_SN)
        monitor.ws.close.assert_awaited_once()


class CommandPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Execute only these application functions, without loading credentials,
        # creating a Bot, opening production logs or starting the application.
        tree = ast.parse((PLATFORM_DIR / 'app.py').read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in {'_is_allowed', '_patched_handle'}]
        self.env = {
            'Message': Message, 'ALLOWGROUP': set(), 'ALLOWCHANNEL': set(), 'ALLOWUSER': set(),
            'BOT_ALLOW_UNRESTRICTED': False, '_gateway_monitor': mock.Mock(),
            '_write_bot_diagnostics': mock.Mock(), 'logger': mock.Mock(),
            '_original_handle': mock.AsyncMock(),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'command-policy', 'exec'), self.env)
        self.msg = SimpleNamespace(content='/ping', author_id='user',
                                   ctx=SimpleNamespace(guild=SimpleNamespace(id='guild'),
                                                       channel=SimpleNamespace(id='channel')))

    async def test_empty_whitelists_still_deny(self):
        await self.env['_patched_handle'](None, None, self.msg)
        self.env['_original_handle'].assert_not_awaited()
        self.env['_gateway_monitor'].record_message.assert_called_once_with(False)

    async def test_configured_policy_dispatches_only_matching_messages(self):
        self.env['ALLOWGROUP'] = {'guild'}
        self.env['ALLOWUSER'] = {'user'}
        await self.env['_patched_handle'](None, None, self.msg)
        self.env['_original_handle'].assert_awaited_once()
        self.msg.author_id = 'other'
        await self.env['_patched_handle'](None, None, self.msg)
        self.env['_original_handle'].assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
