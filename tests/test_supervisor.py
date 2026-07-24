from __future__ import annotations

import threading
import time
from uuid import uuid4

from pawguide.adapter import MockRobotAdapter
from pawguide.models import Action, CommandEnvelope, MissionState
from pawguide.supervisor import SafetySupervisor, SupervisorConfig


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FailingAdapter(MockRobotAdapter):
    def start_patrol(self) -> None:
        raise RuntimeError("transport failed")


class FailingStopAdapter(MockRobotAdapter):
    def emergency_stop(self, reason: str) -> None:
        raise RuntimeError("stop transport failed")


class BlockingMotionAdapter(MockRobotAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def go_to_waypoint(self, waypoint_id: str) -> None:
        self.calls.append(("go_to_waypoint", waypoint_id))
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test did not release motion call")


def command(action: Action, **arguments: object) -> CommandEnvelope:
    return CommandEnvelope(command_id=uuid4(), action=action, arguments=arguments)


def make_supervisor() -> tuple[SafetySupervisor, MockRobotAdapter, FakeClock]:
    adapter = MockRobotAdapter()
    clock = FakeClock()
    supervisor = SafetySupervisor(
        adapter,
        SupervisorConfig(
            allowed_waypoints=frozenset({"home", "demo_a"}),
            operator_heartbeat_timeout_s=2.0,
        ),
        clock=clock,
    )
    return supervisor, adapter, clock


def arm(supervisor: SafetySupervisor) -> None:
    supervisor.heartbeat()
    result = supervisor.submit(command(Action.RESET_STOP))
    assert result.accepted


def test_startup_is_fail_closed() -> None:
    supervisor, adapter, _clock = make_supervisor()

    result = supervisor.submit(command(Action.START_PATROL))

    assert not result.accepted
    assert result.reason == "stop_is_latched"
    assert adapter.calls == [("emergency_stop", "startup_fail_closed")]


def test_fresh_heartbeat_and_explicit_reset_are_required() -> None:
    supervisor, _adapter, _clock = make_supervisor()

    rejected = supervisor.submit(command(Action.RESET_STOP))
    supervisor.heartbeat()
    accepted = supervisor.submit(command(Action.RESET_STOP))

    assert not rejected.accepted
    assert rejected.reason == "fresh_operator_heartbeat_required"
    assert accepted.accepted
    assert supervisor.snapshot().mission_state is MissionState.IDLE


def test_only_allowlisted_waypoint_can_move() -> None:
    supervisor, adapter, _clock = make_supervisor()
    arm(supervisor)

    rejected = supervisor.submit(
        command(Action.GO_TO_WAYPOINT, waypoint_id="outside_geofence")
    )
    accepted = supervisor.submit(command(Action.GO_TO_WAYPOINT, waypoint_id="demo_a"))

    assert not rejected.accepted
    assert rejected.reason == "waypoint_not_allowed"
    assert accepted.accepted
    assert adapter.calls == [
        ("emergency_stop", "startup_fail_closed"),
        ("go_to_waypoint", "demo_a"),
    ]


def test_bounded_posture_and_greeting_actions_require_arming() -> None:
    supervisor, adapter, _clock = make_supervisor()

    rejected = supervisor.submit(command(Action.STAND_UP))
    arm(supervisor)
    stood = supervisor.submit(command(Action.STAND_UP))
    greeted = supervisor.submit(command(Action.GREETING))
    sat = supervisor.submit(command(Action.SIT_DOWN))

    assert not rejected.accepted
    assert stood.accepted
    assert greeted.accepted
    assert sat.accepted
    assert adapter.calls == [
        ("emergency_stop", "startup_fail_closed"),
        ("stand_up", None),
        ("greeting", None),
        ("sit_down", None),
    ]


def test_stop_is_latched_and_bypasses_mission_state() -> None:
    supervisor, adapter, _clock = make_supervisor()
    arm(supervisor)
    supervisor.submit(command(Action.START_PATROL))

    stopped = supervisor.submit(command(Action.STOP))
    rejected = supervisor.submit(command(Action.RETURN_HOME))

    assert stopped.accepted
    assert stopped.state is MissionState.STOPPED
    assert not rejected.accepted
    assert adapter.calls[-1] == ("emergency_stop", "operator_stop")


def test_stop_ignores_arguments_so_validation_cannot_block_it() -> None:
    supervisor, adapter, _clock = make_supervisor()
    arm(supervisor)

    stopped = supervisor.submit(command(Action.STOP, unexpected="ignored"))

    assert stopped.accepted
    assert supervisor.snapshot().stop_latched
    assert adapter.calls[-1] == ("emergency_stop", "operator_stop")


def test_watchdog_latches_stop_after_operator_heartbeat_expires() -> None:
    supervisor, adapter, clock = make_supervisor()
    arm(supervisor)
    supervisor.submit(command(Action.START_PATROL))

    clock.advance(2.01)
    snapshot = supervisor.check_watchdog()

    assert snapshot.stop_latched
    assert snapshot.last_stop_reason == "operator_heartbeat_timeout"
    assert adapter.calls[-1] == ("emergency_stop", "operator_heartbeat_timeout")


def test_watchdog_preempts_a_blocked_motion_transport() -> None:
    adapter = BlockingMotionAdapter()
    clock = FakeClock()
    supervisor = SafetySupervisor(
        adapter,
        SupervisorConfig(
            allowed_waypoints=frozenset({"home", "demo_a"}),
            operator_heartbeat_timeout_s=2.0,
        ),
        clock=clock,
    )
    arm(supervisor)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            supervisor.submit(command(Action.GO_TO_WAYPOINT, waypoint_id="demo_a"))
        )
    )
    worker.start()
    assert adapter.started.wait(timeout=1)

    clock.advance(2.01)
    started_at = time.monotonic()
    snapshot = supervisor.check_watchdog()
    watchdog_duration = time.monotonic() - started_at

    assert watchdog_duration < 0.25
    assert snapshot.stop_latched
    assert ("emergency_stop", "operator_heartbeat_timeout") in adapter.calls

    adapter.release.set()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert len(results) == 1
    assert not results[0].accepted
    assert results[0].state is MissionState.STOPPED


def test_duplicate_command_is_not_executed_twice() -> None:
    supervisor, adapter, _clock = make_supervisor()
    arm(supervisor)
    envelope = command(Action.GO_TO_WAYPOINT, waypoint_id="demo_a")

    first = supervisor.submit(envelope)
    second = supervisor.submit(envelope)

    assert first == second
    assert adapter.calls == [
        ("emergency_stop", "startup_fail_closed"),
        ("go_to_waypoint", "demo_a"),
    ]


def test_motion_adapter_failure_latches_stop() -> None:
    clock = FakeClock()
    supervisor = SafetySupervisor(
        FailingAdapter(),
        SupervisorConfig(allowed_waypoints=frozenset({"home"})),
        clock=clock,
    )
    arm(supervisor)

    result = supervisor.submit(command(Action.START_PATROL))

    assert not result.accepted
    assert result.reason == "adapter_error_stop_latched"
    assert supervisor.snapshot().stop_latched
    assert supervisor.snapshot().last_stop_reason == "adapter_error"


def test_failed_emergency_stop_dispatch_does_not_prevent_software_latch() -> None:
    clock = FakeClock()
    supervisor = SafetySupervisor(
        FailingStopAdapter(),
        SupervisorConfig(allowed_waypoints=frozenset({"home"})),
        clock=clock,
    )

    result = supervisor.submit(command(Action.STOP))

    assert not result.accepted
    assert result.reason == "stop_latched_but_dispatch_failed"
    assert supervisor.snapshot().stop_latched
    assert (
        supervisor.snapshot().last_stop_reason
        == "operator_stop:emergency_stop_dispatch_failed"
    )
