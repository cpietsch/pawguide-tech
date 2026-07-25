"""Live-safe concept failure-matrix acceptance for the X5 gateway."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any
from uuid import uuid4

import httpx

from pawguide.acceptance import Check
from pawguide.models import Action
from pawguide.secrets import read_secret


@dataclass
class FailureMatrixReport:
    artifact_schema_version: int
    started_at: str
    gateway_url: str
    checks: list[Check] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    soak_reference: dict[str, Any] | None = None
    final_state: dict[str, Any] | None = None
    finished_at: str | None = None
    passed: bool = False


class FailureApi:
    def __init__(self, url: str, token: str) -> None:
        self._url = url.rstrip("/")
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(120, connect=5),
        )

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        started = time.monotonic()
        response = self._client.request(
            method, f"{self._url}{path}", json=payload
        )
        elapsed = (time.monotonic() - started) * 1000
        try:
            body = response.json()
        except ValueError:
            body = {"raw_body": response.text}
        if not isinstance(body, dict):
            body = {"body": body}
        return response.status_code, body, elapsed

    def command(
        self,
        action: str,
        *,
        command_id: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], float]:
        return self.request(
            "POST",
            "/v1/commands",
            {
                "command_id": command_id or str(uuid4()),
                "action": action,
                "arguments": arguments or {},
            },
        )

    def close(self) -> None:
        self._client.close()


class HeartbeatLease:
    def __init__(self, url: str, token: str, period_s: float = 0.5) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._period_s = period_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    def _send(self) -> None:
        response = httpx.post(
            f"{self._url}/v1/heartbeat",
            headers={"Authorization": f"Bearer {self._token}"},
            json={"source": "concept_failure_matrix"},
            timeout=3,
        )
        response.raise_for_status()

    def start(self) -> None:
        self._send()

        def loop() -> None:
            while not self._stop.wait(self._period_s):
                try:
                    self._send()
                except Exception as exc:
                    self._error = str(exc)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4)
            if self._thread.is_alive():
                raise RuntimeError("heartbeat request did not terminate")

    @property
    def error(self) -> str | None:
        return self._error


def _stopped(state: dict[str, Any], *, stale: bool) -> bool:
    return (
        state.get("stop_latched") is True
        and state.get("mission_state") == "stopped"
        and state.get("active_waypoint") is None
        and (not stale or state.get("operator_heartbeat_fresh") is False)
    )


def _load_soak_reference(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = path.read_bytes()
    document = json.loads(raw)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "passed": document.get("passed"),
        "requested_legs": document.get("requested_legs"),
        "completed_legs": document.get("completed_legs"),
        "passed_legs": document.get("passed_legs"),
    }


def run_failure_matrix(
    *,
    gateway_url: str,
    operator_token: str,
    developer_token: str,
    required_waypoints: list[str],
    heartbeat_test_waypoint: str,
    misspelled_waypoint: str,
    heartbeat_timeout_s: float = 2.5,
    no_auto_rearm_s: float = 1.0,
    final_state_timeout_s: float = 3.0,
    duplicate_max_elapsed_ms: float = 750,
    duplicate_max_ratio: float = 0.5,
    soak_report_path: Path | None = None,
) -> FailureMatrixReport:
    report = FailureMatrixReport(
        artifact_schema_version=1,
        started_at=datetime.now(UTC).isoformat(),
        gateway_url=gateway_url,
    )
    operator = FailureApi(gateway_url, operator_token)
    developer = FailureApi(gateway_url, developer_token)
    lease: HeartbeatLease | None = None

    def check(name: str, passed: bool, detail: str) -> None:
        report.checks.append(Check(name, passed, detail))
        if not passed:
            raise RuntimeError(f"{name}: {detail}")

    def op_state() -> dict[str, Any]:
        status, body, _ = operator.request("GET", "/v1/state")
        if status != 200:
            raise RuntimeError(f"state returned HTTP {status}: {body}")
        return body

    try:
        report.soak_reference = _load_soak_reference(soak_report_path)
        if report.soak_reference is not None:
            check(
                "soak_reference",
                report.soak_reference.get("passed") is True
                and report.soak_reference.get("requested_legs") == 50
                and report.soak_reference.get("completed_legs") == 50
                and report.soak_reference.get("passed_legs") == 50,
                json.dumps(report.soak_reference, sort_keys=True),
            )

        status, capabilities, _ = operator.request(
            "GET", "/v1/capabilities"
        )
        check(
            "exact_waypoints",
            status == 200
            and sorted(capabilities.get("allowed_waypoints", []))
            == sorted(required_waypoints),
            json.dumps(capabilities, sort_keys=True),
        )
        startup_state = op_state()
        report.evidence["startup_state"] = startup_state
        check(
            "startup_initial_stop_invariants",
            _stopped(startup_state, stale=True),
            json.dumps(startup_state, sort_keys=True),
        )

        status, initial_stop, _ = operator.command(Action.STOP.value)
        report.evidence["initial_stop"] = initial_stop
        check(
            "initial_operator_stop",
            status == 200
            and initial_stop.get("accepted") is True
            and initial_stop.get("reason") == "stop_latched",
            json.dumps(initial_stop, sort_keys=True),
        )

        stale_reset_id = str(uuid4())
        status, stale_reset, _ = operator.command(
            Action.RESET_STOP.value, command_id=stale_reset_id
        )
        report.evidence["stale_reset"] = stale_reset
        check(
            "stale_heartbeat_reset_rejected",
            status == 200
            and stale_reset.get("accepted") is False
            and stale_reset.get("reason")
            == "fresh_operator_heartbeat_required",
            json.dumps(stale_reset, sort_keys=True),
        )

        lease = HeartbeatLease(gateway_url, operator_token)
        lease.start()
        status, arm, _ = operator.command(Action.RESET_STOP.value)
        check(
            "operator_arm",
            status == 200
            and arm.get("accepted") is True
            and arm.get("reason") == "stop_reset",
            json.dumps(arm, sort_keys=True),
        )

        status, unknown, _ = operator.command(
            Action.GO_TO_WAYPOINT.value,
            arguments={"waypoint_id": misspelled_waypoint},
        )
        report.evidence["unknown_waypoint"] = unknown
        check(
            "unknown_waypoint_rejected",
            status == 200
            and unknown.get("accepted") is False
            and unknown.get("reason") == "waypoint_not_allowed",
            json.dumps(unknown, sort_keys=True),
        )

        status, raw_action, _ = operator.command(
            "raw_velocity",
            arguments={"forward": 1.0},
        )
        report.evidence["raw_action"] = {
            "http_status": status,
            "body": raw_action,
        }
        check(
            "raw_action_http_validation_rejected",
            status == 422,
            json.dumps(report.evidence["raw_action"], sort_keys=True),
        )
        post_validation_state = op_state()
        check(
            "validation_rejections_do_not_move",
            post_validation_state.get("mission_state") == "idle"
            and post_validation_state.get("stop_latched") is False
            and post_validation_state.get("active_waypoint") is None,
            json.dumps(post_validation_state, sort_keys=True),
        )

        status, operator_stop, _ = operator.command(Action.STOP.value)
        check(
            "operator_stop_accepted",
            status == 200 and operator_stop.get("accepted") is True,
            json.dumps(operator_stop, sort_keys=True),
        )
        status, developer_stop, _ = developer.command(Action.STOP.value)
        check(
            "developer_stop_accepted",
            status == 200 and developer_stop.get("accepted") is True,
            json.dumps(developer_stop, sort_keys=True),
        )
        status, developer_reset, _ = developer.command(
            Action.RESET_STOP.value
        )
        report.evidence["developer_reset"] = {
            "http_status": status,
            "body": developer_reset,
        }
        check(
            "developer_reset_forbidden",
            status == 403,
            json.dumps(report.evidence["developer_reset"], sort_keys=True),
        )

        duplicate_id = str(uuid4())
        status1, first_stop, first_elapsed = operator.command(
            Action.STOP.value, command_id=duplicate_id
        )
        status2, second_stop, second_elapsed = operator.command(
            Action.STOP.value, command_id=duplicate_id
        )
        report.evidence["duplicate_command"] = {
            "command_id": duplicate_id,
            "first": first_stop,
            "second": second_stop,
            "first_elapsed_ms": round(first_elapsed, 3),
            "second_elapsed_ms": round(second_elapsed, 3),
        }
        check(
            "duplicate_uuid_idempotent_result",
            status1 == status2 == 200
            and first_stop == second_stop
            and second_elapsed <= duplicate_max_elapsed_ms
            and second_elapsed <= first_elapsed * duplicate_max_ratio,
            json.dumps(report.evidence["duplicate_command"], sort_keys=True),
        )

        status, rearm, _ = operator.command(Action.RESET_STOP.value)
        check(
            "heartbeat_test_arm",
            status == 200 and rearm.get("accepted") is True,
            json.dumps(rearm, sort_keys=True),
        )
        status, navigation, _ = operator.command(
            Action.GO_TO_WAYPOINT.value,
            arguments={"waypoint_id": heartbeat_test_waypoint},
        )
        check(
            "heartbeat_test_navigation_active",
            status == 200
            and navigation.get("accepted") is True
            and navigation.get("state") == "navigating",
            json.dumps(navigation, sort_keys=True),
        )
        lease.stop()
        check(
            "heartbeat_worker_clean",
            lease.error is None,
            lease.error or "no heartbeat errors",
        )
        heartbeat_stopped = time.monotonic()
        timeout_state: dict[str, Any] = {}
        while time.monotonic() - heartbeat_stopped <= heartbeat_timeout_s:
            timeout_state = op_state()
            if (
                _stopped(timeout_state, stale=True)
                and timeout_state.get("last_stop_reason")
                == "operator_heartbeat_timeout"
            ):
                break
            time.sleep(0.05)
        heartbeat_elapsed = time.monotonic() - heartbeat_stopped
        report.evidence["heartbeat_loss"] = {
            "elapsed_s": round(heartbeat_elapsed, 3),
            "state": timeout_state,
        }
        check(
            "heartbeat_loss_navigation_stop",
            heartbeat_elapsed <= heartbeat_timeout_s
            and _stopped(timeout_state, stale=True)
            and timeout_state.get("last_stop_reason")
            == "operator_heartbeat_timeout",
            json.dumps(report.evidence["heartbeat_loss"], sort_keys=True),
        )
        time.sleep(no_auto_rearm_s)
        recovery_state = op_state()
        report.evidence["no_auto_rearm_state"] = recovery_state
        check(
            "no_auto_rearm",
            _stopped(recovery_state, stale=True)
            and recovery_state.get("last_stop_reason")
            == "operator_heartbeat_timeout",
            json.dumps(recovery_state, sort_keys=True),
        )
    except Exception as exc:
        report.checks.append(Check("run_completed", False, str(exc)))
    finally:
        if lease is not None:
            try:
                lease.stop()
            except Exception as exc:
                report.checks.append(
                    Check("heartbeat_cleanup", False, str(exc))
                )
        try:
            status, final_stop, _ = operator.command(Action.STOP.value)
            report.checks.append(
                Check(
                    "final_operator_stop",
                    status == 200 and final_stop.get("accepted") is True,
                    json.dumps(final_stop, sort_keys=True),
                )
            )
            deadline = time.monotonic() + final_state_timeout_s
            while time.monotonic() < deadline:
                report.final_state = op_state()
                if (
                    _stopped(report.final_state, stale=True)
                    and report.final_state.get("last_stop_reason")
                    == "operator_stop"
                ):
                    break
                time.sleep(0.05)
            report.checks.append(
                Check(
                    "final_stop_invariants",
                    report.final_state is not None
                    and _stopped(report.final_state, stale=True)
                    and report.final_state.get("last_stop_reason")
                    == "operator_stop",
                    json.dumps(report.final_state, sort_keys=True),
                )
            )
        except Exception as exc:
            report.checks.append(Check("final_operator_stop", False, str(exc)))
        operator.close()
        developer.close()

    report.finished_at = datetime.now(UTC).isoformat()
    report.passed = (
        bool(report.checks)
        and all(item.passed for item in report.checks)
        and report.final_state is not None
        and _stopped(report.final_state, stale=True)
        and report.final_state.get("last_stop_reason") == "operator_stop"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the live-safe concept gateway failure matrix."
    )
    parser.add_argument("--gateway-url", default="http://100.72.30.53:8876")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path("config/concept-failure-matrix.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/concept-failure-matrix.json"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    soak_path = (
        Path(scenario["soak_report_path"])
        if scenario.get("soak_report_path")
        else None
    )
    report = run_failure_matrix(
        gateway_url=args.gateway_url,
        operator_token=read_secret("PAWGUIDE_OPERATOR_TOKEN"),
        developer_token=read_secret("PAWGUIDE_DEV_TOKEN"),
        required_waypoints=scenario["required_waypoints"],
        heartbeat_test_waypoint=scenario["heartbeat_test_waypoint"],
        misspelled_waypoint=scenario["misspelled_waypoint"],
        heartbeat_timeout_s=scenario["heartbeat_timeout_s"],
        no_auto_rearm_s=scenario["no_auto_rearm_s"],
        final_state_timeout_s=scenario["final_state_timeout_s"],
        duplicate_max_elapsed_ms=scenario["duplicate_max_elapsed_ms"],
        duplicate_max_ratio=scenario["duplicate_max_ratio"],
        soak_report_path=soak_path,
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
