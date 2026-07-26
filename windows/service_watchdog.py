from dataclasses import dataclass
from typing import Iterable, Tuple

try:
    from .runtime_health import HealthSnapshot
except ImportError:
    from runtime_health import HealthSnapshot


@dataclass(frozen=True)
class WatchdogConfig:
    startup_grace: float = 180.0
    loop_timeout: float = 90.0
    gateway_timeout: float = 90.0
    failures_before_restart: int = 3


@dataclass(frozen=True)
class WatchdogDecision:
    phase: str
    reasons: Tuple[str, ...]
    consecutive_failures: int
    should_restart: bool
    restart_blocked: bool


class WatchdogEvaluator:
    """无副作用的健康判定器，便于覆盖全部超时和恢复路径。"""

    NON_RECOVERABLE_STATES = {"configuration_error"}

    def __init__(self, config=None):
        self.config = config or WatchdogConfig()
        self.consecutive_failures = 0

    def evaluate(
        self,
        snapshot: HealthSnapshot,
        dependency_failures: Iterable[str] = (),
    ):
        ready_at = snapshot.supervisor_ready_at
        if ready_at is None:
            self.consecutive_failures = 0
            return WatchdogDecision("starting", (), 0, False, False)

        if snapshot.now - ready_at < self.config.startup_grace:
            self.consecutive_failures = 0
            return WatchdogDecision("startup_grace", (), 0, False, False)

        reasons = list(dependency_failures)
        if snapshot.bot_state in {"failed", "stopped", "configuration_error"}:
            detail = snapshot.bot_failure_reason or snapshot.bot_state
            reasons.append(f"bot_state:{detail}")

        loop_age = snapshot.age(snapshot.loop_heartbeat_at)
        if loop_age is None:
            reasons.append("bot_loop:no_heartbeat")
        elif loop_age > self.config.loop_timeout:
            reasons.append(f"bot_loop:stale:{loop_age:.1f}s")

        if snapshot.gateway_probe_available:
            gateway_age = snapshot.age(snapshot.gateway_heartbeat_at)
            if gateway_age is None:
                reasons.append("kook_gateway:no_activity")
            elif gateway_age > self.config.gateway_timeout:
                reasons.append(f"kook_gateway:stale:{gateway_age:.1f}s")

        reasons = tuple(dict.fromkeys(reasons))
        if not reasons:
            self.consecutive_failures = 0
            return WatchdogDecision("healthy", (), 0, False, False)

        self.consecutive_failures += 1
        blocked = snapshot.bot_state in self.NON_RECOVERABLE_STATES
        should_restart = (
            not blocked
            and self.consecutive_failures
            >= self.config.failures_before_restart
        )
        return WatchdogDecision(
            "unhealthy",
            reasons,
            self.consecutive_failures,
            should_restart,
            blocked,
        )
