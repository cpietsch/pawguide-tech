from __future__ import annotations

from typing import Any

import pawguide.acceptance as acceptance


class FakeGateway:
    instances: list["FakeGateway"] = []

    def __init__(self, _url: str, _token: str) -> None:
        self.commands: list[str] = []
        self.heartbeat_stopped = False
        self.last_stop_reason = "operator_stop"
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
            }, 25.0
        if path == "/v1/capabilities":
            return {"allowed_waypoints": ["home", "demo_a"]}, 25.0
        if path == "/v1/state":
            return {
                "active_waypoint": None,
                "stop_latched": True,
                "mission_state": "stopped",
                "last_stop_reason": self.last_stop_reason,
                "operator_heartbeat_fresh": False,
            }, 25.0
        raise AssertionError(path)

    def command(
        self, action: acceptance.Action, **_arguments: Any
    ) -> tuple[dict[str, Any], float]:
        self.commands.append(action.value)
        if action is acceptance.Action.STOP:
            self.last_stop_reason = "operator_stop"
            return {"accepted": True, "state": "stopped"}, 25.0
        if action is acceptance.Action.RESET_STOP:
            return {"accepted": True, "state": "idle"}, 25.0
        return {"accepted": True, "state": "navigating"}, 25.0

    def start_heartbeat(self, period_s: float = 0.5) -> None:
        assert period_s == 0.5

    def stop_heartbeat(self) -> None:
        self.heartbeat_stopped = True
        self.last_stop_reason = "operator_heartbeat_timeout"

    def close(self) -> None:
        pass


class FakePoses:
    def __init__(self, _url: str) -> None:
        self.updates = 0

    def start(self) -> None:
        pass

    def wait_for_pose(self, _timeout_s: float) -> list[float]:
        return [-1.0, 1.0, 0.3]

    def latest(self) -> tuple[list[float], int]:
        self.updates += 1
        return [0.1, 1.48, 0.3], self.updates

    def evidence(self) -> tuple[list[list[float]], list[list[float]]]:
        return [], []

    def wait_for_path(self, _timeout_s: float) -> list[list[float]]:
        return [[-1.0, 1.0], [0.1, 1.48]]

    def close(self) -> None:
        pass


def test_acceptance_requires_motion_arrival_and_finishes_stopped(monkeypatch) -> None:
    FakeGateway.instances.clear()
    monkeypatch.setattr(acceptance, "GatewaySession", FakeGateway)
    monkeypatch.setattr(acceptance, "PoseMonitor", FakePoses)

    report = acceptance.run_acceptance(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        waypoint="demo_a",
        target_pose=(0.1, 1.48),
        minimum_displacement_m=0.5,
    )

    assert report.passed
    assert report.displacement_m is not None
    assert report.displacement_m > 1
    assert report.arrival_error_m == 0
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True
    assert FakeGateway.instances[0].commands == [
        "stop",
        "reset_stop",
        "go_to_waypoint",
        "stop",
    ]


def test_percentile_uses_nearest_rank() -> None:
    assert acceptance._percentile([1, 2, 3, 4, 100], 0.95) == 100


def test_path_metrics_rejects_segment_crossing_expanded_obstacle() -> None:
    points = [[-1.0, 1.0], [0.1, 1.48]]
    _, _, _, collisions = acceptance._path_metrics(
        points,
        start=(-1.0, 1.0),
        goal=(0.1, 1.48),
        obstacle_center=(-0.45, 1.24),
        obstacle_yaw=0.41,
        obstacle_half_extents=(0.08, 0.35),
        robot_radius=0.3,
    )
    assert collisions == [0]


def test_arena_check_applies_robot_inset() -> None:
    assert acceptance._outside_arena_segments(
        [[-1.39, 1.0], [0.19, 2.0]],
        (-1.7, 0.5, 0.4, 2.4),
        0.3,
    ) == []
    assert acceptance._outside_arena_segments(
        [[-1.41, 1.0], [0.21, 2.0]],
        (-1.7, 0.5, 0.4, 2.4),
        0.3,
    ) == [0, 1]
