"""Consolidate authoritative evidence for the concept simulation gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any


PHYSICAL_GATES = [
    "Go2 supported-off-ground posture and gesture tests",
    "Go2 floor motion, stopping-distance, and heartbeat-loss tests",
    "RDK X5 mounting, power, cooling, strap, and cable retention",
    "Final booth barriers, measured clearance, waypoints, and route rehearsal",
    "Ring mechanical load, entanglement, release, BLE, audio, and haptics",
    "Dedicated operator, spotter, local STOP, and stationary fallback",
]


def _load(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _safe_final(state: dict[str, Any] | None) -> bool:
    return bool(
        state
        and state.get("stop_latched") is True
        and state.get("operator_heartbeat_fresh") is False
        and state.get("mission_state") == "stopped"
        and state.get("active_waypoint") is None
        and state.get("last_stop_reason") == "operator_stop"
    )


def build_suite(
    *,
    show_path: Path,
    blocked_path: Path,
    failure_path: Path,
    soak_path: Path,
    visualization_url: str,
) -> dict[str, Any]:
    show, show_hash = _load(show_path)
    blocked, blocked_hash = _load(blocked_path)
    failure, failure_hash = _load(failure_path)
    soak, soak_hash = _load(soak_path)

    gates = [
        {
            "id": "endurance",
            "label": "50-leg navigation endurance",
            "status": "passed" if (
                soak.get("passed") is True
                and soak.get("requested_legs") == 50
                and soak.get("completed_legs") == 50
                and soak.get("passed_legs") == 50
                and _safe_final(soak.get("final_state"))
            ) else "failed",
            "evidence": "50/50 legs; five live heartbeat-loss injections.",
        },
        {
            "id": "show",
            "label": "Complete 5 m show sequence",
            "status": "passed" if (
                show.get("passed") is True
                and isinstance(show.get("show_elapsed_s"), (int, float))
                and show["show_elapsed_s"] <= 120
                and not show.get("outbound_path_exit_segments")
                and not show.get("outbound_trajectory_exit_segments")
                and not show.get("return_path_exit_segments")
                and not show.get("return_trajectory_exit_segments")
                and _safe_final(show.get("final_state"))
            ) else "failed",
            "evidence": (
                f"{show.get('show_elapsed_s', '—')}s; stationary and orientation "
                "evidence; zero protected-corridor exits."
            ),
        },
        {
            "id": "blocked-lane",
            "label": "Sealed-lane safe refusal",
            "status": "passed" if (
                blocked.get("passed") is True
                and blocked.get("expected_safe_refusal") is True
                and blocked.get("navigation_success") is False
                and not blocked.get("lane_exit_samples")
                and not blocked.get("barrier_crossing_segments")
                and _safe_final(blocked.get("final_state"))
            ) else "failed",
            "evidence": (
                f"{blocked.get('max_displacement_m', '—')}m maximum displacement; "
                "no path, bypass, barrier crossing, or arrival claim."
            ),
        },
        {
            "id": "failure-matrix",
            "label": "Gateway failure matrix",
            "status": "passed" if (
                failure.get("passed") is True
                and _safe_final(failure.get("final_state"))
            ) else "failed",
            "evidence": (
                "Heartbeat-loss STOP "
                f"{failure.get('evidence', {}).get('heartbeat_loss', {}).get('elapsed_s', '—')}s; "
                "authorization, allowlist, validation, idempotency, and no-auto-rearm."
            ),
        },
    ]
    passed = all(gate["status"] == "passed" for gate in gates)
    final_state = failure.get("final_state")
    return {
        "artifact_schema_version": 1,
        "acceptance_scope": "simulation_pre_hardware",
        "passed": passed,
        "status": "passed" if passed else "failed",
        "started_at": show.get("started_at"),
        "finished_at": datetime.now(UTC).isoformat(),
        "show_elapsed_s": show.get("show_elapsed_s"),
        "requested_steps": len(gates),
        "completed_steps": sum(gate["status"] == "passed" for gate in gates),
        "sequence": gates,
        "checks": [
            {
                "name": gate["id"],
                "passed": gate["status"] == "passed",
                "detail": gate["evidence"],
            }
            for gate in gates
        ],
        "final_state": final_state,
        "visualization_url": visualization_url,
        "message": (
            "Simulation pre-hardware gates passed; physical Go2 and venue gates "
            "remain separate and pending."
            if passed
            else "One or more simulation pre-hardware gates failed."
        ),
        "evidence": {
            "show": {"path": str(show_path), "sha256": show_hash},
            "blocked_lane": {"path": str(blocked_path), "sha256": blocked_hash},
            "failure_matrix": {"path": str(failure_path), "sha256": failure_hash},
            "soak": {"path": str(soak_path), "sha256": soak_hash},
        },
        "physical_gates": [
            {"name": name, "status": "pending_physical_hardware"}
            for name in PHYSICAL_GATES
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the consolidated concept simulation acceptance report."
    )
    parser.add_argument(
        "--show", type=Path, default=Path("artifacts/concept-show-acceptance.json")
    )
    parser.add_argument(
        "--blocked",
        type=Path,
        default=Path("artifacts/concept-gate-blocked-acceptance.json"),
    )
    parser.add_argument(
        "--failure",
        type=Path,
        default=Path("artifacts/concept-failure-matrix.json"),
    )
    parser.add_argument(
        "--soak",
        type=Path,
        default=Path(
            "artifacts/soak/arena-qualification-20260726/soak-report.json"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/concept-pre-hardware-acceptance.json"),
    )
    parser.add_argument(
        "--visualization-url", default="http://100.102.208.90:7780"
    )
    args = parser.parse_args()
    report = build_suite(
        show_path=args.show,
        blocked_path=args.blocked,
        failure_path=args.failure,
        soak_path=args.soak,
        visualization_url=args.visualization_url,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
