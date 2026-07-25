"""Wire models shared by PawGuide operator clients and the edge gateway."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Action(StrEnum):
    """The complete MVP command allowlist.

    There is intentionally no raw velocity or arbitrary sport-command action.
    """

    STOP = "stop"
    PAUSE = "pause"
    RESET_STOP = "reset_stop"
    STAND_UP = "stand_up"
    SIT_DOWN = "sit_down"
    GREETING = "greeting"
    GO_TO_WAYPOINT = "go_to_waypoint"
    START_PATROL = "start_patrol"
    RETURN_HOME = "return_home"


class MissionState(StrEnum):
    STOPPED = "stopped"
    IDLE = "idle"
    PAUSED = "paused"
    NAVIGATING = "navigating"
    PATROLLING = "patrolling"
    RETURNING = "returning"
    FAILED = "failed"


class CommandEnvelope(BaseModel):
    """A validated command produced by an authenticated operator client."""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    action: Action
    arguments: dict[str, Any] = Field(default_factory=dict)


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    accepted: bool
    state: MissionState
    reason: str


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=64)


class WaypointTagRequest(BaseModel):
    """Explicit human confirmation for a stationary commissioning write."""

    model_config = ConfigDict(extra="forbid")

    confirm_stationary: Literal[True]


class WaypointTagResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waypoint_id: str
    stored: Literal[True] = True
    detail: str


class SupervisorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_latched: bool
    operator_heartbeat_fresh: bool
    mission_state: MissionState
    active_waypoint: str | None
    last_stop_reason: str


class GatewayHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    adapter: str
    motion_capable: bool


class GatewayCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: str
    adapter: str
    motion_capable: bool
    operator_actions: list[Action]
    developer_actions: list[Action]
    allowed_waypoints: list[str]
    heartbeat_period_ms: int
    heartbeat_timeout_ms: int
