from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pawguide.failure_matrix_acceptance as matrix


class Backend:
    state: dict[str, Any] = {}
    heartbeat_running = False
    results: dict[str, dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        cls.state = {
            "stop_latched": True,
            "operator_heartbeat_fresh": False,
            "mission_state": "stopped",
            "active_waypoint": None,
            "last_stop_reason": "startup_fail_closed",
        }
        cls.heartbeat_running = False
        cls.results = {}


class FakeApi:
    mutate_duplicate = False

    def __init__(self, _url: str, token: str) -> None:
        self.role = token

    def request(
        self,
        _method: str,
        path: str,
        _payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        if path == "/v1/capabilities":
            return {"operator": 200, "developer": 200}[self.role], {
                "allowed_waypoints": ["home", "demo_gate"]
            }, 10
        if path == "/v1/state":
            if (
                Backend.state["mission_state"] == "navigating"
                and not Backend.heartbeat_running
            ):
                Backend.state.update(
                    stop_latched=True,
                    operator_heartbeat_fresh=False,
                    mission_state="stopped",
                    active_waypoint=None,
                    last_stop_reason="operator_heartbeat_timeout",
                )
            return 200, dict(Backend.state), 10
        raise AssertionError(path)

    def command(
        self,
        action: str,
        *,
        command_id: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        command_id = command_id or f"id-{len(Backend.results)}"
        if action == "raw_velocity":
            return 422, {"detail": "validation error"}, 10
        if action == "reset_stop" and self.role == "developer":
            return 403, {"detail": "Forbidden"}, 10
        if command_id in Backend.results:
            cached = dict(Backend.results[command_id])
            if self.mutate_duplicate:
                cached["reason"] = "duplicate_was_dispatched"
            return 200, cached, 5
        if action == "stop":
            Backend.state.update(
                stop_latched=True,
                mission_state="stopped",
                active_waypoint=None,
                last_stop_reason="operator_stop",
            )
            result = {
                "accepted": True,
                "command_id": command_id,
                "reason": "stop_latched",
                "state": "stopped",
            }
        elif action == "reset_stop":
            if not Backend.heartbeat_running:
                result = {
                    "accepted": False,
                    "command_id": command_id,
                    "reason": "fresh_operator_heartbeat_required",
                    "state": "stopped",
                }
            else:
                Backend.state.update(stop_latched=False, mission_state="idle")
                result = {
                    "accepted": True,
                    "command_id": command_id,
                    "reason": "stop_reset",
                    "state": "idle",
                }
        elif action == "go_to_waypoint":
            waypoint = (arguments or {})["waypoint_id"]
            if waypoint != "home":
                result = {
                    "accepted": False,
                    "command_id": command_id,
                    "reason": "waypoint_not_allowed",
                    "state": "idle",
                }
            else:
                Backend.state.update(
                    mission_state="navigating", active_waypoint="home"
                )
                result = {
                    "accepted": True,
                    "command_id": command_id,
                    "reason": "navigation_started",
                    "state": "navigating",
                }
        else:
            raise AssertionError(action)
        Backend.results[command_id] = dict(result)
        return 200, result, 25

    def close(self) -> None:
        pass


class FakeLease:
    def __init__(
        self, _url: str, _token: str, period_s: float = 0.5
    ) -> None:
        assert period_s == 0.5

    def start(self) -> None:
        Backend.heartbeat_running = True
        Backend.state["operator_heartbeat_fresh"] = True

    def stop(self) -> None:
        Backend.heartbeat_running = False
        Backend.state["operator_heartbeat_fresh"] = False

    @property
    def error(self) -> None:
        return None


def write_soak(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "requested_legs": 50,
                "completed_legs": 50,
                "passed_legs": 50,
            }
        )
    )


def test_live_safe_failure_matrix_passes_and_finishes_stopped(
    monkeypatch, tmp_path: Path
) -> None:
    Backend.reset()
    FakeApi.mutate_duplicate = False
    monkeypatch.setattr(matrix, "FailureApi", FakeApi)
    monkeypatch.setattr(matrix, "HeartbeatLease", FakeLease)
    soak = tmp_path / "soak-report.json"
    write_soak(soak)

    report = matrix.run_failure_matrix(
        gateway_url="http://gateway",
        operator_token="operator",
        developer_token="developer",
        required_waypoints=["home", "demo_gate"],
        heartbeat_test_waypoint="home",
        misspelled_waypoint="demo_gtae",
        heartbeat_timeout_s=0.1,
        no_auto_rearm_s=0,
        final_state_timeout_s=0.1,
        soak_report_path=soak,
    )

    assert report.passed
    assert all(check.passed for check in report.checks)
    assert report.soak_reference is not None
    assert report.soak_reference["requested_legs"] == 50
    assert report.evidence["unknown_waypoint"]["reason"] == "waypoint_not_allowed"
    assert report.evidence["raw_action"]["http_status"] == 422
    assert report.evidence["developer_reset"]["http_status"] == 403
    assert (
        report.evidence["heartbeat_loss"]["state"]["last_stop_reason"]
        == "operator_heartbeat_timeout"
    )
    assert report.final_state == {
        "stop_latched": True,
        "operator_heartbeat_fresh": False,
        "mission_state": "stopped",
        "active_waypoint": None,
        "last_stop_reason": "operator_stop",
    }


def test_duplicate_mismatch_fails_but_final_stop_remains_latched(
    monkeypatch,
) -> None:
    Backend.reset()
    FakeApi.mutate_duplicate = True
    monkeypatch.setattr(matrix, "FailureApi", FakeApi)
    monkeypatch.setattr(matrix, "HeartbeatLease", FakeLease)

    report = matrix.run_failure_matrix(
        gateway_url="http://gateway",
        operator_token="operator",
        developer_token="developer",
        required_waypoints=["home", "demo_gate"],
        heartbeat_test_waypoint="home",
        misspelled_waypoint="demo_gtae",
        heartbeat_timeout_s=0.1,
        no_auto_rearm_s=0,
        final_state_timeout_s=0.1,
    )

    assert not report.passed
    duplicate = next(
        check
        for check in report.checks
        if check.name == "duplicate_uuid_idempotent_result"
    )
    assert not duplicate.passed
    assert report.final_state is not None
    assert report.final_state["stop_latched"] is True
    assert report.final_state["last_stop_reason"] == "operator_stop"
