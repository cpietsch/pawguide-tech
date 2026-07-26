#!/usr/bin/env python3
"""Start DimOS with WebRTC ICE constrained to the Go2-facing interface."""

from __future__ import annotations

import os
import socket
import sys

import aioice.ice


def robot_facing_address(robot_ip: str) -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((robot_ip, 9))
        return str(probe.getsockname()[0])
    finally:
        probe.close()


robot_ip = os.environ.get("PAWGUIDE_ROBOT_IP", "192.168.12.1")
local_ip = robot_facing_address(robot_ip)


def local_ap_addresses(use_ipv4: bool, use_ipv6: bool) -> list[str]:
    del use_ipv6
    return [local_ip] if use_ipv4 else []


aioice.ice.get_host_addresses = local_ap_addresses

from dimos.robot.cli.dimos import cli_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli_main())
