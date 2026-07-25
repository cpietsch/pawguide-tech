from __future__ import annotations

from typing import Any

import pawguide.show_acceptance as show


class FakeMonitor:
    target = [0.0, 0.0, 0.0]

    def __init__(self, _url: str) -> None:
        self.sequence = 0
        self.origin = list(self.target)
        self.path: list[list[float]] = []
        self.trajectory: list[list[float]] = []

    def start(self) -> None:
        pass

    def latest(self) -> show.PoseSample:
        self.sequence += 1
        sample = show.PoseSample(
            position=list(self.target),
            orientation=[0.0, 0.0, 0.0, 1.0],
            sequence=self.sequence,
            observed_at=f"sample-{self.sequence}",
        )
        self.trajectory.append(list(sample.position))
        return sample

    def wait_for_pose(self, _timeout_s: float) -> show.PoseSample:
        return self.latest()

    def reset_route_evidence(self) -> None:
        self.origin = list(self.target)
        self.path = []
        self.trajectory = []

    def wait_for_path(self, _timeout_s: float) -> list[list[float]]:
        self.path = [list(self.origin[:2]), list(self.target[:2])]
        return [list(point) for point in self.path]

    def route_evidence(self) -> tuple[list[list[float]], list[list[float]]]:
        return (
            [list(point) for point in self.path],
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
        self, action: show.Action, **arguments: Any
    ) -> tuple[dict[str, Any], float]:
        self.commands.append(action.value)
        reasons = {
            show.Action.STOP: ("stop_latched", "stopped"),
            show.Action.RESET_STOP: ("stop_reset", "idle"),
            show.Action.STAND_UP: ("stand_up_sent", "idle"),
            show.Action.GREETING: ("greeting_sent", "idle"),
            show.Action.GO_TO_WAYPOINT: ("navigation_started", "navigating"),
            show.Action.PAUSE: ("mission_paused", "paused"),
            show.Action.RETURN_HOME: ("returning_home", "returning"),
            show.Action.SIT_DOWN: ("sit_down_sent", "idle"),
        }
        reason, state = reasons[action]
        if action is show.Action.STOP:
            self.state.update(
                stop_latched=True,
                mission_state="stopped",
                active_waypoint=None,
                last_stop_reason="operator_stop",
            )
        elif action is show.Action.RESET_STOP:
            self.state.update(stop_latched=False, mission_state="idle")
        elif action is show.Action.GO_TO_WAYPOINT:
            assert arguments == {"waypoint_id": "demo_gate"}
            FakeMonitor.target = [5.0, 0.0, 0.0]
            self.state.update(
                mission_state="navigating", active_waypoint="demo_gate"
            )
        elif action is show.Action.RETURN_HOME:
            FakeMonitor.target = [0.0, 0.0, 0.0]
            self.state.update(
                mission_state="returning", active_waypoint="home"
            )
        else:
            self.state["mission_state"] = state
        return {"accepted": True, "reason": reason, "state": state}, 10

    def start_heartbeat(self, period_s: float = 0.5) -> None:
        assert period_s == 0.5
        self.state["operator_heartbeat_fresh"] = True

    def stop_heartbeat(self) -> None:
        self.state["operator_heartbeat_fresh"] = False

    def close(self) -> None:
        self.stop_heartbeat()


ENDPOINTS = {
    "home": {
        "position": [0.0, 0.0, 0.0],
        "orientation": [0.0, 0.0, 0.0, 1.0],
    },
    "demo_gate": {
        "position": [5.0, 0.0, 0.0],
        "orientation": [0.0, 0.0, 0.0, 1.0],
    },
}


def test_complete_show_sequence_requires_confirmations_and_finishes_stopped(
    monkeypatch,
) -> None:
    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home"]
    FakeMonitor.target = [0.0, 0.0, 0.0]
    monkeypatch.setattr(show, "GatewaySession", FakeGateway)
    monkeypatch.setattr(show, "ShowPoseMonitor", FakeMonitor)
    confirmations: list[str] = []

    def confirm(stage: str, _pose: show.PoseSample | None) -> str:
        confirmations.append(stage)
        return "operator-a"

    report = show.run_show_acceptance(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        endpoints=ENDPOINTS,
        confirm=confirm,
        stationary_dwell_s=0,
        stationary_samples=3,
    )

    assert report.passed
    assert report.show_elapsed_s is not None
    assert report.show_elapsed_s <= 120
    duration = next(
        check for check in report.checks if check.name == "show_duration"
    )
    assert duration.passed
    assert confirmations == [
        "activation_ready",
        "greeting_complete",
        "gate_arrived",
        "farewell_complete",
        "home_arrived",
        "sitting_complete",
    ]
    assert FakeGateway.instances[0].commands == [
        "stop",
        "reset_stop",
        "stand_up",
        "greeting",
        "go_to_waypoint",
        "pause",
        "greeting",
        "return_home",
        "pause",
        "sit_down",
        "stop",
    ]
    assert report.final_state is not None
    assert report.final_state == {
        "stop_latched": True,
        "operator_heartbeat_fresh": False,
        "mission_state": "stopped",
        "active_waypoint": None,
        "last_stop_reason": "operator_stop",
    }
    assert report.outbound_path == [[0.0, 0.0], [5.0, 0.0]]
    assert report.return_path == [[5.0, 0.0], [0.0, 0.0]]
    assert report.outbound_path_exit_segments == []
    assert report.outbound_trajectory_exit_segments == []
    assert report.return_path_exit_segments == []
    assert report.return_trajectory_exit_segments == []
    assert not report.warnings


def test_extra_waypoint_fails_closed_before_arming_but_still_stops(
    monkeypatch,
) -> None:
    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home", "demo_b"]
    FakeMonitor.target = [0.0, 0.0, 0.0]
    monkeypatch.setattr(show, "GatewaySession", FakeGateway)
    monkeypatch.setattr(show, "ShowPoseMonitor", FakeMonitor)

    report = show.run_show_acceptance(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        endpoints=ENDPOINTS,
        confirm=lambda _stage, _pose: "operator-a",
        stationary_dwell_s=0,
    )

    assert not report.passed
    assert FakeGateway.instances[0].commands == ["stop"]
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True
    exact = next(check for check in report.checks if check.name == "exact_waypoints")
    assert not exact.passed
    final = next(check for check in report.checks if check.name == "final_stop")
    assert final.passed


def test_missing_operator_confirmation_fails_closed(monkeypatch) -> None:
    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home"]
    FakeMonitor.target = [0.0, 0.0, 0.0]
    monkeypatch.setattr(show, "GatewaySession", FakeGateway)
    monkeypatch.setattr(show, "ShowPoseMonitor", FakeMonitor)

    report = show.run_show_acceptance(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        endpoints=ENDPOINTS,
        confirm=lambda stage, _pose: (
            "" if stage == "gate_arrived" else "operator-a"
        ),
        stationary_dwell_s=0,
    )

    assert not report.passed
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True
    assert report.final_state["operator_heartbeat_fresh"] is False
    assert FakeGateway.instances[0].commands[-1] == "stop"


def test_path_leaving_protected_corridor_fails_closed(monkeypatch) -> None:
    class OffLaneMonitor(FakeMonitor):
        def wait_for_path(self, _timeout_s: float) -> list[list[float]]:
            self.path = [
                list(self.origin[:2]),
                [2.5, 0.5],
                list(self.target[:2]),
            ]
            return [list(point) for point in self.path]

    FakeGateway.instances.clear()
    FakeGateway.allowed_waypoints = ["demo_gate", "home"]
    FakeMonitor.target = [0.0, 0.0, 0.0]
    monkeypatch.setattr(show, "GatewaySession", FakeGateway)
    monkeypatch.setattr(show, "ShowPoseMonitor", OffLaneMonitor)

    report = show.run_show_acceptance(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        endpoints=ENDPOINTS,
        confirm=lambda _stage, _pose: "operator-a",
        stationary_dwell_s=0,
    )

    assert not report.passed
    corridor = next(
        check
        for check in report.checks
        if check.name == "outbound_protected_corridor"
    )
    assert not corridor.passed
    assert report.outbound_path_exit_segments
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True


def test_quaternion_error_treats_sign_as_equivalent() -> None:
    assert show._quaternion_error(
        [0.0, 0.0, 0.0, 1.0],
        [0.0, 0.0, 0.0, -1.0],
    ) == 0
