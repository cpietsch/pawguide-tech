from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
DASHBOARD = ROOT / "provision" / "pawguide-admin-dashboard.html"
SCRIPT = ROOT / "provision" / "pawguide-admin-dashboard.js"
NGINX = ROOT / "provision" / "pawguide-admin.nginx.conf"
AUTH_INSTALLER = ROOT / "provision" / "install-admin-auth.sh"
ADMIN_INSTALLER = ROOT / "provision" / "install-china-admin.sh"
TOKEN_SYNC = ROOT / "provision" / "sync-x5-operator-token.sh"


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
    return __import__("json").loads(result.stdout)


def test_dashboard_is_a_tokenless_physical_kiosk_controller() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'id="viewer"' not in html
    assert "Rerun" not in html
    assert 'id="stop-command"' in html
    assert 'id="control-guidance"' in html
    assert 'data-action="stand_up"' in html
    assert 'data-action="sit_down"' in html
    assert 'data-action="greeting"' in html
    assert 'id="round-trip-command"' in html
    assert 'data-action="return_home"' not in html
    assert 'id="operator-token"' not in html
    assert 'id="gateway-target"' not in html
    assert 'id="connect-command"' not in html
    assert 'id="heartbeat-command"' not in html
    assert 'id="arm-command"' not in html
    assert 'src="/admin/dashboard.js?v=kiosk-control-2"' in html

    assert "/admin/api/physical" in javascript
    assert "admin-kiosk" in javascript
    assert "tagWaypoint" not in javascript
    assert "operator-token" not in javascript
    assert "/v1/commissioning/" not in javascript


def test_nginx_injects_the_x5_token_only_for_the_physical_api() -> None:
    nginx = NGINX.read_text(encoding="utf-8")

    assert "location = /admin/dashboard.js" in nginx
    assert "alias /var/www/pawguide/dashboard.js;" in nginx
    assert "location = /command-center" in nginx
    assert "location /admin/api/sim/" in nginx
    assert "proxy_pass http://100.72.30.53:8876/;" in nginx
    assert "location /admin/api/physical/" in nginx
    assert "proxy_pass http://100.72.30.53:8765/;" in nginx
    assert "location = /admin/status/x5" in nginx
    assert "include /etc/pawguide/nginx-operator-auth.conf;" in nginx
    physical_location = nginx.split("location /admin/api/physical/", 1)[1]
    assert "proxy_set_header Authorization $http_authorization;" not in (
        physical_location
    )


def test_admin_installers_keep_the_browser_credential_free() -> None:
    installer = AUTH_INSTALLER.read_text(encoding="utf-8")
    assert '${1:-/etc/pawguide/operator.token}' in installer
    assert "/etc/pawguide/nginx-operator-auth.conf" in installer

    admin_installer = ADMIN_INSTALLER.read_text(encoding="utf-8")
    assert "/var/www/pawguide/dashboard.html" in admin_installer
    assert "/etc/nginx/sites-available/pawguide-admin" in admin_installer
    assert "/etc/pawguide/x5-operator.token" in admin_installer

    token_sync = TOKEN_SYNC.read_text(encoding="utf-8")
    assert "sudo -n cat /etc/pawguide/operator.token" in token_sync
    assert "nginx -t" in token_sync


def test_control_center_generates_command_envelopes() -> None:
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


def test_command_readiness_helpers_follow_gateway_state() -> None:
    assert _run_control(
        "ui.mayDispatch({connected:true, heartbeat:true})"
    ) is True
    assert _run_control(
        "ui.mayDispatch({connected:true, heartbeat:false})"
    ) is False
    assert _run_control(
        "ui.mayMove({connected:true, heartbeat:true, stopLatched:true})"
    ) is False
    assert _run_control(
        "ui.mayMove({connected:true, heartbeat:true, stopLatched:false})"
    ) is True
