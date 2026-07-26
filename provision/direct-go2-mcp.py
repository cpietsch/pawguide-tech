#!/usr/bin/env python3
"""Minimal local MCP bridge for physical Go2 posture commissioning."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
from threading import Event, Lock
import time
from typing import Any

import aioice.ice


ROBOT_IP = os.environ.get("PAWGUIDE_ROBOT_IP", "192.168.12.1")
AES_KEY = os.environ["UNITREE_AES_128_KEY"]
SPORT_COMMANDS = {"StandUp": 1006, "Sit": 1009, "Hello": 1016}


def robot_facing_address() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((ROBOT_IP, 9))
        return str(probe.getsockname()[0])
    finally:
        probe.close()


LOCAL_IP = robot_facing_address()
aioice.ice.get_host_addresses = (
    lambda use_ipv4, use_ipv6: [LOCAL_IP] if use_ipv4 else []
)

from dimos.robot.unitree.connection import UnitreeWebRTCConnection  # noqa: E402
from dimos.msgs.geometry_msgs.Twist import Twist  # noqa: E402
from unitree_webrtc_connect import WebRTCConnectionMethod  # noqa: E402


TOOLS = [
    {
        "name": "execute_sport_command",
        "description": "Execute an allowlisted physical Go2 posture command.",
        "inputSchema": {
            "type": "object",
            "properties": {"command_name": {"type": "string"}},
            "required": ["command_name"],
        },
    },
    {
        "name": "emergency_stop",
        "description": "Immediately damp physical Go2 motion.",
        "inputSchema": {"type": "object"},
    },
    {
        "name": "navigate_to_waypoint",
        "description": "Move between home and the bounded one-meter test point.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "waypoint_id": {
                    "type": "string",
                    "enum": ["home", "demo_gate"],
                }
            },
            "required": ["waypoint_id"],
        },
    },
    *[
        {
            "name": name,
            "description": "No-op cleanup tool for an inactive subsystem.",
            "inputSchema": {"type": "object"},
        }
        for name in ("stop_patrol", "end_exploration", "stop_navigation")
    ],
]


class Bridge:
    def __init__(self) -> None:
        self.stop_requested = Event()
        self.motion_lock = Lock()
        self.position = "home"
        self.connection = UnitreeWebRTCConnection(
            ROBOT_IP,
            aes_128_key=AES_KEY,
            velocity_api=True,
            connection_method=WebRTCConnectionMethod.LocalAP,
        )

    def navigate(self, waypoint_id: str) -> str:
        if waypoint_id not in {"home", "demo_gate"}:
            raise ValueError(f"waypoint is not allowlisted: {waypoint_id}")
        if waypoint_id == self.position:
            return f"already at {waypoint_id}"
        if not self.motion_lock.acquire(blocking=False):
            raise RuntimeError("another physical movement is active")

        self.stop_requested.clear()
        try:
            if self.position == "home":
                if not self.connection.sport_command(1006):
                    raise RuntimeError("Go2 rejected RecoveryStand")
                time.sleep(3.0)
                if not self.connection.balance_stand():
                    raise RuntimeError("Go2 rejected BalanceStand")
                time.sleep(0.5)
            if self.stop_requested.is_set():
                raise RuntimeError("movement interrupted by STOP")

            self.connection.set_obstacle_avoidance(True)
            direction = 1.0 if waypoint_id == "demo_gate" else -1.0
            twist = Twist((direction * 0.2, 0, 0), (0, 0, 0))
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if self.stop_requested.wait(0.05):
                    raise RuntimeError("movement interrupted by STOP")
                if not self.connection.move(twist):
                    raise RuntimeError("Go2 rejected movement")
            self.connection.stop_movement()
            self.position = waypoint_id
            return f"arrived at {waypoint_id}"
        finally:
            self.connection.stop_movement()
            self.motion_lock.release()

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        print(f"physical MCP call: {name}", flush=True)
        if name == "execute_sport_command":
            command_name = str(arguments.get("command_name", ""))
            api_id = SPORT_COMMANDS.get(command_name)
            if api_id is None:
                raise ValueError(f"command is not allowlisted: {command_name}")
            if not self.connection.sport_command(api_id):
                raise RuntimeError(f"Go2 rejected {command_name}")
            return f"{command_name} sent to physical Go2"
        if name == "emergency_stop":
            self.stop_requested.set()
            self.connection.stop_movement()
            if not self.connection.sport_command(1001):
                raise RuntimeError("Go2 rejected Damp")
            return "Damp sent to physical Go2"
        if name == "navigate_to_waypoint":
            return self.navigate(str(arguments.get("waypoint_id", "")))
        if name in {"stop_patrol", "end_exploration", "stop_navigation"}:
            return f"{name} not active"
        raise ValueError(f"tool not found: {name}")


bridge = Bridge()


class McpHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        request: Any = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            method = request.get("method")
            if method == "initialize":
                result: dict[str, Any] = {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pawguide-direct-go2", "version": "1"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request.get("params") or {}
                text = bridge.call(
                    str(params.get("name", "")),
                    dict(params.get("arguments") or {}),
                )
                result = {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                }
            else:
                raise ValueError(f"unsupported MCP method: {method}")
            payload = {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except Exception as error:
            payload = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32000, "message": str(error)},
            }
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


try:
    ThreadingHTTPServer(("127.0.0.1", 9990), McpHandler).serve_forever()
finally:
    bridge.connection.stop()
