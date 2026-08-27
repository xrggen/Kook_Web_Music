import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HealthSnapshot:
    now: float
    process_started_at: float
    supervisor_ready_at: Optional[float]
    loop_heartbeat_at: Optional[float]
    gateway_heartbeat_at: Optional[float]
    gateway_probe_available: bool
    bot_state: str
    bot_failure_reason: str

    def age(self, timestamp: Optional[float]) -> Optional[float]:
        if timestamp is None:
            return None
        return max(0.0, self.now - timestamp)


class RuntimeHealth:
    """线程安全的进程内健康信号，统一使用 monotonic 时钟。"""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._process_started_at = clock()
        self._supervisor_ready_at = None
        self._loop_heartbeat_at = None
        self._gateway_heartbeat_at = None
        self._gateway_probe_available = False
        self._bot_state = "initializing"
        self._bot_failure_reason = ""

    def mark_supervisor_ready(self):
        with self._lock:
            self._supervisor_ready_at = self._clock()

    def mark_loop_heartbeat(self):
        with self._lock:
            self._loop_heartbeat_at = self._clock()

    def mark_gateway_activity(self):
        with self._lock:
            self._gateway_heartbeat_at = self._clock()
            self._gateway_probe_available = True
            self._bot_state = "online"
            self._bot_failure_reason = ""

    def mark_gateway_probe_available(self):
        with self._lock:
            self._gateway_probe_available = True

    def mark_bot_state(self, state, reason=""):
        with self._lock:
            self._bot_state = str(state)
            self._bot_failure_reason = str(reason or "")

    def snapshot(self):
        with self._lock:
            return HealthSnapshot(
                now=self._clock(),
                process_started_at=self._process_started_at,
                supervisor_ready_at=self._supervisor_ready_at,
                loop_heartbeat_at=self._loop_heartbeat_at,
                gateway_heartbeat_at=self._gateway_heartbeat_at,
                gateway_probe_available=self._gateway_probe_available,
                bot_state=self._bot_state,
                bot_failure_reason=self._bot_failure_reason,
            )

    def bot_is_healthy(self, loop_timeout=90.0, gateway_timeout=90.0):
        snapshot = self.snapshot()
        loop_age = snapshot.age(snapshot.loop_heartbeat_at)
        gateway_age = snapshot.age(snapshot.gateway_heartbeat_at)
        return (
            snapshot.bot_state == "online"
            and loop_age is not None
            and loop_age <= loop_timeout
            and (
                not snapshot.gateway_probe_available
                or (
                    gateway_age is not None
                    and gateway_age <= gateway_timeout
                )
            )
        )


runtime_health = RuntimeHealth()
