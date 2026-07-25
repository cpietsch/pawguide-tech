import json
from pathlib import Path

from pawguide.concept_suite import build_suite


SAFE = {
    "stop_latched": True,
    "operator_heartbeat_fresh": False,
    "mission_state": "stopped",
    "active_waypoint": None,
    "last_stop_reason": "operator_stop",
}


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_suite_passes_only_with_all_simulation_gates_and_keeps_physical_pending(
    tmp_path: Path,
) -> None:
    report = build_suite(
        show_path=_write(
            tmp_path / "show.json",
            {
                "passed": True,
                "started_at": "2026-07-25T00:00:00Z",
                "show_elapsed_s": 66.1,
                "final_state": SAFE,
                "outbound_path_exit_segments": [],
                "outbound_trajectory_exit_segments": [],
                "return_path_exit_segments": [],
                "return_trajectory_exit_segments": [],
            },
        ),
        blocked_path=_write(
            tmp_path / "blocked.json",
            {
                "passed": True,
                "expected_safe_refusal": True,
                "navigation_success": False,
                "lane_exit_samples": [],
                "barrier_crossing_segments": [],
                "max_displacement_m": 0.003,
                "final_state": SAFE,
            },
        ),
        failure_path=_write(
            tmp_path / "failure.json",
            {
                "passed": True,
                "evidence": {"heartbeat_loss": {"elapsed_s": 1.6}},
                "final_state": SAFE,
            },
        ),
        soak_path=_write(
            tmp_path / "soak.json",
            {
                "passed": True,
                "requested_legs": 50,
                "completed_legs": 50,
                "passed_legs": 50,
                "final_state": SAFE,
            },
        ),
        visualization_url="http://viewer",
    )

    assert report["passed"] is True
    assert report["completed_steps"] == report["requested_steps"] == 4
    assert all(item["status"] == "passed" for item in report["sequence"])
    assert all(
        item["status"] == "pending_physical_hardware"
        for item in report["physical_gates"]
    )


def test_suite_fails_when_route_left_protected_corridor(tmp_path: Path) -> None:
    safe_show = {
        "passed": True,
        "started_at": "2026-07-25T00:00:00Z",
        "show_elapsed_s": 66.1,
        "final_state": SAFE,
        "outbound_path_exit_segments": [3],
        "outbound_trajectory_exit_segments": [],
        "return_path_exit_segments": [],
        "return_trajectory_exit_segments": [],
    }
    report = build_suite(
        show_path=_write(tmp_path / "show.json", safe_show),
        blocked_path=_write(
            tmp_path / "blocked.json",
            {
                "passed": True,
                "expected_safe_refusal": True,
                "navigation_success": False,
                "lane_exit_samples": [],
                "barrier_crossing_segments": [],
                "final_state": SAFE,
            },
        ),
        failure_path=_write(
            tmp_path / "failure.json",
            {"passed": True, "final_state": SAFE},
        ),
        soak_path=_write(
            tmp_path / "soak.json",
            {
                "passed": True,
                "requested_legs": 50,
                "completed_legs": 50,
                "passed_legs": 50,
                "final_state": SAFE,
            },
        ),
        visualization_url="http://viewer",
    )

    assert report["passed"] is False
    assert next(item for item in report["sequence"] if item["id"] == "show")[
        "status"
    ] == "failed"
