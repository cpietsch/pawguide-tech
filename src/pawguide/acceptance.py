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
            if name not in {"robot_pose", "full_state"} or not payload:
                continue
            body = payload[0]
            if name == "full_state" and isinstance(body, dict):
                body = body.get("robot_pose")
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
                    self._updates += 1

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
        health_times: list[float] = []
        for _ in range(10):
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
        except Exception as exc:
            report.checks.append(Check("final_stop", False, str(exc)))
        poses.close()
        gateway.close()

    report.finished_at = datetime.now(UTC).isoformat()
    report.passed = (
        bool(report.checks)
        and all(item.passed for item in report.checks)
        and report.final_state is not None
        and report.final_state.get("stop_latched") is True
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
