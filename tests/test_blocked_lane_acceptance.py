from __future__ import annotations

from typing import Any

import pawguide.blocked_lane_acceptance as blocked


class FakeMonitor:
    planned_path: list[list[float]] = []
    trajectory: list[list[float]] = [[0.0, 0.0, 0.0]]
    navigating = False

    def __init__(self, _url: str) -> None:
        self.updates = 0

    def start(self) -> None:
        pass

    def wait_for_pose(self, _timeout_s: float) -> list[float]:
        return [0.0, 0.0, 0.0]

    def latest(self) -> tuple[list[float], int]:
        self.updates += 1
        pose = self.trajectory[-1] if self.navigating else [0.0, 0.0, 0.0]
        return list(pose), self.updates

    def reset_path(self) -> None:
        pass

    def evidence(self) -> tuple[list[list[float]], list[list[float]]]:
        return (
            [list(point) for point in self.planned_path],
            [list(point) for point in self.trajectory],
        )

    def close(self) -> None:
        pass


class FakeGateway:
    instances: list["FakeGateway"] = []
    allowed_waypoints = ["demo_gate", "home"]

    def __init__(self, _url: str, _token: str) -> None:
        self.commands: list[str] = []
        self.state = {
            "stop_latched": True,
            "operator_heartbeat_fresh": False,
            "mission_state": "stopped",
            "active_waypoint": None,
            "last_stop_reason": "operator_stop",
        }
        self.__class__.instances.append(self)

    def request(
        self,
        _method: str,
        path: str,
        _payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], float]:
        if path == "/health":
            return {
                "status": "ok",
                "adapter": "dimos_mcp",
                "motion_capable": True,
            }, 10
        if path == "/v1/capabilities":
            return {"allowed_waypoints": list(self.allowed_waypoints)}, 10
        if path == "/v1/state":
            return dict(self.state), 10
        raise AssertionError(path)

    def command(
        self, action: blocked.Action, **arguments: Any
    ) -> tuple[dict[str, Any], float]:
        self.commands.append(action.value)
        if action is blocked.Action.STOP:
            self.state.update(
                stop_latched=True,
                operator_heartbeat_fresh=self.state[
                    "operator_heartbeat_fresh"
                ],
                mission_state="stopped",
                active_waypoint=None,
                last_stop_reason="operator_stop",
            )
            return {
                "accepted": True,
                "state": "stopped",
                "reason": "stop_latched",
            }, 10
        if action is blocked.Action.RESET_STOP:
            self.state.update(stop_latched=False, mission_state="idle")
            return {
                "accepted": True,
                "state": "idle",
                "reason": "stop_reset",
            }, 10
        assert action is blocked.Action.GO_TO_WAYPOINT
        assert arguments == {"waypoint_id": "demo_gate"}
        FakeMonitor.navigating = True
        self.state.update(
            mission_state="navigating", active_waypoint="demo_gate"
        )
        return {
            "accepted": True,
            "state": "navigating",
            "reason": "navigation_started",
        }, 10

    def start_heartbeat(self, period_s: float = 0.5) -> None:
        assert period_s == 0.5
        self.state["operator_heartbeat_fresh"] = True

    def stop_heartbeat(self) -> None:
        self.state["operator_heartbeat_fresh"] = False

    def close(self) -> None:
        self.stop_heartbeat()


BASE_ARGUMENTS = {
    "gateway_url": "http://gateway",
    "visualization_url": "http://viewer",
    "token": "secret",
    "endpoints": {
        "home": [0.0, 0.0, 0.0],
        "demo_gate": [5.0, 0.0, 0.0],
    },
    "corridor_center": (2.5, 0.0),
    "corridor_yaw": 0.0,
    "corridor_half_extents": (3.0, 1.0),
    "barrier_center": (2.5, 0.0),
    "barrier_yaw": 0.0,
    "barrier_half_extents": (0.1, 1.0),
    "robot_radius_m": 0.3,
    "observation_timeout_s": 0.01,
    "stationary_samples": 3,
}


def test_sealed_lane_safe_refusal_passes_and_finishes_stopped(
    monkeypatch,
) -> None:
    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home"]
    FakeMonitor.planned_path = []
    FakeMonitor.navigating = False
    FakeMonitor.trajectory = [
        [0.0, 0.0, 0.0],
        [0.05, 0.0, 0.0],
        [0.08, 0.0, 0.0],
    ]
    monkeypatch.setattr(blocked, "GatewaySession", FakeGateway)
    monkeypatch.setattr(blocked, "PoseMonitor", FakeMonitor)

    report = blocked.run_blocked_lane_acceptance(**BASE_ARGUMENTS)

    assert report.passed
    assert report.expected_safe_refusal
    assert not report.navigation_success
    assert report.refusal_mode == "operator_bounded_timeout_stop"
    assert report.max_displacement_m == 0.08
    assert report.lane_exit_samples == []
    assert report.barrier_crossing_segments == []
    assert report.final_state == {
        "stop_latched": True,
        "operator_heartbeat_fresh": False,
        "mission_state": "stopped",
        "active_waypoint": None,
        "last_stop_reason": "operator_stop",
    }
    assert FakeGateway.instances[0].commands == [
        "stop",
        "reset_stop",
        "go_to_waypoint",
        "stop",
        "stop",
    ]


def test_route_through_sealed_barrier_is_navigation_success_not_safe_refusal(
    monkeypatch,
) -> None:
    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home"]
    FakeMonitor.planned_path = [
        [0.0, 0.0],
        [2.5, 0.0],
        [5.0, 0.0],
    ]
    FakeMonitor.trajectory = [
        [0.0, 0.0, 0.0],
        [2.5, 0.0, 0.0],
        [5.0, 0.0, 0.0],
    ]
    FakeMonitor.navigating = False
    monkeypatch.setattr(blocked, "GatewaySession", FakeGateway)
    monkeypatch.setattr(blocked, "PoseMonitor", FakeMonitor)

    report = blocked.run_blocked_lane_acceptance(**BASE_ARGUMENTS)

    assert not report.passed
    assert not report.expected_safe_refusal
    route = next(
        check
        for check in report.checks
        if check.name == "no_complete_planned_route"
    )
    assert not route.passed
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True
    assert FakeGateway.instances[0].commands[-1] == "stop"


def test_extra_waypoint_fails_before_arm_and_still_stops(monkeypatch) -> None:
    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home", "demo_b"]
    FakeMonitor.planned_path = []
    FakeMonitor.navigating = False
    FakeMonitor.trajectory = [[0.0, 0.0, 0.0]]
    monkeypatch.setattr(blocked, "GatewaySession", FakeGateway)
    monkeypatch.setattr(blocked, "PoseMonitor", FakeMonitor)

    report = blocked.run_blocked_lane_acceptance(**BASE_ARGUMENTS)

    assert not report.passed
    assert FakeGateway.instances[0].commands == ["stop"]
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True
