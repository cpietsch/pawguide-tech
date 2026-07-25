from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pawguide.soak as soak


class FakePoses:
    current = [-1.0, 1.0, 0.3]
    target = [0.1, 1.48, 0.3]

    def __init__(self, _url: str) -> None:
        self.updates = 0

    def start(self) -> None:
        pass

    def wait_for_pose(self, _timeout_s: float) -> list[float]:
        return list(self.current)

    def latest(self) -> tuple[list[float], int]:
        self.updates += 1
        self.current = list(self.target)
        return list(self.current), self.updates

    def close(self) -> None:
        pass


class FakeGateway:
    instances: list["FakeGateway"] = []

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
            return {"allowed_waypoints": ["home", "demo_a"]}, 10
        if path == "/v1/state":
            return dict(self.state), 10
        raise AssertionError(path)

    def command(
        self, action: soak.Action, **arguments: Any
    ) -> tuple[dict[str, Any], float]:
        self.commands.append(action.value)
        if action is soak.Action.STOP:
            self.state.update(
                stop_latched=True,
                mission_state="stopped",
                active_waypoint=None,
                last_stop_reason="operator_stop",
            )
            return {
                "accepted": True,
                "state": "stopped",
                "reason": "stop_latched",
            }, 10
        if action is soak.Action.RESET_STOP:
            self.state.update(stop_latched=False, mission_state="idle")
            return {
                "accepted": True,
                "state": "idle",
                "reason": "stop_reset",
            }, 10
        assert action is soak.Action.GO_TO_WAYPOINT
        waypoint = arguments["waypoint_id"]
        FakePoses.target = (
            [0.1, 1.48, 0.3] if waypoint == "demo_a" else [-1.0, 1.0, 0.3]
        )
        self.state.update(
            mission_state="navigating",
            active_waypoint=waypoint,
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
        if self.state["mission_state"] == "navigating":
            self.state.update(
                stop_latched=True,
                mission_state="stopped",
                active_waypoint=None,
                last_stop_reason="operator_heartbeat_timeout",
            )

    def close(self) -> None:
        self.stop_heartbeat()


def test_soak_alternates_and_writes_a_safe_artifact_per_leg(
    monkeypatch, tmp_path: Path
) -> None:
    FakeGateway.instances.clear()
    FakePoses.current = [-1.0, 1.0, 0.3]
    FakePoses.target = [0.1, 1.48, 0.3]
    monkeypatch.setattr(soak, "GatewaySession", FakeGateway)
    monkeypatch.setattr(soak, "PoseMonitor", FakePoses)

    report = soak.run_soak(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        endpoints={"home": (-1.0, 1.0), "demo_a": (0.1, 1.48)},
        legs=2,
        artifact_dir=tmp_path,
        sustained_samples=3,
        watchdog_every=2,
    )

    assert report.passed
    assert report.completed_legs == 2
    assert report.passed_legs == 2
    first = json.loads((tmp_path / "leg-0001-to-demo_a.json").read_text())
    second = json.loads((tmp_path / "leg-0002-to-home.json").read_text())
    assert first["start_waypoint"] == "home"
    assert first["target_waypoint"] == "demo_a"
    assert first["watchdog_exercised"] is False
    assert second["start_waypoint"] == "demo_a"
    assert second["target_waypoint"] == "home"
    assert second["watchdog_exercised"] is True
    assert second["final_state"]["stop_latched"] is True
    assert second["final_state"]["operator_heartbeat_fresh"] is False
    assert all(
        instance.commands
        == ["stop", "reset_stop", "go_to_waypoint", "stop"]
        for instance in FakeGateway.instances
    )
    aggregate = json.loads((tmp_path / "soak-report.json").read_text())
    assert aggregate["passed"] is True


def test_sustained_arrival_requires_fresh_consecutive_updates() -> None:
    class Sequence:
        def __init__(self) -> None:
            self.samples = iter(
                [
                    ([0.0, 0.0], 1),
                    ([1.0, 1.0], 2),
                    ([0.0, 0.0], 3),
                    ([1.0, 1.0], 4),
                    ([1.0, 1.0], 5),
                    ([1.0, 1.0], 6),
                ]
            )

        def latest(self) -> tuple[list[float], int]:
            return next(self.samples)

    pose, displacement, error = soak._wait_for_sustained_arrival(
        Sequence(),  # type: ignore[arg-type]
        initial_pose=[0.0, 0.0],
        target_pose=(1.0, 1.0),
        initial_updates=0,
        minimum_displacement_m=0.5,
        arrival_tolerance_m=0.01,
        sustained_samples=3,
        timeout_s=1,
    )

    assert pose == [1.0, 1.0]
    assert displacement > 1
    assert error == 0


def test_failed_leg_still_stops_and_writes_failure_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    class RejectingGateway(FakeGateway):
        def command(
            self, action: soak.Action, **arguments: Any
        ) -> tuple[dict[str, Any], float]:
            if action is soak.Action.GO_TO_WAYPOINT:
                self.commands.append(action.value)
                return {
                    "accepted": False,
                    "state": "stopped",
                    "reason": "adapter_error_stop_latched",
                }, 10
            return super().command(action, **arguments)

    FakePoses.current = [-1.0, 1.0, 0.3]
    monkeypatch.setattr(soak, "GatewaySession", RejectingGateway)
    monkeypatch.setattr(soak, "PoseMonitor", FakePoses)

    report = soak.run_soak(
        gateway_url="http://gateway",
        visualization_url="http://viewer",
        token="secret",
        endpoints={"home": (-1.0, 1.0), "demo_a": (0.1, 1.48)},
        legs=2,
        artifact_dir=tmp_path,
    )

    assert not report.passed
    assert report.completed_legs == 1
    leg = json.loads((tmp_path / "leg-0001-to-demo_a.json").read_text())
    assert leg["passed"] is False
    assert leg["final_state"]["mission_state"] == "stopped"
    assert leg["final_state"]["stop_latched"] is True
    final_invariants = next(
        check for check in leg["checks"]
        if check["name"] == "final_stop_invariants"
    )
    assert final_invariants["passed"] is True
