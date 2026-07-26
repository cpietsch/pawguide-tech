"""Fail-closed mission supervisor for the PawGuide edge computer."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
import threading
import time
from uuid import UUID

from pawguide.adapter import RobotAdapter
from pawguide.models import (
    Action,
    CommandEnvelope,
    CommandResult,
    MissionState,
    SupervisorSnapshot,
)


@dataclass(frozen=True)
class SupervisorConfig:
    allowed_waypoints: frozenset[str]
    allowed_actions: frozenset[Action] = frozenset(Action)
    home_waypoint: str = "home"
    operator_heartbeat_timeout_s: float = 2.0
    command_cache_size: int = 256


class SafetySupervisor:
    """Owns the movement permission and latches every safety stop.

    Startup is fail-closed. Movement becomes possible only after a current
    operator heartbeat and an explicit ``reset_stop`` command. A stop command is
    always honored, including when it is a duplicate or the heartbeat is stale.
    """

    def __init__(
        self,
        adapter: RobotAdapter,
        config: SupervisorConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if config.home_waypoint not in config.allowed_waypoints:
            raise ValueError("home_waypoint must be included in allowed_waypoints")
        self._adapter = adapter
        self._config = config
        self._clock = clock
        self._lock = threading.RLock()
        self._mission_lock = threading.Lock()
        self._stop_latched = True
        self._stop_epoch = 0
        self._mission_state = MissionState.STOPPED
        self._active_waypoint: str | None = None
        self._last_stop_reason = "startup_fail_closed"
        self._last_operator_heartbeat: float | None = None
        self._results: OrderedDict[UUID, CommandResult] = OrderedDict()
        # A process restart must actively cancel motion left behind by a
        # previous gateway instance; a software flag alone is not a stop.
        self._latch_stop("startup_fail_closed")

    @property
    def allowed_waypoints(self) -> frozenset[str]:
        return self._config.allowed_waypoints

    @property
    def allowed_actions(self) -> frozenset[Action]:
        return self._config.allowed_actions

    @property
    def operator_heartbeat_timeout_s(self) -> float:
        return self._config.operator_heartbeat_timeout_s

    def heartbeat(self) -> SupervisorSnapshot:
        with self._lock:
            self._last_operator_heartbeat = self._clock()
            return self.snapshot()

    def snapshot(self) -> SupervisorSnapshot:
        with self._lock:
            return SupervisorSnapshot(
                stop_latched=self._stop_latched,
                operator_heartbeat_fresh=self._heartbeat_fresh(),
                mission_state=self._mission_state,
                active_waypoint=self._active_waypoint,
                last_stop_reason=self._last_stop_reason,
            )

    def check_watchdog(self) -> SupervisorSnapshot:
        """Latch a stop when the operator safety heartbeat expires."""
        with self._lock:
            should_stop = not self._heartbeat_fresh() and not self._stop_latched
        if should_stop:
            self._latch_stop("operator_heartbeat_timeout")
        return self.snapshot()

    def submit(self, command: CommandEnvelope) -> CommandResult:
        if command.action is Action.STOP:
            with self._lock:
                cached = self._results.get(command.command_id)
                if cached is not None:
                    return cached
            result = self._handle_stop(command)
            with self._lock:
                self._remember(result)
            return result

        # Serialize mission changes, but never make STOP wait behind a slow
        # navigation transport call.
        with self._mission_lock:
            return self._submit_non_stop(command)

    def _submit_non_stop(self, command: CommandEnvelope) -> CommandResult:
        heartbeat_was_stale = False
        result: CommandResult | None = None
        with self._lock:
            cached = self._results.get(command.command_id)
            if cached is not None:
                return cached

            if command.action not in self._config.allowed_actions:
                result = self._reject(command, "action_not_allowed")
            elif command.action is Action.RESET_STOP:
                result = self._handle_reset(command)
            elif self._stop_latched:
                result = self._reject(command, "stop_is_latched")
            elif not self._heartbeat_fresh():
                heartbeat_was_stale = True
                result = None
            else:
                prepared = self._prepare_motion_locked(command)
                if isinstance(prepared, CommandResult):
                    self._remember(prepared)
                    return prepared
                operation, next_state, waypoint, success_reason = prepared
                stop_epoch = self._stop_epoch

            if result is not None:
                self._remember(result)
                return result

        if heartbeat_was_stale:
            self._latch_stop("operator_heartbeat_timeout")
            with self._lock:
                result = self._reject(command, "operator_heartbeat_is_stale")
                self._remember(result)
                return result

        try:
            operation()
        except Exception:
            self._latch_stop("adapter_error")
            with self._lock:
                result = self._reject(command, "adapter_error_stop_latched")
                self._remember(result)
                return result

        with self._lock:
            stop_interrupted = self._stop_latched or self._stop_epoch != stop_epoch
            heartbeat_expired = not self._heartbeat_fresh()
            if not stop_interrupted and not heartbeat_expired:
                self._mission_state = next_state
                self._active_waypoint = waypoint
                result = self._accept(command, success_reason)
                self._remember(result)
                return result

        # Re-dispatch after the in-flight call has returned. This guarantees a
        # STOP wins even if the robot transport processed the calls out of order.
        stop_reason = (
            "operator_heartbeat_timeout"
            if heartbeat_expired
            else "stop_during_adapter_call"
        )
        self._latch_stop(stop_reason)
        with self._lock:
            result = self._reject(command, stop_reason)
            self._remember(result)
            return result

    def _handle_stop(self, command: CommandEnvelope) -> CommandResult:
        dispatched = self._latch_stop("operator_stop")
        with self._lock:
            if not dispatched:
                return self._reject(command, "stop_latched_but_dispatch_failed")
            return self._accept(command, "stop_latched")

    def _handle_reset(self, command: CommandEnvelope) -> CommandResult:
        self._require_no_arguments(command)
        if not self._heartbeat_fresh():
            return self._reject(command, "fresh_operator_heartbeat_required")
        self._stop_latched = False
        self._mission_state = MissionState.IDLE
        self._active_waypoint = None
        return self._accept(command, "stop_reset")

    def _prepare_motion_locked(
        self, command: CommandEnvelope
    ) -> tuple[Callable[[], None], MissionState, str | None, str] | CommandResult:
        if command.action is Action.PAUSE:
            self._require_no_arguments(command)
            return self._adapter.pause, MissionState.PAUSED, None, "mission_paused"
        if command.action is Action.STAND_UP:
            self._require_no_arguments(command)
            return self._adapter.stand_up, MissionState.IDLE, None, "stand_up_sent"
        if command.action is Action.SIT_DOWN:
            self._require_no_arguments(command)
            return self._adapter.sit_down, MissionState.IDLE, None, "sit_down_sent"
        if command.action is Action.GREETING:
            self._require_no_arguments(command)
            return self._adapter.greeting, MissionState.IDLE, None, "greeting_sent"
        if command.action is Action.GO_TO_WAYPOINT:
            self._require_exact_arguments(command, {"waypoint_id"})
            waypoint_id = command.arguments["waypoint_id"]
            if not isinstance(waypoint_id, str):
                return self._reject(
                    command,
                    "waypoint_id_must_be_a_string",
                )
            if waypoint_id not in self._config.allowed_waypoints:
                return self._reject(command, "waypoint_not_allowed")
            return (
                lambda: self._adapter.go_to_waypoint(waypoint_id),
                MissionState.NAVIGATING,
                waypoint_id,
                "navigation_started",
            )
        if command.action is Action.START_PATROL:
            self._require_no_arguments(command)
            return (
                self._adapter.start_patrol,
                MissionState.PATROLLING,
                None,
                "patrol_started",
            )
        if command.action is Action.RETURN_HOME:
            self._require_no_arguments(command)
            return (
                self._adapter.return_home,
                MissionState.RETURNING,
                self._config.home_waypoint,
                "returning_home",
            )
        raise ValueError(f"unsupported action: {command.action}")

    def _latch_stop(self, reason: str) -> bool:
        with self._lock:
            self._stop_latched = True
            self._stop_epoch += 1
            stop_epoch = self._stop_epoch
            self._mission_state = MissionState.STOPPED
            self._active_waypoint = None
            self._last_stop_reason = reason
        try:
            self._adapter.emergency_stop(reason)
        except Exception:
            with self._lock:
                if self._stop_epoch == stop_epoch:
                    self._last_stop_reason = f"{reason}:emergency_stop_dispatch_failed"
            return False
        return True

    def _heartbeat_fresh(self) -> bool:
        if self._last_operator_heartbeat is None:
            return False
        age = self._clock() - self._last_operator_heartbeat
        return age <= self._config.operator_heartbeat_timeout_s

    def _accept(self, command: CommandEnvelope, reason: str) -> CommandResult:
        return CommandResult(
            command_id=command.command_id,
            accepted=True,
            state=self._mission_state,
            reason=reason,
        )

    def _reject(self, command: CommandEnvelope, reason: str) -> CommandResult:
        return CommandResult(
            command_id=command.command_id,
            accepted=False,
            state=self._mission_state,
            reason=reason,
        )

    def _remember(self, result: CommandResult) -> None:
        self._results[result.command_id] = result
        self._results.move_to_end(result.command_id)
        while len(self._results) > self._config.command_cache_size:
            self._results.popitem(last=False)

    @staticmethod
    def _require_no_arguments(command: CommandEnvelope) -> None:
        SafetySupervisor._require_exact_arguments(command, set())

    @staticmethod
    def _require_exact_arguments(
        command: CommandEnvelope, expected: Iterable[str]
    ) -> None:
        expected_set = set(expected)
        actual_set = set(command.arguments)
        if actual_set != expected_set:
            raise ValueError(
                f"{command.action.value} requires exactly these arguments: "
                f"{sorted(expected_set)}"
            )
