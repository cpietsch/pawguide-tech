"""End-to-end pre-hardware acceptance runner for the simulated Go2 path."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import statistics
import threading
import time
from typing import Any
from uuid import uuid4

import httpx
import socketio

from pawguide.models import Action
from pawguide.secrets import read_secret


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    elapsed_ms: float | None = None


@dataclass
class AcceptanceReport:
    started_at: str
    gateway_url: str
    visualization_url: str
    waypoint: str
    target_pose: list[float]
    checks: list[Check] = field(default_factory=list)
    gateway_latency_ms: dict[str, float] = field(default_factory=dict)
    initial_pose: list[float] | None = None
    final_pose: list[float] | None = None
    displacement_m: float | None = None
    arrival_error_m: float | None = None
    planned_path: list[list[float]] = field(default_factory=list)
    trajectory: list[list[float]] = field(default_factory=list)
    path_length_m: float | None = None
    path_detour_ratio: float | None = None
    path_max_lateral_m: float | None = None
    final_state: dict[str, Any] | None = None
    finished_at: str | None = None
    passed: bool = False


class PoseMonitor:
    """Capture the latest simulated odometry exposed by the command center."""

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._client = socketio.SimpleClient()
        self._lock = threading.Lock()
        self._latest: list[float] | None = None
        self._trajectory: list[list[float]] = []
        self._path: list[list[float]] = []
        self._updates = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._client.connect(self._url, transports=["websocket"])
        self._thread = threading.Thread(target=self._receive, daemon=True)
        self._thread.start()

    def _receive(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._client.receive(timeout=0.5)
            except (TimeoutError, socketio.exceptions.TimeoutError):
                continue
            except Exception:
                return
            if not event:
                continue
            name, *payload = event
            if name not in {"robot_pose", "full_state", "path"} or not payload:
                continue
            body = payload[0]
            if name == "full_state" and isinstance(body, dict):
                path = body.get("path")
                self._record_path(path)
                body = body.get("robot_pose")
            elif name == "path":
                self._record_path(body)
                continue
            if not isinstance(body, dict):
                continue
            coordinates = body.get("c")
            if (
                isinstance(coordinates, list)
                and len(coordinates) >= 2
                and all(isinstance(value, (int, float)) for value in coordinates[:2])
            ):
                with self._lock:
                    self._latest = [float(value) for value in coordinates]
                    self._trajectory.append(list(self._latest))
                    self._updates += 1

    def _record_path(self, body: Any) -> None:
        if not isinstance(body, dict):
            return
        points = body.get("points")
        if not isinstance(points, list):
            return
        parsed = [
            [float(point[0]), float(point[1])]
            for point in points
            if isinstance(point, list)
            and len(point) >= 2
            and all(isinstance(value, (int, float)) for value in point[:2])
        ]
        if parsed:
            with self._lock:
                # Replanning emits progressively shorter suffixes. Preserve
                # the most complete route for end-to-end obstacle evidence.
                if len(parsed) > len(self._path):
                    self._path = parsed

    def wait_for_pose(self, timeout_s: float) -> list[float]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest is not None:
                    return list(self._latest)
            time.sleep(0.05)
        raise TimeoutError("no robot_pose telemetry received")

    def latest(self) -> tuple[list[float] | None, int]:
        with self._lock:
            return (
                list(self._latest) if self._latest is not None else None,
                self._updates,
            )

    def evidence(self) -> tuple[list[list[float]], list[list[float]]]:
        with self._lock:
            return (
                [list(point) for point in self._path],
                [list(point) for point in self._trajectory],
            )

    def wait_for_path(self, timeout_s: float) -> list[list[float]]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._path:
                    return [list(point) for point in self._path]
            time.sleep(0.05)
        raise TimeoutError("no planned path telemetry received")

    def reset_path(self) -> None:
        with self._lock:
            self._path = []

    def close(self) -> None:
        self._stop.set()
        self._client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=1)


class GatewaySession:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(120, connect=5),
        )
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        response = self._client.request(
            method,
            f"{self._url}{path}",
            json=payload,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"{path} returned a non-object response")
        return body, elapsed_ms

    def command(
        self, action: Action, **arguments: Any
    ) -> tuple[dict[str, Any], float]:
        return self.request(
            "POST",
            "/v1/commands",
            {
                "command_id": str(uuid4()),
                "action": action.value,
                "arguments": arguments,
            },
        )

    def heartbeat(self) -> None:
        response = self._client.post(
            f"{self._url}/v1/heartbeat",
            json={"source": "pre_hardware_acceptance"},
            timeout=3,
        )
        response.raise_for_status()

    def start_heartbeat(self, period_s: float = 0.5) -> None:
        self.heartbeat()

        def loop() -> None:
            while not self._heartbeat_stop.wait(period_s):
                try:
                    self.heartbeat()
                except Exception:
                    # The edge watchdog remains authoritative and will STOP.
                    pass

        self._heartbeat_thread = threading.Thread(target=loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=4)
            if self._heartbeat_thread.is_alive():
                raise RuntimeError("heartbeat request did not terminate within four seconds")

    def close(self) -> None:
        self.stop_heartbeat()
        self._client.close()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _obstacle_local(
    point: tuple[float, float] | list[float],
    center: tuple[float, float],
    yaw: float,
) -> tuple[float, float]:
    dx, dy = point[0] - center[0], point[1] - center[1]
    cosine, sine = math.cos(yaw), math.sin(yaw)
    return cosine * dx + sine * dy, -sine * dx + cosine * dy


def _segment_hits_box(
    start: list[float],
    end: list[float],
    center: tuple[float, float],
    yaw: float,
    half_extents: tuple[float, float],
) -> bool:
    a = _obstacle_local(start, center, yaw)
    b = _obstacle_local(end, center, yaw)
    direction = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for origin, delta, extent in zip(a, direction, half_extents, strict=True):
        if abs(delta) < 1e-9:
            if abs(origin) > extent:
                return False
            continue
        first, second = (-extent - origin) / delta, (extent - origin) / delta
        low = max(low, min(first, second))
        high = min(high, max(first, second))
        if low > high:
            return False
    return True


def _segment_hits_obstacle(
    start: list[float],
    end: list[float],
    center: tuple[float, float],
    yaw: float,
    half_extents: tuple[float, float],
    robot_radius: float,
) -> bool:
    """Test a segment against an oriented box expanded by a circular robot."""
    distance = math.dist(start[:2], end[:2])
    samples = max(1, math.ceil(distance / 0.01))
    for index in range(samples + 1):
        fraction = index / samples
        point = [
            start[0] + (end[0] - start[0]) * fraction,
            start[1] + (end[1] - start[1]) * fraction,
        ]
        local_x, local_y = _obstacle_local(point, center, yaw)
        outside_x = max(abs(local_x) - half_extents[0], 0.0)
        outside_y = max(abs(local_y) - half_extents[1], 0.0)
        if math.hypot(outside_x, outside_y) <= robot_radius:
            return True
    return False


def _path_metrics(
    points: list[list[float]],
    *,
    start: tuple[float, float],
    goal: tuple[float, float],
    obstacle_center: tuple[float, float],
    obstacle_yaw: float,
    obstacle_half_extents: tuple[float, float],
    robot_radius: float,
) -> tuple[float, float, float, list[int]]:
    if len(points) < 2:
        raise ValueError("planned path has fewer than two points")
    if math.dist(points[0][:2], start) > 0.35:
        raise ValueError("planned path does not start near the initial pose")
    if math.dist(points[-1][:2], goal) > 0.20:
        raise ValueError("planned path does not end near the commanded goal")
    length = sum(math.dist(a[:2], b[:2]) for a, b in zip(points, points[1:]))
    direct = math.dist(start, goal)
    lateral = max(
        abs(_obstacle_local(point, obstacle_center, obstacle_yaw)[1])
        for point in points
    )
    collisions = [
        index
        for index, (a, b) in enumerate(zip(points, points[1:]))
        if _segment_hits_obstacle(
            a,
            b,
            obstacle_center,
            obstacle_yaw,
            obstacle_half_extents,
            robot_radius,
        )
    ]
    return length, length / direct, lateral, collisions


def _outside_arena_segments(
    points: list[list[float]],
    bounds: tuple[float, float, float, float],
    inset: float,
) -> list[int]:
    min_x, max_x, min_y, max_y = bounds
    return [
        index
        for index, point in enumerate(points)
        if not (
            min_x + inset <= point[0] <= max_x - inset
            and min_y + inset <= point[1] <= max_y - inset
        )
    ]


def run_acceptance(
    *,
    gateway_url: str,
    visualization_url: str,
    token: str,
    waypoint: str,
    target_pose: tuple[float, float],
    minimum_displacement_m: float = 0.25,
    arrival_tolerance_m: float = 0.20,
    max_gateway_p95_ms: float = 750,
    heartbeat_stop_deadline_s: float = 3.0,
    obstacle_center: tuple[float, float] | None = None,
    obstacle_yaw: float = 0.0,
    obstacle_half_extents: tuple[float, float] = (0.0, 0.0),
    robot_radius_m: float = 0.0,
    planning_grid_tolerance_m: float = 0.0,
    minimum_path_detour_ratio: float = 1.0,
    minimum_path_lateral_m: float = 0.0,
    arena_bounds: tuple[float, float, float, float] | None = None,
) -> AcceptanceReport:
    report = AcceptanceReport(
        started_at=datetime.now(UTC).isoformat(),
        gateway_url=gateway_url,
        visualization_url=visualization_url,
        waypoint=waypoint,
        target_pose=list(target_pose),
    )
    gateway = GatewaySession(gateway_url, token)
    poses = PoseMonitor(visualization_url)

    def check(name: str, passed: bool, detail: str, elapsed: float | None = None) -> None:
        report.checks.append(Check(name, passed, detail, elapsed))
        if not passed:
            raise RuntimeError(f"{name}: {detail}")

    try:
        # Exclude connection/tunnel cold-start from the steady-state latency
        # gate while still requiring the warm-up request to succeed.
        warmup_health, _ = gateway.request("GET", "/health")
        check(
            "gateway_warmup",
            warmup_health.get("status") == "ok",
            json.dumps(warmup_health, sort_keys=True),
        )
        health_times: list[float] = []
        for _ in range(20):
            health, elapsed = gateway.request("GET", "/health")
            health_times.append(elapsed)
            check(
                "gateway_health",
                health.get("status") == "ok"
                and health.get("adapter") == "dimos_mcp"
                and health.get("motion_capable") is True,
                json.dumps(health, sort_keys=True),
                elapsed,
            )
        report.gateway_latency_ms = {
            "median": round(statistics.median(health_times), 2),
            "p95": round(_percentile(health_times, 0.95), 2),
            "max": round(max(health_times), 2),
        }
        check(
            "gateway_latency",
            report.gateway_latency_ms["p95"] <= max_gateway_p95_ms,
            f"p95={report.gateway_latency_ms['p95']}ms "
            f"limit={max_gateway_p95_ms}ms",
        )

        capabilities, elapsed = gateway.request("GET", "/v1/capabilities")
        check(
            "waypoint_allowlisted",
            waypoint in capabilities.get("allowed_waypoints", []),
            f"{waypoint=} allowed={capabilities.get('allowed_waypoints')}",
            elapsed,
        )

        stop_result, elapsed = gateway.command(Action.STOP)
        check(
            "initial_stop",
            stop_result.get("accepted") is True,
            json.dumps(stop_result, sort_keys=True),
            elapsed,
        )

        poses.start()
        report.initial_pose = poses.wait_for_pose(15)
        check("pose_stream", True, f"initial_pose={report.initial_pose}")

        gateway.start_heartbeat()
        reset, elapsed = gateway.command(Action.RESET_STOP)
        check(
            "arm",
            reset.get("accepted") is True and reset.get("state") == "idle",
            json.dumps(reset, sort_keys=True),
            elapsed,
        )

        navigation, elapsed = gateway.command(
            Action.GO_TO_WAYPOINT,
            waypoint_id=waypoint,
        )
        check(
            "navigation_dispatch",
            navigation.get("accepted") is True
            and navigation.get("state") == "navigating",
            json.dumps(navigation, sort_keys=True),
            elapsed,
        )
        planned_path = poses.wait_for_path(10)
        check(
            "navigation_map_ready",
            len(planned_path) >= 2,
            f"planned_points={len(planned_path)}",
        )

        deadline = time.monotonic() + 90
        initial_updates = poses.latest()[1]
        while time.monotonic() < deadline:
            current, updates = poses.latest()
            if current is not None and report.initial_pose is not None:
                displacement = math.dist(current[:2], report.initial_pose[:2])
                arrival_error = math.dist(current[:2], target_pose)
                if (
                    displacement >= minimum_displacement_m
                    and arrival_error <= arrival_tolerance_m
                ):
                    report.final_pose = current
                    report.displacement_m = round(displacement, 3)
                    report.arrival_error_m = round(arrival_error, 3)
                    break
            if updates == initial_updates:
                time.sleep(0.1)
            else:
                time.sleep(0.25)
        check(
            "waypoint_arrival",
            report.displacement_m is not None
            and report.arrival_error_m is not None,
            f"displacement={report.displacement_m}m minimum={minimum_displacement_m}m; "
            f"arrival_error={report.arrival_error_m}m "
            f"tolerance={arrival_tolerance_m}m",
        )

        report.planned_path, report.trajectory = poses.evidence()
        if obstacle_center is not None:
            assert report.initial_pose is not None
            length, ratio, lateral, path_collisions = _path_metrics(
                report.planned_path,
                start=tuple(report.initial_pose[:2]),
                goal=target_pose,
                obstacle_center=obstacle_center,
                obstacle_yaw=obstacle_yaw,
                obstacle_half_extents=obstacle_half_extents,
                robot_radius=max(
                    0.0, robot_radius_m - planning_grid_tolerance_m
                ),
            )
            report.path_length_m = round(length, 3)
            report.path_detour_ratio = round(ratio, 3)
            report.path_max_lateral_m = round(lateral, 3)
            check(
                "planned_path_collision_free",
                not path_collisions,
                f"robot_radius={robot_radius_m}; "
                f"grid_tolerance={planning_grid_tolerance_m}; "
                f"collision_segments={path_collisions}",
            )
            check(
                "planned_path_detour",
                ratio >= minimum_path_detour_ratio
                and lateral >= minimum_path_lateral_m,
                f"length={length:.3f}m ratio={ratio:.3f} "
                f"minimum_ratio={minimum_path_detour_ratio}; "
                f"lateral={lateral:.3f}m minimum={minimum_path_lateral_m}m",
            )
            trajectory_collisions = [
                index
                for index, (a, b) in enumerate(
                    zip(report.trajectory, report.trajectory[1:])
                )
                if _segment_hits_obstacle(
                    a,
                    b,
                    obstacle_center,
                    obstacle_yaw,
                    obstacle_half_extents,
                    robot_radius_m,
                )
            ]
            check(
                "trajectory_collision_free",
                len(report.trajectory) >= 3 and not trajectory_collisions,
                f"samples={len(report.trajectory)}; "
                f"collision_segments={trajectory_collisions}",
            )
            if arena_bounds is not None:
                path_outside = _outside_arena_segments(
                    report.planned_path,
                    arena_bounds,
                    max(0.0, robot_radius_m - planning_grid_tolerance_m),
                )
                trajectory_outside = _outside_arena_segments(
                    report.trajectory,
                    arena_bounds,
                    robot_radius_m,
                )
                check(
                    "planned_path_inside_lane",
                    not path_outside,
                    f"bounds={arena_bounds}; outside_points={path_outside}",
                )
                check(
                    "trajectory_inside_lane",
                    not trajectory_outside,
                    f"bounds={arena_bounds}; outside_samples={trajectory_outside}",
                )

        # Prove the edge watchdog, independently of an explicit STOP request.
        gateway.stop_heartbeat()
        deadline = time.monotonic() + heartbeat_stop_deadline_s
        watchdog_state: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            watchdog_state, _ = gateway.request("GET", "/v1/state")
            if (
                watchdog_state.get("stop_latched") is True
                and watchdog_state.get("last_stop_reason")
                == "operator_heartbeat_timeout"
            ):
                break
            time.sleep(0.1)
        check(
            "heartbeat_loss_stop",
            watchdog_state is not None
            and watchdog_state.get("stop_latched") is True
            and watchdog_state.get("last_stop_reason")
            == "operator_heartbeat_timeout",
            json.dumps(watchdog_state, sort_keys=True),
        )
    except Exception as exc:
        report.checks.append(Check("run_completed", False, str(exc)))
    finally:
        try:
            final_stop, elapsed = gateway.command(Action.STOP)
            report.checks.append(
                Check(
                    "final_stop",
                    final_stop.get("accepted") is True,
                    json.dumps(final_stop, sort_keys=True),
                    elapsed,
                )
            )
            report.final_state, _ = gateway.request("GET", "/v1/state")
            final_invariants = (
                report.final_state.get("stop_latched") is True
                and report.final_state.get("mission_state") == "stopped"
                and report.final_state.get("active_waypoint") is None
                and report.final_state.get("operator_heartbeat_fresh") is False
                and report.final_state.get("last_stop_reason") == "operator_stop"
            )
            report.checks.append(
                Check(
                    "final_stop_invariants",
                    final_invariants,
                    json.dumps(report.final_state, sort_keys=True),
                )
            )
        except Exception as exc:
            report.checks.append(Check("final_stop", False, str(exc)))
        poses.close()
        gateway.close()

    report.finished_at = datetime.now(UTC).isoformat()
    report.passed = (
        bool(report.checks)
        and all(item.passed for item in report.checks)
        and report.final_state is not None
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the PawGuide simulated pre-hardware acceptance gate."
    )
    parser.add_argument("--gateway-url", default="http://100.72.30.53:8876")
    parser.add_argument("--visualization-url", default="http://100.102.208.90:7780")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path("config/simulation-acceptance.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/pre-hardware-acceptance.json"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    token = read_secret("PAWGUIDE_OPERATOR_TOKEN")
    report = run_acceptance(
        gateway_url=args.gateway_url,
        visualization_url=args.visualization_url,
        token=token,
        waypoint=scenario["waypoint"],
        target_pose=tuple(scenario["target_pose"][:2]),
        minimum_displacement_m=scenario["minimum_displacement_m"],
        arrival_tolerance_m=scenario["arrival_tolerance_m"],
        max_gateway_p95_ms=scenario["max_gateway_p95_ms"],
        heartbeat_stop_deadline_s=scenario["heartbeat_stop_deadline_s"],
        obstacle_center=tuple(scenario["obstacle"]["center"]),
        obstacle_yaw=scenario["obstacle"]["yaw"],
        obstacle_half_extents=tuple(scenario["obstacle"]["half_extents"]),
        robot_radius_m=scenario["obstacle"]["robot_radius_m"],
        planning_grid_tolerance_m=scenario["obstacle"]["planning_grid_tolerance_m"],
        minimum_path_detour_ratio=scenario["minimum_path_detour_ratio"],
        minimum_path_lateral_m=scenario["minimum_path_lateral_m"],
        arena_bounds=tuple(scenario["arena_bounds"]),
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
