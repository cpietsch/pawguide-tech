"""Fail-closed acceptance for a concept lane sealed by an obstacle."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import time
from typing import Any

from pawguide.acceptance import Check, GatewaySession, PoseMonitor
from pawguide.models import Action
from pawguide.secrets import read_secret


@dataclass
class BlockedLaneReport:
    artifact_schema_version: int
    started_at: str
    scenario: str
    gateway_url: str
    visualization_url: str
    expected_outcome: str
    endpoints: dict[str, list[float]]
    protected_corridor: dict[str, Any]
    sealed_barrier: dict[str, Any]
    criteria: dict[str, float | int]
    checks: list[Check] = field(default_factory=list)
    gateway_health: dict[str, Any] | None = None
    gateway_capabilities: dict[str, Any] | None = None
    initial_pose: list[float] | None = None
    planned_path: list[list[float]] = field(default_factory=list)
    trajectory: list[list[float]] = field(default_factory=list)
    navigation_result: dict[str, Any] | None = None
    refusal_mode: str | None = None
    max_displacement_m: float | None = None
    minimum_gate_distance_m: float | None = None
    lane_exit_samples: list[int] = field(default_factory=list)
    barrier_crossing_segments: list[int] = field(default_factory=list)
    navigation_success: bool = False
    expected_safe_refusal: bool = False
    stop_issued_after_s: float | None = None
    bounded_stop_result: dict[str, Any] | None = None
    bounded_stop_state: dict[str, Any] | None = None
    bounded_stop_latched_after_s: float | None = None
    final_state: dict[str, Any] | None = None
    finished_at: str | None = None
    elapsed_s: float | None = None
    passed: bool = False


def _local(
    point: list[float] | tuple[float, float],
    center: tuple[float, float],
    yaw: float,
) -> tuple[float, float]:
    dx, dy = point[0] - center[0], point[1] - center[1]
    cosine, sine = math.cos(yaw), math.sin(yaw)
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def _inside_corridor(
    point: list[float],
    *,
    center: tuple[float, float],
    yaw: float,
    half_extents: tuple[float, float],
    robot_radius_m: float,
) -> bool:
    local_x, local_y = _local(point, center, yaw)
    return (
        abs(local_x) <= half_extents[0] - robot_radius_m
        and abs(local_y) <= half_extents[1] - robot_radius_m
    )


def _segment_hits_box(
    start: list[float],
    end: list[float],
    *,
    center: tuple[float, float],
    yaw: float,
    half_extents: tuple[float, float],
    robot_radius_m: float,
) -> bool:
    distance = math.dist(start[:2], end[:2])
    samples = max(1, math.ceil(distance / 0.01))
    expanded = (
        half_extents[0] + robot_radius_m,
        half_extents[1] + robot_radius_m,
    )
    for index in range(samples + 1):
        fraction = index / samples
        point = [
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        ]
        local_x, local_y = _local(point, center, yaw)
        if abs(local_x) <= expanded[0] and abs(local_y) <= expanded[1]:
            return True
    return False


def _stopped(state: dict[str, Any], *, stale: bool) -> bool:
    return (
        state.get("mission_state") == "stopped"
        and state.get("stop_latched") is True
        and state.get("active_waypoint") is None
        and (not stale or state.get("operator_heartbeat_fresh") is False)
    )


def _wait_stationary_home(
    monitor: PoseMonitor,
    *,
    home: tuple[float, float],
    position_tolerance_m: float,
    stationary_step_m: float,
    samples: int,
    timeout_s: float,
) -> list[float]:
    deadline = time.monotonic() + timeout_s
    last_update = -1
    last_pose: list[float] | None = None
    stable = 0
    while time.monotonic() < deadline:
        pose, updates = monitor.latest()
        if pose is None or updates == last_update:
            time.sleep(0.05)
            continue
        last_update = updates
        step = (
            math.dist(pose[:2], last_pose[:2])
            if last_pose is not None
            else math.inf
        )
        last_pose = pose
        if (
            math.dist(pose[:2], home) <= position_tolerance_m
            and step <= stationary_step_m
        ):
            stable += 1
            if stable >= samples:
                return pose
        else:
            stable = 0
    raise TimeoutError("stationary home pose not observed")


def _wait_final_state(
    gateway: GatewaySession, timeout_s: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest, _ = gateway.request("GET", "/v1/state")
        if (
            _stopped(latest, stale=True)
            and latest.get("last_stop_reason") == "operator_stop"
        ):
            return latest
        time.sleep(0.1)
    return latest


def run_blocked_lane_acceptance(
    *,
    gateway_url: str,
    visualization_url: str,
    token: str,
    endpoints: dict[str, list[float]],
    corridor_center: tuple[float, float],
    corridor_yaw: float,
    corridor_half_extents: tuple[float, float],
    barrier_center: tuple[float, float],
    barrier_yaw: float,
    barrier_half_extents: tuple[float, float],
    robot_radius_m: float,
    observation_timeout_s: float = 5,
    stop_timeout_s: float = 3,
    home_tolerance_m: float = 0.2,
    stationary_step_m: float = 0.02,
    stationary_samples: int = 3,
    maximum_safe_displacement_m: float = 0.3,
    arrival_tolerance_m: float = 0.2,
) -> BlockedLaneReport:
    if sorted(endpoints) != ["demo_gate", "home"]:
        raise ValueError("blocked-lane endpoints must be exactly home and demo_gate")
    if (
        corridor_half_extents[0] <= robot_radius_m
        or corridor_half_extents[1] <= robot_radius_m
    ):
        raise ValueError("protected corridor is too small for the robot radius")
    report = BlockedLaneReport(
        artifact_schema_version=1,
        started_at=datetime.now(UTC).isoformat(),
        scenario="concept_gate_blocked",
        gateway_url=gateway_url,
        visualization_url=visualization_url,
        expected_outcome="safe_refusal_without_arrival",
        endpoints=endpoints,
        protected_corridor={
            "center": list(corridor_center),
            "yaw": corridor_yaw,
            "half_extents": list(corridor_half_extents),
        },
        sealed_barrier={
            "center": list(barrier_center),
            "yaw": barrier_yaw,
            "half_extents": list(barrier_half_extents),
        },
        criteria={
            "robot_radius_m": robot_radius_m,
            "observation_timeout_s": observation_timeout_s,
            "stop_timeout_s": stop_timeout_s,
            "home_tolerance_m": home_tolerance_m,
            "stationary_step_m": stationary_step_m,
            "stationary_samples": stationary_samples,
            "maximum_safe_displacement_m": maximum_safe_displacement_m,
            "arrival_tolerance_m": arrival_tolerance_m,
        },
    )
    started = time.monotonic()
    gateway = GatewaySession(gateway_url, token)
    monitor = PoseMonitor(visualization_url)

    def check(name: str, passed: bool, detail: str) -> None:
        report.checks.append(Check(name, passed, detail))
        if not passed:
            raise RuntimeError(f"{name}: {detail}")

    try:
        report.gateway_health, _ = gateway.request("GET", "/health")
        check(
            "gateway_health",
            report.gateway_health.get("status") == "ok"
            and report.gateway_health.get("adapter") == "dimos_mcp"
            and report.gateway_health.get("motion_capable") is True,
            json.dumps(report.gateway_health, sort_keys=True),
        )
        report.gateway_capabilities, _ = gateway.request(
            "GET", "/v1/capabilities"
        )
        actual_waypoints = sorted(
            report.gateway_capabilities.get("allowed_waypoints", [])
        )
        check(
            "exact_waypoints",
            actual_waypoints == ["demo_gate", "home"],
            f"actual={actual_waypoints}",
        )
        yaw_delta = abs(
            math.atan2(
                math.sin(barrier_yaw - corridor_yaw),
                math.cos(barrier_yaw - corridor_yaw),
            )
        )
        yaw_alignment = min(yaw_delta, abs(math.pi - yaw_delta))
        check(
            "sealed_barrier_geometry",
            yaw_alignment <= 0.05
            and barrier_half_extents[1] + robot_radius_m
            >= corridor_half_extents[1] - robot_radius_m
            and _inside_corridor(
                [barrier_center[0], barrier_center[1]],
                center=corridor_center,
                yaw=corridor_yaw,
                half_extents=corridor_half_extents,
                robot_radius_m=0.0,
            ),
            f"yaw_alignment={yaw_alignment:.3f}rad; "
            f"barrier_cross_half_width="
            f"{barrier_half_extents[1] + robot_radius_m:.3f}m; "
            f"corridor_center_half_width="
            f"{corridor_half_extents[1] - robot_radius_m:.3f}m",
        )
        initial_stop, _ = gateway.command(Action.STOP)
        check(
            "initial_stop",
            initial_stop.get("accepted") is True,
            json.dumps(initial_stop, sort_keys=True),
        )
        initial_state, _ = gateway.request("GET", "/v1/state")
        check(
            "initial_stop_invariants",
            _stopped(initial_state, stale=True),
            json.dumps(initial_state, sort_keys=True),
        )
        monitor.start()
        monitor.wait_for_pose(15)
        report.initial_pose = _wait_stationary_home(
            monitor,
            home=tuple(endpoints["home"][:2]),
            position_tolerance_m=home_tolerance_m,
            stationary_step_m=stationary_step_m,
            samples=stationary_samples,
            timeout_s=15,
        )
        check(
            "stationary_home",
            _inside_corridor(
                report.initial_pose,
                center=corridor_center,
                yaw=corridor_yaw,
                half_extents=corridor_half_extents,
                robot_radius_m=robot_radius_m,
            ),
            json.dumps(report.initial_pose),
        )

        monitor.reset_path()
        gateway.start_heartbeat()
        reset, _ = gateway.command(Action.RESET_STOP)
        check(
            "arm",
            reset.get("accepted") is True
            and reset.get("reason") == "stop_reset",
            json.dumps(reset, sort_keys=True),
        )
        report.navigation_result, _ = gateway.command(
            Action.GO_TO_WAYPOINT, waypoint_id="demo_gate"
        )
        if report.navigation_result.get("accepted") is False:
            report.refusal_mode = "gateway_navigation_rejected"

        observation_started = time.monotonic()
        observation_deadline = observation_started + observation_timeout_s
        autonomous_stop: dict[str, Any] | None = None
        while time.monotonic() < observation_deadline:
            state, _ = gateway.request("GET", "/v1/state")
            if state.get("stop_latched") is True:
                autonomous_stop = state
                report.refusal_mode = "gateway_stop_latched"
                break
            time.sleep(0.1)

        report.planned_path, report.trajectory = monitor.evidence()
        if report.initial_pose is not None and not report.trajectory:
            report.trajectory = [list(report.initial_pose)]
        home = endpoints["home"]
        gate = endpoints["demo_gate"]
        report.max_displacement_m = round(
            max(
                math.dist(point[:2], home[:2])
                for point in report.trajectory
            ),
            3,
        )
        report.minimum_gate_distance_m = round(
            min(
                math.dist(point[:2], gate[:2])
                for point in report.trajectory
            ),
            3,
        )
        report.lane_exit_samples = [
            index
            for index, point in enumerate(report.trajectory)
            if not _inside_corridor(
                point,
                center=corridor_center,
                yaw=corridor_yaw,
                half_extents=corridor_half_extents,
                robot_radius_m=robot_radius_m,
            )
        ]
        report.barrier_crossing_segments = [
            index
            for index, (first, second) in enumerate(
                zip(report.trajectory, report.trajectory[1:])
            )
            if _segment_hits_box(
                first,
                second,
                center=barrier_center,
                yaw=barrier_yaw,
                half_extents=barrier_half_extents,
                robot_radius_m=robot_radius_m,
            )
        ]
        planned_complete = bool(report.planned_path) and math.dist(
            report.planned_path[-1][:2], gate[:2]
        ) <= arrival_tolerance_m
        planned_lane_exits = [
            index
            for index, point in enumerate(report.planned_path)
            if not _inside_corridor(
                point,
                center=corridor_center,
                yaw=corridor_yaw,
                half_extents=corridor_half_extents,
                robot_radius_m=robot_radius_m,
            )
        ]
        planned_barrier_crossings = [
            index
            for index, (first, second) in enumerate(
                zip(report.planned_path, report.planned_path[1:])
            )
            if _segment_hits_box(
                first,
                second,
                center=barrier_center,
                yaw=barrier_yaw,
                half_extents=barrier_half_extents,
                robot_radius_m=robot_radius_m,
            )
        ]
        check(
            "no_complete_planned_route",
            not planned_complete
            and not planned_lane_exits
            and not planned_barrier_crossings,
            f"points={len(report.planned_path)}; complete={planned_complete}; "
            f"lane_exits={planned_lane_exits}; "
            f"barrier_crossings={planned_barrier_crossings}",
        )
        check(
            "bounded_displacement",
            report.max_displacement_m <= maximum_safe_displacement_m,
            f"maximum={report.max_displacement_m}m; "
            f"limit={maximum_safe_displacement_m}m",
        )
        check(
            "protected_lane_containment",
            not report.lane_exit_samples
            and not report.barrier_crossing_segments,
            f"lane_exits={report.lane_exit_samples}; "
            f"barrier_crossings={report.barrier_crossing_segments}",
        )
        report.navigation_success = (
            report.minimum_gate_distance_m <= arrival_tolerance_m
        )
        check(
            "no_arrival_claim",
            not report.navigation_success,
            f"minimum_gate_distance={report.minimum_gate_distance_m}m; "
            f"arrival_tolerance={arrival_tolerance_m}m",
        )

        report.stop_issued_after_s = round(
            time.monotonic() - observation_started, 3
        )
        check(
            "bounded_stop_issue_time",
            report.stop_issued_after_s <= observation_timeout_s + 0.25,
            f"issued_after={report.stop_issued_after_s}s; "
            f"bound={observation_timeout_s}s",
        )
        report.bounded_stop_result, _ = gateway.command(Action.STOP)
        check(
            "bounded_fail_closed_stop",
            report.bounded_stop_result.get("accepted") is True,
            json.dumps(report.bounded_stop_result, sort_keys=True),
        )
        report.bounded_stop_state, _ = gateway.request("GET", "/v1/state")
        report.bounded_stop_latched_after_s = round(
            time.monotonic() - observation_started, 3
        )
        check(
            "bounded_stop_latched",
            _stopped(report.bounded_stop_state, stale=False)
            and report.bounded_stop_latched_after_s
            <= observation_timeout_s + stop_timeout_s,
            f"latched_after={report.bounded_stop_latched_after_s}s; "
            f"deadline={observation_timeout_s + stop_timeout_s}s; "
            f"state={json.dumps(report.bounded_stop_state, sort_keys=True)}",
        )
        if report.refusal_mode is None:
            report.refusal_mode = (
                "operator_bounded_timeout_stop"
                if autonomous_stop is None
                else "gateway_stop_latched"
            )
    except Exception as exc:
        report.checks.append(Check("run_completed", False, str(exc)))
    finally:
        try:
            final_stop, _ = gateway.command(Action.STOP)
            report.checks.append(
                Check(
                    "final_stop",
                    final_stop.get("accepted") is True,
                    json.dumps(final_stop, sort_keys=True),
                )
            )
        except Exception as exc:
            report.checks.append(Check("final_stop", False, str(exc)))
        try:
            gateway.stop_heartbeat()
            report.final_state = _wait_final_state(gateway, stop_timeout_s)
            report.checks.append(
                Check(
                    "final_stop_invariants",
                    _stopped(report.final_state, stale=True)
                    and report.final_state.get("last_stop_reason")
                    == "operator_stop",
                    json.dumps(report.final_state, sort_keys=True),
                )
            )
        except Exception as exc:
            report.checks.append(
                Check("final_stop_invariants", False, str(exc))
            )
        try:
            monitor.close()
        except Exception as exc:
            report.checks.append(Check("monitor_close", False, str(exc)))
        try:
            gateway.close()
        except Exception as exc:
            report.checks.append(Check("gateway_close", False, str(exc)))

    report.elapsed_s = round(time.monotonic() - started, 3)
    report.finished_at = datetime.now(UTC).isoformat()
    report.expected_safe_refusal = (
        report.refusal_mode is not None
        and not report.navigation_success
        and report.bounded_stop_result is not None
        and report.bounded_stop_result.get("accepted") is True
        and report.bounded_stop_state is not None
        and _stopped(report.bounded_stop_state, stale=False)
    )
    report.passed = (
        bool(report.checks)
        and all(item.passed for item in report.checks)
        and report.expected_safe_refusal
        and report.final_state is not None
        and _stopped(report.final_state, stale=True)
        and report.final_state.get("last_stop_reason") == "operator_stop"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove safe refusal when the concept lane is sealed."
    )
    parser.add_argument("--gateway-url", default="http://100.72.30.53:8876")
    parser.add_argument("--visualization-url", default="http://100.102.208.90:7780")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path("config/concept-gate-blocked.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/concept-gate-blocked.json"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    report = run_blocked_lane_acceptance(
        gateway_url=args.gateway_url,
        visualization_url=args.visualization_url,
        token=read_secret("PAWGUIDE_OPERATOR_TOKEN"),
        endpoints=scenario["endpoints"],
        corridor_center=tuple(scenario["protected_corridor"]["center"]),
        corridor_yaw=scenario["protected_corridor"]["yaw"],
        corridor_half_extents=tuple(
            scenario["protected_corridor"]["half_extents"]
        ),
        barrier_center=tuple(scenario["sealed_barrier"]["center"]),
        barrier_yaw=scenario["sealed_barrier"]["yaw"],
        barrier_half_extents=tuple(
            scenario["sealed_barrier"]["half_extents"]
        ),
        robot_radius_m=scenario["robot_radius_m"],
        observation_timeout_s=scenario["observation_timeout_s"],
        stop_timeout_s=scenario["stop_timeout_s"],
        home_tolerance_m=scenario["home_tolerance_m"],
        stationary_step_m=scenario["stationary_step_m"],
        stationary_samples=scenario["stationary_samples"],
        maximum_safe_displacement_m=scenario[
            "maximum_safe_displacement_m"
        ],
        arrival_tolerance_m=scenario["arrival_tolerance_m"],
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
