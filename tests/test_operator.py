from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest

from pawguide.models import Action
from pawguide.operator import ManualOperator, _parse_action


def test_manual_action_parser_exposes_only_bounded_commands() -> None:
    assert _parse_action("arm") == (Action.RESET_STOP, {})
    assert _parse_action("stand") == (Action.STAND_UP, {})
    assert _parse_action("sit") == (Action.SIT_DOWN, {})
    assert _parse_action("hello") == (Action.GREETING, {})
    assert _parse_action("goto demo_a") == (
        Action.GO_TO_WAYPOINT,
        {"waypoint_id": "demo_a"},
    )

    with pytest.raises(ValueError):
        _parse_action("move 1.0 0.0")
    with pytest.raises(ValueError):
        _parse_action("hello FrontFlip")


def test_manual_session_heartbeats_and_stops_when_closed() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        if request.url.path == "/v1/heartbeat":
            return httpx.Response(200, json={"stop_latched": True})
        if request.url.path == "/v1/commands":
            return httpx.Response(
                200,
                json={
                    "accepted": True,
                    "action": payload["action"],
                },
            )
        raise AssertionError(f"unexpected request: {request.url.path}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    operator = ManualOperator(
        "http://gateway",
        "operator-token",
        client=client,
        heartbeat_period_s=0.01,
        heartbeat_fresh_s=0.1,
    )

    operator.start()
    time.sleep(0.025)
    operator.command(Action.GREETING)
    operator.close()

    paths = [path for _method, path, _payload in calls]
    assert paths.count("/v1/heartbeat") >= 2
    actions = [
        payload["action"]
        for _method, path, payload in calls
        if path == "/v1/commands" and payload is not None
    ]
    assert actions == ["greeting", "stop"]


def test_non_stop_command_is_blocked_when_manual_heartbeat_is_stale() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={})
        )
    )
    operator = ManualOperator(
        "http://gateway",
        "operator-token",
        client=client,
        heartbeat_fresh_s=0.001,
    )
    operator.heartbeat()
    time.sleep(0.005)

    with pytest.raises(RuntimeError, match="heartbeat is stale"):
        operator.command(Action.STAND_UP)
