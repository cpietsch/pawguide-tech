"""Small Hetzner-side client for the PawGuide edge application bridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from uuid import uuid4

import httpx

from pawguide.models import Action
from pawguide.secrets import read_secret


def _settings() -> tuple[str, str]:
    gateway_url = os.getenv("PAWGUIDE_GATEWAY_URL")
    if not gateway_url:
        raise RuntimeError("PAWGUIDE_GATEWAY_URL must be set")
    dev_token = read_secret("PAWGUIDE_DEV_TOKEN")
    return gateway_url.rstrip("/"), dev_token


def _request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gateway_url, dev_token = _settings()
    response = httpx.request(
        method,
        f"{gateway_url}{path}",
        headers={"Authorization": f"Bearer {dev_token}"},
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _command(action: Action, **arguments: Any) -> dict[str, Any]:
    return _request(
        "POST",
        "/v1/commands",
        payload={
            "command_id": str(uuid4()),
            "action": action.value,
            "arguments": arguments,
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call the PawGuide edge bridge through Tailscale."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("state", "stop", "pause", "patrol", "home"):
        subparsers.add_parser(command)
    goto = subparsers.add_parser("goto")
    goto.add_argument("waypoint_id")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "state":
            result = _request("GET", "/v1/state")
        elif args.command == "stop":
            result = _command(Action.STOP)
        elif args.command == "pause":
            result = _command(Action.PAUSE)
        elif args.command == "patrol":
            result = _command(Action.START_PATROL)
        elif args.command == "home":
            result = _command(Action.RETURN_HOME)
        elif args.command == "goto":
            result = _command(Action.GO_TO_WAYPOINT, waypoint_id=args.waypoint_id)
        else:  # pragma: no cover - argparse guarantees the choices
            raise AssertionError("unreachable")
    except (RuntimeError, httpx.HTTPError) as exc:
        print(f"pawguide-client: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result, indent=2, sort_keys=True))
