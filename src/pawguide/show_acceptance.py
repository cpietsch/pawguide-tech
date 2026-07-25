"""Concept-level, operator-confirmed acceptance for the complete showcase."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import threading
import time
from typing import Any

import socketio

from pawguide.acceptance import Check, GatewaySession
from pawguide.models import Action
from pawguide.secrets import read_secret


@dataclass
class PoseSample:
    position: list[float]
    orientation: list[float] | None
    sequence: int
    observed_at: str


@dataclass
class Confirmation:
    stage: str
    operator: str
    confirmed_at: str
    pose: PoseSample | None


@dataclass
class ShowAcceptanceReport:
    artifact_schema_version: int
    started_at: str
    gateway_url: str
    visualization_url: str
    required_waypoints: list[str]
    expected_endpoints: dict[str, dict[str, list[float]]]
    criteria: dict[str, float | int]
    gateway_health: dict[str, Any] | None = None
    gateway_capabilities: dict[str, Any] | None = None
    checks: list[Check] = field(default_factory=list)
    confirmations: list[Confirmation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gate_pose: PoseSample | None = None
    home_pose: PoseSample | None = None
    outbound_path: list[list[float]] = field(default_factory=list)
    outbound_trajectory: list[list[float]] = field(default_factory=list)
    outbound_path_exit_segments: list[int] = field(default_factory=list)
    outbound_trajectory_exit_segments: list[int] = field(default_factory=list)
    return_path: list[list[float]] = field(default_factory=list)
    return_trajectory: list[list[float]] = field(default_factory=list)
    return_path_exit_segments: list[int] = field(default_factory=list)
    return_trajectory_exit_segments: list[int] = field(default_factory=list)
    show_started_at: str | None = None
    show_finished_at: str | None = None
    show_elapsed_s: float | None = None
    final_state: dict[str, Any] | None = None
    finished_at: str | None = None
    passed: bool = False


class ShowPoseMonitor:
    """Capture position and optional orientation from command-center telemetry."""

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._client = socketio.SimpleClient()
        self._lock = threading.Lock()
        self._latest: PoseSample | None = None
        self._path: list[list[float]] = []
        self._trajectory: list[list[float]] = []
        self._sequence = 0
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
                self._record_path(body.get("path"))
                body = body.get("robot_pose")
            elif name == "path":
                self._record_path(body)
                continue
            if not isinstance(body, dict):
                continue
            coordinates = body.get("c")
            if (
                not isinstance(coordinates, list)
                or len(coordinates) < 2
                or not all(
                    isinstance(value, (int, float)) for value in coordinates[:2]
                )
            ):
                continue
            raw_orientation = body.get("q", body.get("orientation"))
            orientation = (
                [float(value) for value in raw_orientation]
                if isinstance(raw_orientation, list)
                and len(raw_orientation) == 4
                and all(
                    isinstance(value, (int, float))
                    for value in raw_orientation
                )
                else None
            )
            with self._lock:
                self._sequence += 1
                self._latest = PoseSample(
                    position=[float(value) for value in coordinates],
                    orientation=orientation,
                    sequence=self._sequence,
                    observed_at=datetime.now(UTC).isoformat(),
                )
                self._trajectory.append(list(self._latest.position))

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
            and all(
                isinstance(value, (int, float)) for value in point[:2]
            )
        ]
        if parsed:
            with self._lock:
                if len(parsed) > len(self._path):
                    self._path = parsed

    def latest(self) -> PoseSample | None:
        with self._lock:
            if self._latest is None:
                return None
            return PoseSample(**asdict(self._latest))

    def wait_for_pose(self, timeout_s: float) -> PoseSample:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sample = self.latest()
            if sample is not None:
                return sample
            time.sleep(0.05)
        raise TimeoutError("no robot_pose telemetry received")

    def reset_route_evidence(self) -> None:
        with self._lock:
            self._path = []
            self._trajectory = []

    def wait_for_path(self, timeout_s: float) -> list[list[float]]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._path:
                    return [list(point) for point in self._path]
            time.sleep(0.05)
        raise TimeoutError("no fresh planned path telemetry received")

    def route_evidence(self) -> tuple[list[list[float]], list[list[float]]]:
        with self._lock:
            return (
                [list(point) for point in self._path],
                [list(point) for point in self._trajectory],
            )

    def close(self) -> None:
        self._stop.set()
        self._client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=1)


def _stopped(state: dict[str, Any], *, require_stale: bool) -> bool:
    return (
        state.get("mission_state") == "stopped"
        and state.get("stop_latched") is True
        and state.get("active_waypoint") is None
        and (
            not require_stale
            or state.get("operator_heartbeat_fresh") is False
        )
    )


def _quaternion_error(
    actual: list[float], expected: list[float]
) -> float:
    actual_norm = math.sqrt(sum(value * value for value in actual))
    expected_norm = math.sqrt(sum(value * value for value in expected))
    if actual_norm < 1e-9 or expected_norm < 1e-9:
        raise ValueError("orientation quaternion has zero magnitude")
    dot = sum(a * b for a, b in zip(actual, expected, strict=True))
    cosine = min(1.0, abs(dot / (actual_norm * expected_norm)))
    return 2 * math.acos(cosine)


def _wait_stationary_at(
    monitor: ShowPoseMonitor,
    *,
    target_position: tuple[float, float],
    target_orientation: list[float] | None,
    position_tolerance_m: float,
    orientation_tolerance_rad: float,
    stationary_step_m: float,
    stationary_dwell_s: float,
    minimum_samples: int,
    timeout_s: float,
) -> tuple[PoseSample, float | None]:
    deadline = time.monotonic() + timeout_s
    last_sequence = -1
    last_position: list[float] | None = None
    stable_since: float | None = None
    stable_samples = 0
    latest: PoseSample | None = None
    orientation_error: float | None = None
    while time.monotonic() < deadline:
        sample = monitor.latest()
        if sample is None or sample.sequence == last_sequence:
            time.sleep(0.05)
            continue
        last_sequence = sample.sequence
        latest = sample
        position_error = math.dist(sample.position[:2], target_position)
        step = (
            math.dist(sample.position[:2], last_position[:2])
            if last_position is not None
            else math.inf
        )
        last_position = sample.position
        orientation_error = (
            _quaternion_error(sample.orientation, target_orientation)
            if sample.orientation is not None
            and target_orientation is not None
            else None
        )
        orientation_ok = (
            orientation_error is None
            or orientation_error <= orientation_tolerance_rad
        )
        if (
            position_error <= position_tolerance_m
            and step <= stationary_step_m
            and orientation_ok
        ):
            if stable_since is None:
                stable_since = time.monotonic()
                stable_samples = 1
            else:
                stable_samples += 1
            if (
                stable_samples >= minimum_samples
                and time.monotonic() - stable_since >= stationary_dwell_s
            ):
                return sample, orientation_error
        else:
            stable_since = None
            stable_samples = 0
    raise TimeoutError(f"stationary target dwell not observed; latest={latest}")


def _wait_final_state(
    gateway: GatewaySession, timeout_s: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest, _ = gateway.request("GET", "/v1/state")
        if _stopped(latest, require_stale=True):
            return latest
        time.sleep(0.1)
    return latest


def _corridor_exit_segments(
    points: list[list[float]],
    *,
    home: tuple[float, float],
    gate: tuple[float, float],
    half_width_m: float,
    longitudinal_margin_m: float,
) -> list[int]:
    dx, dy = gate[0] - home[0], gate[1] - home[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ValueError("home and demo_gate must not coincide")
    unit_x, unit_y = dx / length, dy / length

    def inside(point: list[float]) -> bool:
        relative_x, relative_y = point[0] - home[0], point[1] - home[1]
        along = relative_x * unit_x + relative_y * unit_y
        lateral = abs(-relative_x * unit_y + relative_y * unit_x)
        return (
            -longitudinal_margin_m
            <= along
            <= length + longitudinal_margin_m
            and lateral <= half_width_m
        )

    return [
        index
        for index, (first, second) in enumerate(zip(points, points[1:]))
        if not inside(first) or not inside(second)
    ]


def run_show_acceptance(
    *,
    gateway_url: str,
    visualization_url: str,
    token: str,
    endpoints: dict[str, dict[str, list[float]]],
    confirm: Callable[[str, PoseSample | None], str],
    position_tolerance_m: float = 0.2,
    orientation_tolerance_rad: float = 0.25,
    stationary_step_m: float = 0.02,
    stationary_dwell_s: float = 1.0,
    stationary_samples: int = 3,
    arrival_timeout_s: float = 40,
    final_stop_timeout_s: float = 3,
    max_show_duration_s: float = 120,
    minimum_route_distance_m: float = 4.5,
    maximum_route_distance_m: float = 5.5,
    protected_corridor_half_width_m: float = 0.3,
    protected_corridor_longitudinal_margin_m: float = 0.2,
    path_timeout_s: float = 5,
) -> ShowAcceptanceReport:
    required = ["demo_gate", "home"]
    if sorted(endpoints) != required:
        raise ValueError("show endpoints must be exactly home and demo_gate")
    report = ShowAcceptanceReport(
        artifact_schema_version=1,
        started_at=datetime.now(UTC).isoformat(),
        gateway_url=gateway_url,
        visualization_url=visualization_url,
        required_waypoints=required,
        expected_endpoints=endpoints,
        criteria={
            "position_tolerance_m": position_tolerance_m,
            "orientation_tolerance_rad": orientation_tolerance_rad,
            "stationary_step_m": stationary_step_m,
            "stationary_dwell_s": stationary_dwell_s,
            "stationary_samples": stationary_samples,
            "arrival_timeout_s": arrival_timeout_s,
            "final_stop_timeout_s": final_stop_timeout_s,
            "max_show_duration_s": max_show_duration_s,
            "minimum_route_distance_m": minimum_route_distance_m,
            "maximum_route_distance_m": maximum_route_distance_m,
            "protected_corridor_half_width_m":
                protected_corridor_half_width_m,
            "protected_corridor_longitudinal_margin_m":
                protected_corridor_longitudinal_margin_m,
            "path_timeout_s": path_timeout_s,
        },
    )
    gateway = GatewaySession(gateway_url, token)
    monitor = ShowPoseMonitor(visualization_url)
    show_started: float | None = None

    def check(
        name: str, passed: bool, detail: str, elapsed_ms: float | None = None
    ) -> None:
        report.checks.append(Check(name, passed, detail, elapsed_ms))
        if not passed:
            raise RuntimeError(f"{name}: {detail}")

    def command(action: Action, reason: str, **arguments: Any) -> None:
        result, elapsed = gateway.command(action, **arguments)
        check(
            action.value,
            result.get("accepted") is True and result.get("reason") == reason,
            json.dumps(result, sort_keys=True),
            elapsed,
        )

    def confirmation(stage: str, pose: PoseSample | None) -> None:
        operator = confirm(stage, pose).strip()
        check(
            f"operator_confirmation_{stage}",
            bool(operator),
            f"operator={operator or '(missing)'}",
        )
        report.confirmations.append(
            Confirmation(
                stage=stage,
                operator=operator,
                confirmed_at=datetime.now(UTC).isoformat(),
                pose=pose,
            )
        )

    try:
        health, elapsed = gateway.request("GET", "/health")
        report.gateway_health = health
        check(
            "gateway_health",
            health.get("status") == "ok"
            and health.get("adapter") == "dimos_mcp"
            and health.get("motion_capable") is True,
            json.dumps(health, sort_keys=True),
            elapsed,
        )
        capabilities, elapsed = gateway.request("GET", "/v1/capabilities")
        report.gateway_capabilities = capabilities
        actual_waypoints = sorted(capabilities.get("allowed_waypoints", []))
        check(
            "exact_waypoints",
            actual_waypoints == required,
            f"required={required}; actual={actual_waypoints}",
            elapsed,
        )
        route_distance = math.dist(
            endpoints["home"]["position"][:2],
            endpoints["demo_gate"]["position"][:2],
        )
        check(
            "route_distance",
            minimum_route_distance_m
            <= route_distance
            <= maximum_route_distance_m,
            f"distance={route_distance:.3f}m; required="
            f"{minimum_route_distance_m}..{maximum_route_distance_m}m",
        )
        command(Action.STOP, "stop_latched")
        initial_state, _ = gateway.request("GET", "/v1/state")
        check(
            "initial_stop_invariants",
            _stopped(initial_state, require_stale=True),
            json.dumps(initial_state, sort_keys=True),
        )
        monitor.start()
        monitor.wait_for_pose(15)
        home = endpoints["home"]
        initial_home, home_orientation_error = _wait_stationary_at(
            monitor,
            target_position=tuple(home["position"][:2]),
            target_orientation=home.get("orientation"),
            position_tolerance_m=position_tolerance_m,
            orientation_tolerance_rad=orientation_tolerance_rad,
            stationary_step_m=stationary_step_m,
            stationary_dwell_s=stationary_dwell_s,
            minimum_samples=stationary_samples,
            timeout_s=15,
        )
        check("initial_home_stationary", True, json.dumps(asdict(initial_home)))
        if home_orientation_error is None:
            report.warnings.append("home orientation is not observable")
        else:
            check(
                "initial_home_orientation",
                home_orientation_error <= orientation_tolerance_rad,
                f"error={home_orientation_error:.3f}rad",
            )
        confirmation("activation_ready", initial_home)

        show_started = time.monotonic()
        report.show_started_at = datetime.now(UTC).isoformat()
        gateway.start_heartbeat()
        command(Action.RESET_STOP, "stop_reset")
        command(Action.STAND_UP, "stand_up_sent")
        command(Action.GREETING, "greeting_sent")
        confirmation("greeting_complete", monitor.latest())
        monitor.reset_route_evidence()
        command(
            Action.GO_TO_WAYPOINT,
            "navigation_started",
            waypoint_id="demo_gate",
        )
        report.outbound_path = monitor.wait_for_path(path_timeout_s)
        gate = endpoints["demo_gate"]
        report.gate_pose, gate_orientation_error = _wait_stationary_at(
            monitor,
            target_position=tuple(gate["position"][:2]),
            target_orientation=gate.get("orientation"),
            position_tolerance_m=position_tolerance_m,
            orientation_tolerance_rad=orientation_tolerance_rad,
            stationary_step_m=stationary_step_m,
            stationary_dwell_s=stationary_dwell_s,
            minimum_samples=stationary_samples,
            timeout_s=arrival_timeout_s,
        )
        check("gate_stationary_arrival", True, json.dumps(asdict(report.gate_pose)))
        report.outbound_path, report.outbound_trajectory = (
            monitor.route_evidence()
        )
        home_xy = tuple(home["position"][:2])
        gate_xy = tuple(gate["position"][:2])
        report.outbound_path_exit_segments = _corridor_exit_segments(
            report.outbound_path,
            home=home_xy,
            gate=gate_xy,
            half_width_m=protected_corridor_half_width_m,
            longitudinal_margin_m=protected_corridor_longitudinal_margin_m,
        )
        report.outbound_trajectory_exit_segments = _corridor_exit_segments(
            report.outbound_trajectory,
            home=home_xy,
            gate=gate_xy,
            half_width_m=protected_corridor_half_width_m,
            longitudinal_margin_m=protected_corridor_longitudinal_margin_m,
        )
        check(
            "outbound_protected_corridor",
            len(report.outbound_path) >= 2
            and len(report.outbound_trajectory) >= stationary_samples
            and not report.outbound_path_exit_segments
            and not report.outbound_trajectory_exit_segments,
            f"path_points={len(report.outbound_path)}; "
            f"trajectory_points={len(report.outbound_trajectory)}; "
            f"path_exit_segments={report.outbound_path_exit_segments}; "
            f"trajectory_exit_segments="
            f"{report.outbound_trajectory_exit_segments}",
        )
        if gate_orientation_error is None:
            report.warnings.append("demo_gate orientation is not observable")
        else:
            check(
                "gate_orientation",
                gate_orientation_error <= orientation_tolerance_rad,
                f"error={gate_orientation_error:.3f}rad",
            )
        confirmation("gate_arrived", report.gate_pose)
        command(Action.PAUSE, "mission_paused")
        command(Action.GREETING, "greeting_sent")
        confirmation("farewell_complete", monitor.latest())
        monitor.reset_route_evidence()
        command(Action.RETURN_HOME, "returning_home")
        report.return_path = monitor.wait_for_path(path_timeout_s)
        report.home_pose, return_orientation_error = _wait_stationary_at(
            monitor,
            target_position=tuple(home["position"][:2]),
            target_orientation=home.get("orientation"),
            position_tolerance_m=position_tolerance_m,
            orientation_tolerance_rad=orientation_tolerance_rad,
            stationary_step_m=stationary_step_m,
            stationary_dwell_s=stationary_dwell_s,
            minimum_samples=stationary_samples,
            timeout_s=arrival_timeout_s,
        )
        check("home_stationary_arrival", True, json.dumps(asdict(report.home_pose)))
        report.return_path, report.return_trajectory = (
            monitor.route_evidence()
        )
        report.return_path_exit_segments = _corridor_exit_segments(
            report.return_path,
            home=home_xy,
            gate=gate_xy,
            half_width_m=protected_corridor_half_width_m,
            longitudinal_margin_m=protected_corridor_longitudinal_margin_m,
        )
        report.return_trajectory_exit_segments = _corridor_exit_segments(
            report.return_trajectory,
            home=home_xy,
            gate=gate_xy,
            half_width_m=protected_corridor_half_width_m,
            longitudinal_margin_m=protected_corridor_longitudinal_margin_m,
        )
        check(
            "return_protected_corridor",
            len(report.return_path) >= 2
            and len(report.return_trajectory) >= stationary_samples
            and not report.return_path_exit_segments
            and not report.return_trajectory_exit_segments,
            f"path_points={len(report.return_path)}; "
            f"trajectory_points={len(report.return_trajectory)}; "
            f"path_exit_segments={report.return_path_exit_segments}; "
            f"trajectory_exit_segments="
            f"{report.return_trajectory_exit_segments}",
        )
        if return_orientation_error is None:
            report.warnings.append("return-home orientation is not observable")
        else:
            check(
                "return_home_orientation",
                return_orientation_error <= orientation_tolerance_rad,
                f"error={return_orientation_error:.3f}rad",
            )
        confirmation("home_arrived", report.home_pose)
        command(Action.PAUSE, "mission_paused")
        command(Action.SIT_DOWN, "sit_down_sent")
        confirmation("sitting_complete", monitor.latest())
    except Exception as exc:
        report.checks.append(Check("run_completed", False, str(exc)))
    finally:
        try:
            final_stop, elapsed = gateway.command(Action.STOP)
            report.checks.append(
                Check(
                    "final_stop",
                    final_stop.get("accepted") is True
                    and final_stop.get("reason") == "stop_latched",
                    json.dumps(final_stop, sort_keys=True),
                    elapsed,
                )
            )
        except Exception as exc:
            report.checks.append(Check("final_stop", False, str(exc)))
        try:
            gateway.stop_heartbeat()
            report.final_state = _wait_final_state(
                gateway, final_stop_timeout_s
            )
            report.checks.append(
                Check(
                    "final_stop_invariants",
                    _stopped(report.final_state, require_stale=True)
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

    if show_started is not None:
        report.show_finished_at = datetime.now(UTC).isoformat()
        report.show_elapsed_s = round(time.monotonic() - show_started, 3)
        report.checks.append(
            Check(
                "show_duration",
                report.show_elapsed_s <= max_show_duration_s,
                f"elapsed={report.show_elapsed_s}s limit={max_show_duration_s}s",
            )
        )
    report.finished_at = datetime.now(UTC).isoformat()
    required_confirmations = {
        "activation_ready",
        "greeting_complete",
        "gate_arrived",
        "farewell_complete",
        "home_arrived",
        "sitting_complete",
    }
    report.passed = (
        bool(report.checks)
        and all(item.passed for item in report.checks)
        and {item.stage for item in report.confirmations}
        == required_confirmations
        and report.final_state is not None
        and _stopped(report.final_state, require_stale=True)
        and report.show_elapsed_s is not None
        and report.show_elapsed_s <= max_show_duration_s
    )
    return report


class InteractiveConfirmer:
    def __init__(self, operator: str) -> None:
        self._operator = operator

    def __call__(self, stage: str, pose: PoseSample | None) -> str:
        prompt = f"Type CONFIRM {stage} after visually verifying completion: "
        if input(prompt).strip() != f"CONFIRM {stage}":
            raise RuntimeError(f"operator did not confirm {stage}")
        return self._operator


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the complete operator-confirmed PawGuide show gate."
    )
    parser.add_argument("--gateway-url", default="http://100.72.30.53:8876")
    parser.add_argument("--visualization-url", default="http://100.102.208.90:7780")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path("config/concept-show-acceptance.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/concept-show-acceptance.json"),
    )
    parser.add_argument("--operator", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    report = run_show_acceptance(
        gateway_url=args.gateway_url,
        visualization_url=args.visualization_url,
        token=read_secret("PAWGUIDE_OPERATOR_TOKEN"),
        endpoints=scenario["endpoints"],
        confirm=InteractiveConfirmer(args.operator),
        position_tolerance_m=scenario["position_tolerance_m"],
        orientation_tolerance_rad=scenario["orientation_tolerance_rad"],
        stationary_step_m=scenario["stationary_step_m"],
        stationary_dwell_s=scenario["stationary_dwell_s"],
        stationary_samples=scenario["stationary_samples"],
        arrival_timeout_s=scenario["arrival_timeout_s"],
        final_stop_timeout_s=scenario["final_stop_timeout_s"],
        max_show_duration_s=scenario["max_show_duration_s"],
        minimum_route_distance_m=scenario["minimum_route_distance_m"],
        maximum_route_distance_m=scenario["maximum_route_distance_m"],
        protected_corridor_half_width_m=scenario[
            "protected_corridor_half_width_m"
        ],
        protected_corridor_longitudinal_margin_m=scenario[
            "protected_corridor_longitudinal_margin_m"
        ],
        path_timeout_s=scenario["path_timeout_s"],
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
