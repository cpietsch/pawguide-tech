#!/usr/bin/env python3
"""Validate that a DimOS MCP tool listing contains the PawGuide edge tools."""

from __future__ import annotations

import argparse
import json
import sys

REQUIRED_TOOLS = {
    "begin_exploration",
    "emergency_stop",
    "end_exploration",
    "execute_sport_command",
    "navigate_to_waypoint",
    "start_patrol",
    "stop_navigation",
    "stop_patrol",
    "tag_location",
}
PHYSICAL_MINIMUM_TOOLS = {
    "emergency_stop",
    "execute_sport_command",
    "navigate_to_waypoint",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--physical-minimal", action="store_true")
    args = parser.parse_args()

    try:
        document = json.load(sys.stdin)
        if isinstance(document, list):
            tools = document
        else:
            tools = document["result"]["tools"]
        names = {
            tool["name"]
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        if not args.quiet:
            print("Invalid DimOS MCP tool listing.", file=sys.stderr)
        return 1

    required = PHYSICAL_MINIMUM_TOOLS if args.physical_minimal else REQUIRED_TOOLS
    missing = sorted(required - names)
    if missing:
        if not args.quiet:
            print(f"Missing DimOS tools: {', '.join(missing)}", file=sys.stderr)
        return 1

    if not args.quiet:
        for name in sorted(required):
            print(f"PASS  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
