"""Fail-closed manual operator console for the first PawGuide motion tests."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from typing import Any
from uuid import uuid4

import httpx

from pawguide.models import Action
from pawguide.secrets import read_secret


class ManualOperator:
    """Maintain the local heartbeat while issuing allowlisted commands.

    The gateway watchdog remains authoritative. A lost console, SSH session or
    HTTP link stops refreshing the heartbeat, which latches STOP at the edge.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
        heartbeat_period_s: float = 0.5,
        heartbeat_fresh_s: float = 1.25,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(timeout=2.0)
        self._owns_client = client is None
        self._heartbeat_period_s = heartbeat_period_s
        self._heartbeat_fresh_s = heartbeat_fresh_s
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_lock = threading.Lock()
        self._last_heartbeat: float | None = None
        self._closed = False

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.request(
            method,
            f"{self._base_url}{path}",
            headers=self.headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("gateway returned a non-object response")
        return body

    def heartbeat(self) -> dict[str, Any]:
        body = self._request(
            "POST",
            "/v1/heartbeat",
            payload={"source": "manual_operator_console"},
        )
        with self._heartbeat_lock:
            self._last_heartbeat = time.monotonic()
        return body

    def heartbeat_is_fresh(self) -> bool:
        with self._heartbeat_lock:
            last_heartbeat = self._last_heartbeat
        return (
            last_heartbeat is not None
            and time.monotonic() - last_heartbeat < self._heartbeat_fresh_s
        )

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self._heartbeat_period_s):
            try:
                self.heartbeat()
            except (httpx.HTTPError, RuntimeError, ValueError):
                # The edge watchdog stops the robot. Keep retrying so a brief
                # local transport failure can recover without a new process.
                continue

    def start(self) -> None:
        if self._heartbeat_thread is not None:
            raise RuntimeError("manual operator session already started")
        self.heartbeat()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="pawguide-manual-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def state(self) -> dict[str, Any]:
        return self._request("GET", "/v1/state")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def command(self, action: Action, **arguments: Any) -> dict[str, Any]:
        if action is not Action.STOP and not self.heartbeat_is_fresh():
            raise RuntimeError(
                "local heartbeat is stale; the command was not submitted"
            )
        return self._request(
            "POST",
            "/v1/commands",
            payload={
                "command_id": str(uuid4()),
                "action": action.value,
                "arguments": arguments,
            },
        )

    def close(self) -> dict[str, Any] | None:
        if self._closed:
            return None
        self._closed = True
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=self._heartbeat_period_s + 0.5)
        stop_result: dict[str, Any] | None = None
        try:
            stop_result = self.command(Action.STOP)
        except (httpx.HTTPError, RuntimeError, ValueError):
            # Heartbeat loss still causes the gateway watchdog to latch STOP.
            pass
        finally:
            if self._owns_client:
                self._client.close()
        return stop_result

    def __enter__(self) -> ManualOperator:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def _parse_action(line: str) -> tuple[Action, dict[str, Any]]:
    parts = line.strip().split()
    if not parts:
        raise ValueError("empty command")
    name = parts[0].lower()
    if name == "arm" and len(parts) == 1:
        return Action.RESET_STOP, {}
    if name == "stand" and len(parts) == 1:
        return Action.STAND_UP, {}
    if name == "sit" and len(parts) == 1:
        return Action.SIT_DOWN, {}
    if name == "hello" and len(parts) == 1:
        return Action.GREETING, {}
    if name == "pause" and len(parts) == 1:
        return Action.PAUSE, {}
    if name == "patrol" and len(parts) == 1:
        return Action.START_PATROL, {}
    if name == "home" and len(parts) == 1:
        return Action.RETURN_HOME, {}
    if name == "stop" and len(parts) == 1:
        return Action.STOP, {}
    if name == "goto" and len(parts) == 2:
        return Action.GO_TO_WAYPOINT, {"waypoint_id": parts[1]}
    raise ValueError("unknown command or wrong number of arguments")


def _print_json(document: dict[str, Any]) -> None:
    print(json.dumps(document, indent=2, sort_keys=True))


def run_console(operator: ManualOperator) -> None:
    capabilities = operator.capabilities()
    waypoints = ", ".join(capabilities.get("allowed_waypoints", []))
    print("PawGuide manual console: no LLM is active.")
    print(f"Allowlisted waypoints: {waypoints or '(none)'}")
    print(
        "Commands: state, arm, stand, sit, hello, goto <id>, "
        "pause, patrol, home, stop, help, quit"
    )
    print("Leaving this console always requests STOP.")

    while True:
        try:
            line = input("pawguide> ").strip()
        except EOFError:
            print()
            return
        if not line:
            continue
        if line in {"quit", "exit"}:
            return
        if line == "help":
            print(
                "state | arm | stand | sit | hello | goto <id> | "
                "pause | patrol | home | stop | quit"
            )
            continue
        if line == "state":
            try:
                _print_json(operator.state())
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                print(f"state failed: {exc}", file=sys.stderr)
            continue
        try:
            action, arguments = _parse_action(line)
            _print_json(operator.command(action, **arguments))
        except ValueError as exc:
            print(f"{exc}; type 'help'", file=sys.stderr)
        except (httpx.HTTPError, RuntimeError) as exc:
            print(f"command failed: {exc}", file=sys.stderr)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local no-LLM PawGuide operator console."
    )
    parser.add_argument(
        "--gateway-url",
        default=os.getenv("PAWGUIDE_GATEWAY_URL", "http://127.0.0.1:8765"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        token = read_secret("PAWGUIDE_OPERATOR_TOKEN")
    except RuntimeError as exc:
        print(f"pawguide-operator: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    def interrupt_console(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    for signal_name in ("SIGHUP", "SIGTERM"):
        selected_signal = getattr(signal, signal_name, None)
        if selected_signal is not None:
            signal.signal(selected_signal, interrupt_console)

    operator = ManualOperator(args.gateway_url, token)
    try:
        with operator:
            run_console(operator)
    except KeyboardInterrupt:
        print("\nStopping PawGuide...")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"pawguide-operator: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        operator.close()


if __name__ == "__main__":
    main()
