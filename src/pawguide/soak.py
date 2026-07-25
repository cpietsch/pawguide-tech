"""Repeated, fail-closed home ↔ demo soak test for the simulated Go2."""

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
class SoakLegReport:
    index: int
    started_at: str
    start_waypoint: str | None = None
    target_waypoint: str | None = None
    initial_pose: list[float] | None = None
    final_pose: list[float] | None = None
    displacement_m: float | None = None
    arrival_error_m: float | None = None
    watchdog_exercised: bool = False
    elapsed_s: float | None = None
    checks: list[Check] = field(default_factory=list)
    final_state: dict[str, Any] | None = None
    finished_at: str | None = None
    passed: bool = False


@dataclass
class SoakReport:
    started_at: str
    gateway_url: str
    visualization_url: str
    requested_legs: int
    completed_legs: int = 0
    passed_legs: int = 0
    artifact_dir: str = ""
    legs: list[str] = field(default_factory=list)
    final_state: dict[str, Any] | None = None
    finished_at: str | None = None
    passed: bool = False


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _nearest_endpoint(
    pose: list[float],
    endpoints: dict[str, tuple[float, float]],
    tolerance_m: float,
) -> str:
    distances = {
        name: math.dist(pose[:2], coordinates)
        for name, coordinates in endpoints.items()
    }
    nearest = min(distances, key=distances.__getitem__)
    if distances[nearest] > tolerance_m:
        detail = ", ".join(
            f"{name}={distance:.3f}m" for name, distance in sorted(distances.items())
        )
        raise RuntimeError(
            f"pose is not within {tolerance_m}m of a soak endpoint ({detail})"
        )
    return nearest


def _stopped(state: dict[str, Any], *, reason: str | None = None) -> bool:
    valid = (
        state.get("mission_state") == "stopped"
        and state.get("stop_latched") is True
        and state.get("active_waypoint") is None
    )
    return valid and (reason is None or state.get("last_stop_reason") == reason)


def _wait_for_state(
    gateway: GatewaySession,
    predicate,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest, _ = gateway.request("GET", "/v1/state")
        if predicate(latest):
            return latest
        time.sleep(0.1)
    return latest


def _wait_for_sustained_arrival(
    poses: PoseMonitor,
    *,
    initial_pose: list[float],
    target_pose: tuple[float, float],
    initial_updates: int,
    minimum_displacement_m: float,
    arrival_tolerance_m: float,
    sustained_samples: int,
    timeout_s: float,
) -> tuple[list[float], float, float]:
    deadline = time.monotonic() + timeout_s
    last_updates = initial_updates
    consecutive = 0
    latest_pose: list[float] | None = None
    displacement = 0.0
    arrival_error = math.inf
    while time.monotonic() < deadline:
        current, updates = poses.latest()
        if current is None or updates == last_updates:
            time.sleep(0.05)
            continue
        last_updates = updates
        latest_pose = current
        displacement = math.dist(current[:2], initial_pose[:2])
        arrival_error = math.dist(current[:2], target_pose)
        if (
            displacement >= minimum_displacement_m
            and arrival_error <= arrival_tolerance_m
        ):
            consecutive += 1
            if consecutive >= sustained_samples:
                return current, displacement, arrival_error
        else:
            consecutive = 0
    raise TimeoutError(
        "sustained arrival not observed: "
        f"pose={latest_pose}, displacement={displacement:.3f}m, "
        f"arrival_error={arrival_error:.3f}m"
    )


def run_soak(
    *,
    gateway_url: str,
    visualization_url: str,
    token: str,
    endpoints: dict[str, tuple[float, float]],
    destination_waypoint: str,
    legs: int,
    artifact_dir: Path,
    minimum_displacement_m: float = 0.5,
    arrival_tolerance_m: float = 0.2,
    endpoint_tolerance_m: float = 0.25,
    sustained_samples: int = 3,
    arrival_timeout_s: float = 90,
    heartbeat_stop_deadline_s: float = 3,
    watchdog_every: int = 10,
    max_leg_runtime_s: float = 240,
) -> SoakReport:
    if set(endpoints) != {"home", destination_waypoint}:
        raise ValueError(
            "soak endpoints must be exactly home and the configured destination"
        )
    if legs < 1 or sustained_samples < 1 or watchdog_every < 1:
        raise ValueError("legs, sustained_samples and watchdog_every must be positive")

    report = SoakReport(
        started_at=datetime.now(UTC).isoformat(),
        gateway_url=gateway_url,
        visualization_url=visualization_url,
        requested_legs=legs,
        artifact_dir=str(artifact_dir),
    )
    poses = PoseMonitor(visualization_url)
    poses.start()

    try:
        for index in range(1, legs + 1):
            leg = SoakLegReport(index=index, started_at=datetime.now(UTC).isoformat())
            leg_started = time.monotonic()
            gateway = GatewaySession(gateway_url, token)

            def check(name: str, passed: bool, detail: str) -> None:
                leg.checks.append(Check(name, passed, detail))
                if not passed:
                    raise RuntimeError(f"{name}: {detail}")

            try:
                health, _ = gateway.request("GET", "/health")
                check(
                    "gateway_health",
                    health.get("status") == "ok"
                    and health.get("adapter") == "dimos_mcp"
                    and health.get("motion_capable") is True,
                    json.dumps(health, sort_keys=True),
                )
                capabilities, _ = gateway.request("GET", "/v1/capabilities")
                check(
                    "endpoint_allowlist",
                    set(endpoints).issubset(
                        set(capabilities.get("allowed_waypoints", []))
                    ),
                    json.dumps(capabilities.get("allowed_waypoints"), sort_keys=True),
                )

                initial_stop, _ = gateway.command(Action.STOP)
                check(
                    "initial_stop",
                    initial_stop.get("accepted") is True,
                    json.dumps(initial_stop, sort_keys=True),
                )
                stopped_state, _ = gateway.request("GET", "/v1/state")
                check(
                    "initial_stop_invariants",
                    _stopped(stopped_state),
                    json.dumps(stopped_state, sort_keys=True),
                )

                leg.initial_pose = poses.wait_for_pose(15)
                leg.start_waypoint = _nearest_endpoint(
                    leg.initial_pose, endpoints, endpoint_tolerance_m
                )
                leg.target_waypoint = (
                    destination_waypoint
                    if leg.start_waypoint == "home"
                    else "home"
                )
                target_pose = endpoints[leg.target_waypoint]
                check(
                    "endpoint_selected",
                    True,
                    f"{leg.start_waypoint}->{leg.target_waypoint}",
                )

                gateway.start_heartbeat()
                reset, _ = gateway.command(Action.RESET_STOP)
                check(
                    "arm",
                    reset.get("accepted") is True
                    and reset.get("state") == "idle"
                    and reset.get("reason") == "stop_reset",
                    json.dumps(reset, sort_keys=True),
                )
                poses.reset_path()
                navigation, _ = gateway.command(
                    Action.GO_TO_WAYPOINT,
                    waypoint_id=leg.target_waypoint,
                )
                check(
                    "navigation_dispatch",
                    navigation.get("accepted") is True
                    and navigation.get("state") == "navigating"
                    and navigation.get("reason") == "navigation_started",
                    json.dumps(navigation, sort_keys=True),
                )
                planned_path = poses.wait_for_path(10)
                check(
                    "navigation_map_ready",
                    len(planned_path) >= 2,
                    f"planned_points={len(planned_path)}",
                )

                _, initial_updates = poses.latest()
                final_pose, displacement, arrival_error = (
                    _wait_for_sustained_arrival(
                        poses,
                        initial_pose=leg.initial_pose,
                        target_pose=target_pose,
                        initial_updates=initial_updates,
                        minimum_displacement_m=minimum_displacement_m,
                        arrival_tolerance_m=arrival_tolerance_m,
                        sustained_samples=sustained_samples,
                        timeout_s=arrival_timeout_s,
                    )
                )
                leg.final_pose = final_pose
                leg.displacement_m = round(displacement, 3)
                leg.arrival_error_m = round(arrival_error, 3)
                check(
                    "sustained_arrival",
                    True,
                    f"samples={sustained_samples}, displacement="
                    f"{leg.displacement_m}m, error={leg.arrival_error_m}m",
                )

                leg.watchdog_exercised = index % watchdog_every == 0
                if leg.watchdog_exercised:
                    gateway.stop_heartbeat()
                    watchdog_state = _wait_for_state(
                        gateway,
                        lambda value: _stopped(
                            value, reason="operator_heartbeat_timeout"
                        ),
                        heartbeat_stop_deadline_s,
                    )
                    check(
                        "heartbeat_loss_stop",
                        _stopped(
                            watchdog_state, reason="operator_heartbeat_timeout"
                        )
                        and watchdog_state.get("operator_heartbeat_fresh") is False,
                        json.dumps(watchdog_state, sort_keys=True),
                    )
            except Exception as exc:
                leg.checks.append(Check("run_completed", False, str(exc)))
            finally:
                try:
                    final_stop, _ = gateway.command(Action.STOP)
                    leg.checks.append(
                        Check(
                            "final_stop",
                            final_stop.get("accepted") is True,
                            json.dumps(final_stop, sort_keys=True),
                        )
                    )
                    gateway.stop_heartbeat()
                    leg.final_state = _wait_for_state(
                        gateway,
                        lambda value: _stopped(value, reason="operator_stop")
                        and value.get("operator_heartbeat_fresh") is False,
                        heartbeat_stop_deadline_s,
                    )
                    leg.checks.append(
                        Check(
                            "final_stop_invariants",
                            _stopped(leg.final_state, reason="operator_stop")
                            and leg.final_state.get("operator_heartbeat_fresh")
                            is False,
                            json.dumps(leg.final_state, sort_keys=True),
                        )
                    )
                except Exception as exc:
                    leg.checks.append(Check("final_stop", False, str(exc)))
                finally:
                    try:
                        gateway.close()
                    except Exception as exc:
                        leg.checks.append(
                            Check("gateway_close", False, str(exc))
                        )

            leg.finished_at = datetime.now(UTC).isoformat()
            leg.elapsed_s = round(time.monotonic() - leg_started, 3)
            leg.checks.append(
                Check(
                    "leg_runtime",
                    leg.elapsed_s <= max_leg_runtime_s,
                    f"elapsed={leg.elapsed_s}s limit={max_leg_runtime_s}s",
                )
            )
            leg.passed = bool(leg.checks) and all(
                item.passed for item in leg.checks
            )
            target = leg.target_waypoint or "unknown"
            leg_path = artifact_dir / f"leg-{index:04d}-to-{target}.json"
            _write_json(leg_path, leg)
            report.legs.append(str(leg_path))
            report.completed_legs += 1
            if leg.passed:
                report.passed_legs += 1
            report.final_state = leg.final_state
            _write_json(artifact_dir / "soak-report.json", report)
            if not leg.passed:
                break
    finally:
        poses.close()

    report.finished_at = datetime.now(UTC).isoformat()
    report.passed = (
        report.completed_legs == report.requested_legs
        and report.passed_legs == report.requested_legs
        and report.final_state is not None
        and _stopped(report.final_state, reason="operator_stop")
        and report.final_state.get("operator_heartbeat_fresh") is False
    )
    _write_json(artifact_dir / "soak-report.json", report)
    return report


def _parser() -> argparse.ArgumentParser:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(
        description="Run repeated fail-closed home ↔ demo simulation legs."
    )
    parser.add_argument("--gateway-url", default="http://100.72.30.53:8876")
    parser.add_argument("--visualization-url", default="http://100.102.208.90:7780")
    parser.add_argument("--scenario", type=Path, default=Path("config/simulation-soak.json"))
    parser.add_argument("--legs", type=int)
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("artifacts/soak") / timestamp
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    report = run_soak(
        gateway_url=args.gateway_url,
        visualization_url=args.visualization_url,
        token=read_secret("PAWGUIDE_OPERATOR_TOKEN"),
        endpoints={
            name: tuple(value[:2])
            for name, value in scenario["endpoints"].items()
        },
        destination_waypoint=scenario["destination_waypoint"],
        legs=args.legs or scenario["legs"],
        artifact_dir=args.artifact_dir,
        minimum_displacement_m=scenario["minimum_displacement_m"],
        arrival_tolerance_m=scenario["arrival_tolerance_m"],
        endpoint_tolerance_m=scenario["endpoint_tolerance_m"],
        sustained_samples=scenario["sustained_samples"],
        arrival_timeout_s=scenario["arrival_timeout_s"],
        heartbeat_stop_deadline_s=scenario["heartbeat_stop_deadline_s"],
        watchdog_every=scenario["watchdog_every"],
        max_leg_runtime_s=scenario["max_leg_runtime_s"],
    )
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
