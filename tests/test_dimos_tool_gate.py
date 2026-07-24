from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "provision" / "check-dimos-tools.py"
REQUIRED = [
    "begin_exploration",
    "emergency_stop",
    "end_exploration",
    "execute_sport_command",
    "navigate_to_waypoint",
    "start_patrol",
    "stop_navigation",
    "stop_patrol",
    "tag_location",
]


def _run(document: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--quiet"],
        input=json.dumps(document),
        text=True,
        capture_output=True,
        check=False,
    )


def test_tool_gate_accepts_dimos_cli_shape() -> None:
    result = _run([{"name": name} for name in REQUIRED])

    assert result.returncode == 0


def test_tool_gate_accepts_json_rpc_shape() -> None:
    result = _run({"result": {"tools": [{"name": name} for name in REQUIRED]}})

    assert result.returncode == 0


def test_tool_gate_rejects_half_ready_registry() -> None:
    result = _run({"result": {"tools": []}})

    assert result.returncode == 1
