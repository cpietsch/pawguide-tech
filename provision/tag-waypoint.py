#!/usr/bin/env python3
"""Tag one exact waypoint through the loopback-only DimOS MCP endpoint."""

from __future__ import annotations

import argparse
import json
import re
from uuid import uuid4

import httpx

WAYPOINT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("waypoint_id")
    args = parser.parse_args()
    if not WAYPOINT_ID.fullmatch(args.waypoint_id):
        parser.error("use 1-64 lowercase letters, digits, underscores or hyphens")

    response = httpx.post(
        "http://127.0.0.1:9990/mcp",
        json={
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tools/call",
            "params": {
                "name": "tag_location",
                "arguments": {"waypoint_id": args.waypoint_id},
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body or body.get("result", {}).get("isError"):
        raise SystemExit(f"DimOS rejected waypoint: {json.dumps(body)}")
    content = body.get("result", {}).get("content", [])
    print(content[0].get("text", "Waypoint stored.") if content else "Waypoint stored.")


if __name__ == "__main__":
    main()
