from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pawguide.adapter import DimOSMcpAdapter, DimOSMcpError


def mcp_response(text: str = "ok") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": "test",
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        },
    )


def test_adapter_maps_missions_to_the_verified_dimos_tools() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(
            (
                body["params"]["name"],
                body["params"]["arguments"],
            )
        )
        return mcp_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = DimOSMcpAdapter(client=client)

    adapter.go_to_waypoint("demo_a")
    adapter.start_patrol()
    adapter.return_home()
    adapter.stand_up()
    adapter.sit_down()
    adapter.greeting()

    assert calls == [
        ("navigate_to_waypoint", {"waypoint_id": "demo_a"}),
        ("start_patrol", {}),
        ("navigate_to_waypoint", {"waypoint_id": "home"}),
        ("execute_sport_command", {"command_name": "StandUp"}),
        ("execute_sport_command", {"command_name": "Sit"}),
        ("execute_sport_command", {"command_name": "Hello"}),
    ]


def test_emergency_stop_attempts_every_motion_stop_even_after_an_error() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tool_name = body["params"]["name"]
        calls.append(tool_name)
        if tool_name == "stop_patrol":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": "test",
                    "error": {"code": -32000, "message": "failed"},
                },
            )
        return mcp_response()

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = DimOSMcpAdapter(client=client)

    with pytest.raises(DimOSMcpError, match="stop_patrol"):
        adapter.emergency_stop("test")

    assert calls == [
        "emergency_stop",
        "stop_patrol",
        "end_exploration",
        "stop_navigation",
        "emergency_stop",
    ]


def test_dimos_adapter_rejects_nonlocal_mcp_urls() -> None:
    with pytest.raises(ValueError, match="local loopback"):
        DimOSMcpAdapter("http://example.com:9990/mcp")
