from __future__ import annotations

import time
import unittest

from flask import Flask

from cloud.runtime_proxy import RuntimeProxy


class FakeHub:
    def __init__(self, connected: bool):
        self.connected = connected
        self.calls = []

    def agent_for_guild(self, _guild_id: str):
        return None

    def is_connected(self, _agent_id: str) -> bool:
        return self.connected

    def state_snapshot(self, _agent_id: str):
        return {
            "last_event_at": time.time(),
            "full": {},
            "runtime": {"active": {"guild-1": {}}},
        }

    def call(self, agent_id: str, action: str, payload: dict, timeout: float):
        self.calls.append((agent_id, action, payload, timeout))
        return {
            "ok": True,
            "payload": {
                "status": 200,
                "json": {
                    "success": True,
                    "active": {"channel-1": "connected"},
                },
            },
        }


class FakeAuth:
    pass


def invoke_channel_active(hub: FakeHub):
    app = Flask(__name__)
    proxy = RuntimeProxy(hub, FakeAuth())
    with app.test_request_context("/api/channels/active?guild_id=guild-1"):
        return proxy.invoke("channel.active")


class RuntimeProxyTests(unittest.TestCase):
    def test_connected_channel_active_bypasses_periodic_snapshot(self):
        hub = FakeHub(connected=True)

        response, status = invoke_channel_active(hub)

        assert status == 200
        assert response.get_json()["active"] == {"channel-1": "connected"}
        assert len(hub.calls) == 1
        assert hub.calls[0][1] == "channel.active"


    def test_disconnected_channel_active_keeps_cached_offline_fallback(self):
        hub = FakeHub(connected=False)

        response, status = invoke_channel_active(hub)

        assert status == 200
        assert response.get_json() == {
            "success": True,
            "active": {},
            "edge_stale": True,
        }
        assert hub.calls == []
