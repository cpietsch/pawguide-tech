"""Robot adapter boundary for mock and MCP-backed deployments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

import httpx


class RobotAdapter(Protocol):
    def emergency_stop(self, reason: str) -> None: ...

    def pause(self) -> None: ...

    def stand_up(self) -> None: ...

    def sit_down(self) -> None: ...

    def greeting(self) -> None: ...

    def go_to_waypoint(self, waypoint_id: str) -> None: ...

    def start_patrol(self) -> None: ...

    def return_home(self) -> None: ...


@dataclass
class MockRobotAdapter:
    """In-memory adapter used for development and safety tests."""

    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def emergency_stop(self, reason: str) -> None:
        self.calls.append(("emergency_stop", reason))

    def pause(self) -> None:
        self.calls.append(("pause", None))

    def stand_up(self) -> None:
        self.calls.append(("stand_up", None))

    def sit_down(self) -> None:
        self.calls.append(("sit_down", None))

    def greeting(self) -> None:
        self.calls.append(("greeting", None))

    def go_to_waypoint(self, waypoint_id: str) -> None:
        self.calls.append(("go_to_waypoint", waypoint_id))

    def start_patrol(self) -> None:
        self.calls.append(("start_patrol", None))

    def return_home(self) -> None:
        self.calls.append(("return_home", None))


class DimOSMcpError(RuntimeError):
    """Raised when the local DimOS MCP bridge cannot complete an operation."""


class DimOSMcpAdapter:
    """Translate the PawGuide command allowlist to local DimOS MCP tools."""

    _STOP_TOOLS = (
        ("emergency_stop", {}),
        ("stop_patrol", {}),
        ("end_exploration", {}),
        ("stop_navigation", {}),
        ("emergency_stop", {}),
    )

    def __init__(
        self,
        url: str = "http://127.0.0.1:9990/mcp",
        *,
        timeout_s: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("DimOS MCP URL must use HTTP on the local loopback")
        self._url = url
        self._client = client or httpx.Client(timeout=timeout_s)

    def emergency_stop(self, _reason: str) -> None:
        failures: list[str] = []
        for tool_name, arguments in self._STOP_TOOLS:
            try:
                self._call_tool(tool_name, arguments)
            except (DimOSMcpError, httpx.HTTPError):
                failures.append(tool_name)
        if failures:
            failed = ", ".join(failures)
            raise DimOSMcpError(f"one or more stop tools failed: {failed}")

    def pause(self) -> None:
        self.emergency_stop("pause")

    def stand_up(self) -> None:
        self._call_tool("execute_sport_command", {"command_name": "StandUp"})

    def sit_down(self) -> None:
        self._call_tool("execute_sport_command", {"command_name": "Sit"})

    def greeting(self) -> None:
        self._call_tool("execute_sport_command", {"command_name": "Hello"})

    def go_to_waypoint(self, waypoint_id: str) -> None:
        self._call_tool("navigate_to_waypoint", {"waypoint_id": waypoint_id})

    def start_patrol(self) -> None:
        self._call_tool("start_patrol", {})

    def return_home(self) -> None:
        self.go_to_waypoint("home")

    def _call_tool(self, name: str, arguments: dict[str, object]) -> str:
        response = self._client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid4()),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise DimOSMcpError(f"DimOS MCP rejected tool {name}")
        result = body.get("result")
        if not isinstance(result, dict) or result.get("isError"):
            raise DimOSMcpError(f"DimOS MCP tool {name} failed")
        content = result.get("content", [])
        if not isinstance(content, list) or not content:
            return ""
        first = content[0]
        if not isinstance(first, dict):
            return str(first)
        return str(first.get("text", ""))
