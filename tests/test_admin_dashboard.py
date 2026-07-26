from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "provision" / "pawguide-admin-dashboard.html"
SCRIPT = ROOT / "provision" / "pawguide-admin-dashboard.js"
NGINX = ROOT / "provision" / "pawguide-admin.nginx.conf"
AUTH_INSTALLER = ROOT / "provision" / "install-admin-auth.sh"


def _normalize(value: dict[str, object], now: str) -> dict[str, object]:
    program = """
const ui = require(process.argv[1]);
const report = JSON.parse(process.argv[2]);
const normalized = ui.normalizeAcceptance(report, Date.parse(process.argv[3]));
process.stdout.write(JSON.stringify(normalized));
"""
    result = subprocess.run(
        ["node", "-e", program, str(SCRIPT), json.dumps(value), now],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _run_control(expression: str) -> object:
    program = f"""
const ui = require(process.argv[1]);
const result = {expression};
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "-e", program, str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_dashboard_is_a_tokenless_physical_kiosk_controller() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")

    assert 'id="viewer"' not in html
    assert 'id="viewer-link"' not in html
    assert "Live 3D Rerun viewer" not in html
    assert 'id="stop-command"' in html
    assert 'id="control-guidance"' in html
    assert 'data-action="stand_up"' in html
    assert 'data-action="sit_down"' in html
    assert 'data-action="greeting"' in html
    assert 'data-action="return_home"' in html
    assert 'id="operator-token"' not in html
    assert 'id="gateway-target"' not in html
    assert 'id="connect-command"' not in html
    assert 'id="heartbeat-command"' not in html
    assert 'id="arm-command"' not in html
    assert "ENABLE PHYSICAL CONTROL" not in html
    assert 'src="/admin/dashboard.js?v=kiosk-control-1"' in html

    nginx = NGINX.read_text(encoding="utf-8")
    assert "location = /admin/dashboard.js" in nginx
    assert "alias /var/www/pawguide/dashboard.js;" in nginx
    assert "location = /command-center" in nginx
    assert "location = /admin/status/acceptance" in nginx
    assert "alias /var/www/pawguide/acceptance.json;" in nginx
    assert "location /admin/api/sim/" in nginx
    assert "proxy_pass http://100.72.30.53:8876/;" in nginx
    assert "location /admin/api/physical/" in nginx
    assert "proxy_pass http://100.72.30.53:8765/;" in nginx
    assert "location = /admin/status/x5" in nginx
    assert "include /etc/pawguide/nginx-operator-auth.conf;" in nginx
    assert "proxy_set_header Authorization $http_authorization;" not in nginx.split(
        "location /admin/api/physical/", 1
    )[1]

    installer = AUTH_INSTALLER.read_text(encoding="utf-8")
    assert '${1:-/etc/pawguide/operator.token}' in installer
    assert "/etc/pawguide/nginx-operator-auth.conf" in installer


def test_control_center_generates_only_allowlisted_command_envelopes() -> None:
    envelope = _run_control(
        'ui.commandEnvelope("go_to_waypoint", '
        '{waypoint_id: "demo_gate"}, "00000000-0000-4000-8000-000000000001")'
    )

    assert envelope == {
        "command_id": "00000000-0000-4000-8000-000000000001",
        "action": "go_to_waypoint",
        "arguments": {"waypoint_id": "demo_gate"},
    }


def test_command_id_fallback_works_without_secure_context_crypto() -> None:
    command_id = _run_control(
        "(() => { Object.defineProperty(globalThis, 'crypto', "
        "{value: undefined, configurable: true}); return ui.newCommandId(); })()"
    )

    assert isinstance(command_id, str)
    assert len(command_id) == 36
    assert command_id[14] == "4"
    assert command_id[19] in "89ab"


def test_command_controls_require_only_connection_and_heartbeat() -> None:
    assert (
        _run_control("ui.mayDispatch({connected:true, heartbeat:true})")
        is True
    )
    assert (
        _run_control("ui.mayDispatch({connected:true, heartbeat:false})")
        is False
    )
    assert (
        _run_control("ui.mayDispatch({connected:false, heartbeat:true})")
        is False
    )


def test_movement_controls_follow_gateway_stop_state() -> None:
    assert (
        _run_control(
            "ui.mayMove({connected:true, heartbeat:true, stopLatched:true})"
        )
        is False
    )
    assert (
        _run_control(
            "ui.mayMove({connected:true, heartbeat:true, stopLatched:false})"
        )
        is True
    )


def test_running_soak_artifact_shows_progress_elapsed_and_safe_stop() -> None:
    normalized = _normalize(
        {
            "started_at": "2026-07-25T17:21:23Z",
            "finished_at": None,
            "requested_legs": 50,
            "completed_legs": 27,
            "passed_legs": 27,
            "passed": False,
            "visualization_url": "http://viewer/",
            "final_state": {
                "stop_latched": True,
                "operator_heartbeat_fresh": False,
                "mission_state": "stopped",
                "active_waypoint": None,
                "last_stop_reason": "operator_stop",
            },
        },
        "2026-07-25T17:31:23Z",
    )

    assert normalized["status"] == "running"
    assert normalized["completed"] == 27
    assert normalized["requested"] == 50
    assert normalized["elapsed_s"] == 600
    assert normalized["safe"] is True
    assert normalized["viewer_url"] == "http://viewer/"
    assert [step["status"] for step in normalized["sequence"]] == [
        "passed",
        "running",
        "passed",
    ]


def test_finished_failed_artifact_preserves_failed_evidence() -> None:
    normalized = _normalize(
        {
            "started_at": "2026-07-25T17:21:23Z",
            "finished_at": "2026-07-25T17:22:23Z",
            "requested_steps": 5,
            "completed_steps": 2,
            "passed": False,
            "final_state": {
                "stop_latched": False,
                "operator_heartbeat_fresh": False,
                "mission_state": "failed",
                "active_waypoint": None,
                "last_stop_reason": "adapter_error",
            },
            "checks": [
                {
                    "name": "sustained_arrival",
                    "passed": False,
                    "detail": "timeout",
                }
            ],
        },
        "2026-07-25T17:30:00Z",
    )

    assert normalized["status"] == "failed"
    assert normalized["elapsed_s"] == 60
    assert normalized["safe"] is False
    assert normalized["evidence"] == [
        {
            "label": "sustained arrival",
            "detail": "timeout",
            "passed": False,
        }
    ]


def test_completed_acceptance_requires_explicit_safe_final_stop() -> None:
    normalized = _normalize(
        {
            "status": "passed",
            "started_at": "2026-07-25T17:21:23Z",
            "finished_at": "2026-07-25T17:23:23Z",
            "requested_steps": 3,
            "completed_steps": 3,
            "sequence": [
                {"id": "stand", "label": "Stand", "status": "passed"},
                {"id": "greet", "label": "Greet", "status": "passed"},
                {"id": "stop", "label": "STOP", "status": "passed"},
            ],
            "final_state": {
                "stop_latched": True,
                "operator_heartbeat_fresh": False,
                "mission_state": "stopped",
                "active_waypoint": None,
                "last_stop_reason": "operator_stop",
            },
        },
        "2026-07-25T17:30:00Z",
    )

    assert normalized["status"] == "passed"
    assert normalized["safe"] is True
    assert normalized["elapsed_s"] == 120
    assert [step["label"] for step in normalized["sequence"]] == [
        "Stand",
        "Greet",
        "STOP",
    ]

    unsafe = _normalize(
        {
            "status": "passed",
            "started_at": "2026-07-25T17:21:23Z",
            "finished_at": "2026-07-25T17:23:23Z",
            "requested_steps": 1,
            "completed_steps": 1,
            "final_state": {
                "stop_latched": False,
                "operator_heartbeat_fresh": True,
                "mission_state": "idle",
                "active_waypoint": None,
                "last_stop_reason": "operator_stop",
            },
        },
        "2026-07-25T17:30:00Z",
    )

    assert unsafe["status"] == "failed"
    assert unsafe["safe"] is False


def test_concept_show_artifact_renders_real_sequence_and_show_duration() -> None:
    normalized = _normalize(
        {
            "passed": True,
            "started_at": "2026-07-25T18:49:40Z",
            "finished_at": "2026-07-25T18:50:45Z",
            "show_elapsed_s": 58.577,
            "checks": [
                {"name": "initial_home_stationary", "passed": True},
                {"name": "stand_up", "passed": True},
                {"name": "greeting", "passed": True},
                {"name": "gate_stationary_arrival", "passed": True},
                {"name": "gate_orientation", "passed": True},
                {"name": "home_stationary_arrival", "passed": True},
                {"name": "return_home_orientation", "passed": True},
                {"name": "show_duration", "passed": True, "detail": "58.577s"},
                {"name": "final_stop", "passed": True},
                {"name": "final_stop_invariants", "passed": True},
            ],
            "confirmations": [
                {"stage": "activation_ready"},
                {"stage": "greeting_complete"},
                {"stage": "gate_arrived"},
                {"stage": "farewell_complete"},
                {"stage": "home_arrived"},
                {"stage": "sitting_complete"},
            ],
            "final_state": {
                "stop_latched": True,
                "operator_heartbeat_fresh": False,
                "mission_state": "stopped",
                "active_waypoint": None,
                "last_stop_reason": "operator_stop",
            },
        },
        "2026-07-25T18:51:00Z",
    )

    assert normalized["status"] == "passed"
    assert normalized["requested"] == 7
    assert normalized["completed"] == 7
    assert normalized["elapsed_s"] == 58.577
    assert [step["label"] for step in normalized["sequence"]] == [
        "Ready at home",
        "Stand and greet",
        "Navigate 5 m to demo gate",
        "Gate confirmation and farewell",
        "Return home",
        "Sit down",
        "Final safety STOP",
    ]
    assert all(step["status"] == "passed" for step in normalized["sequence"])
