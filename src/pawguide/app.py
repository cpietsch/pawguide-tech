"""FastAPI entry point for the PawGuide edge safety gateway."""

from __future__ import annotations

from contextlib import asynccontextmanager
from enum import StrEnum
import os
from secrets import compare_digest
import threading
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import uvicorn

from pawguide import __version__
from pawguide.adapter import DimOSMcpAdapter, MockRobotAdapter
from pawguide.models import (
    Action,
    CommandEnvelope,
    CommandResult,
    GatewayCapabilities,
    GatewayHealth,
    Heartbeat,
    SupervisorSnapshot,
    WaypointTagRequest,
    WaypointTagResult,
)
from pawguide.secrets import read_secret
from pawguide.supervisor import SafetySupervisor, SupervisorConfig

_BEARER = HTTPBearer(auto_error=False)


def _waypoints_from_env() -> frozenset[str]:
    raw = os.getenv("PAWGUIDE_WAYPOINTS", "home,demo_a,demo_b")
    values = frozenset(value.strip() for value in raw.split(",") if value.strip())
    if "home" not in values:
        values = values | {"home"}
    return values


class Principal(StrEnum):
    OPERATOR = "operator"
    DEV = "dev"


def _tokens_from_env() -> tuple[str, str]:
    operator_token = read_secret("PAWGUIDE_OPERATOR_TOKEN")
    dev_token = read_secret("PAWGUIDE_DEV_TOKEN")
    if compare_digest(operator_token, dev_token):
        raise RuntimeError("operator and dev tokens must be different")
    return operator_token, dev_token


def _supervisor_from_env() -> tuple[SafetySupervisor, str, bool]:
    adapter_mode = os.getenv("PAWGUIDE_ADAPTER", "mock")
    if adapter_mode == "mock":
        adapter = MockRobotAdapter()
        motion_capable = False
    elif adapter_mode == "dimos_mcp":
        if os.getenv("PAWGUIDE_ENABLE_REAL_MOTION") != "YES":
            raise RuntimeError(
                "PAWGUIDE_ENABLE_REAL_MOTION=YES is required for dimos_mcp"
            )
        adapter = DimOSMcpAdapter(
            os.getenv(
                "PAWGUIDE_DIMOS_MCP_URL",
                "http://127.0.0.1:9990/mcp",
            ),
            timeout_s=float(os.getenv("PAWGUIDE_DIMOS_MCP_TIMEOUT_S", "5")),
        )
        motion_capable = True
    else:
        raise RuntimeError(f"unknown PAWGUIDE_ADAPTER: {adapter_mode}")

    supervisor = SafetySupervisor(
        adapter,
        SupervisorConfig(allowed_waypoints=_waypoints_from_env()),
    )
    return supervisor, adapter_mode, motion_capable


def create_app(
    *,
    supervisor: SafetySupervisor | None = None,
    operator_token: str | None = None,
    dev_token: str | None = None,
    adapter_mode: str = "mock",
    motion_capable: bool = False,
) -> FastAPI:
    if operator_token is None and dev_token is None:
        expected_operator_token, expected_dev_token = _tokens_from_env()
    elif operator_token is not None and dev_token is not None:
        expected_operator_token = operator_token
        expected_dev_token = dev_token
    else:
        raise ValueError("operator_token and dev_token must be supplied together")
    if compare_digest(expected_operator_token, expected_dev_token):
        raise ValueError("operator_token and dev_token must be different")

    if supervisor is None:
        active_supervisor, adapter_mode, motion_capable = _supervisor_from_env()
    else:
        active_supervisor = supervisor

    watchdog_stop = threading.Event()

    def watchdog_loop() -> None:
        while not watchdog_stop.is_set():
            active_supervisor.check_watchdog()
            watchdog_stop.wait(0.05)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        watchdog_stop.clear()
        watchdog = threading.Thread(
            target=watchdog_loop,
            name="pawguide-safety-watchdog",
            daemon=True,
        )
        watchdog.start()
        try:
            yield
        finally:
            watchdog_stop.set()
            watchdog.join(timeout=1)

    app = FastAPI(
        title="PawGuide Edge Safety Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.supervisor = active_supervisor

    def authorize(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(_BEARER),
        ],
    ) -> Principal:
        if credentials is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        supplied = credentials.credentials
        if compare_digest(supplied, expected_operator_token):
            return Principal.OPERATOR
        if compare_digest(supplied, expected_dev_token):
            return Principal.DEV
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    def require_operator(principal=Depends(authorize)) -> Principal:
        if principal is not Principal.OPERATOR:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        return principal

    @app.get("/health", response_model=GatewayHealth)
    def health() -> GatewayHealth:
        return GatewayHealth(
            adapter=adapter_mode,
            motion_capable=motion_capable,
        )

    @app.get(
        "/v1/capabilities",
        dependencies=[Depends(authorize)],
        response_model=GatewayCapabilities,
    )
    def capabilities() -> GatewayCapabilities:
        return GatewayCapabilities(
            api_version=__version__,
            adapter=adapter_mode,
            motion_capable=motion_capable,
            operator_actions=list(Action),
            developer_actions=[
                action for action in Action if action is not Action.RESET_STOP
            ],
            allowed_waypoints=sorted(active_supervisor.allowed_waypoints),
            heartbeat_period_ms=500,
            heartbeat_timeout_ms=round(
                active_supervisor.operator_heartbeat_timeout_s * 1000
            ),
        )

    @app.get(
        "/v1/state",
        dependencies=[Depends(authorize)],
        response_model=SupervisorSnapshot,
    )
    def state() -> SupervisorSnapshot:
        return active_supervisor.snapshot()

    @app.post(
        "/v1/heartbeat",
        dependencies=[Depends(require_operator)],
        response_model=SupervisorSnapshot,
    )
    def heartbeat(_heartbeat: Heartbeat) -> SupervisorSnapshot:
        return active_supervisor.heartbeat()

    @app.post(
        "/v1/commands",
        response_model=CommandResult,
    )
    def command(
        envelope: CommandEnvelope,
        principal=Depends(authorize),
    ) -> CommandResult:
        if envelope.action is Action.RESET_STOP and principal is not Principal.OPERATOR:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        try:
            return active_supervisor.submit(envelope)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    @app.post(
        "/v1/commissioning/waypoints/{waypoint_id}",
        dependencies=[Depends(require_operator)],
        response_model=WaypointTagResult,
    )
    def tag_waypoint(
        waypoint_id: str,
        _confirmation: WaypointTagRequest,
    ) -> WaypointTagResult:
        try:
            detail = active_supervisor.tag_waypoint(waypoint_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="waypoint_tagging_failed",
            ) from exc
        return WaypointTagResult(waypoint_id=waypoint_id, detail=detail)

    return app


def main() -> None:
    uvicorn.run(
        "pawguide.app:create_app",
        factory=True,
        host=os.getenv("PAWGUIDE_BIND_HOST", "0.0.0.0"),
        port=int(os.getenv("PAWGUIDE_PORT", "8765")),
    )
