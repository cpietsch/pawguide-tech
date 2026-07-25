# Simulated pre-hardware acceptance

This gate validates the complete application path before the physical Go2 is
available:

```text
operator heartbeat and command
  -> X5 fail-closed gateway :8876
  -> China MCP relay :9991
  -> Hyper DimOS planner
  -> MuJoCo proxy drive
  -> live pose telemetry
  -> X5 heartbeat-loss STOP
```

It does not certify physical locomotion, traction, onboard obstacle avoidance,
the Go2 network link, battery telemetry, or an emergency stop under load.

## Scenario

Hyper stores two commissioned exact waypoints in
`/var/lib/pawguide/waypoints.json`:

- `home`: simulator startup position;
- `demo_a`: approximately 1.2 metres from home.

The target and thresholds used by automation are tracked in
`config/simulation-acceptance.json`. Recommission the file and the saved
waypoint together if the scene or start position changes.

The upstream Go1 ONNX locomotion policy receives planner commands but does not
reliably turn the simulated body in this container. Hyper therefore sets
`DIMOS_MUJOCO_KINEMATIC_DRIVE=1`. This opt-in MuJoCo-only proxy integrates
planner velocity commands into a planar pose while keeping the sensor,
mapping, planning, gateway and telemetry path real. It must never be enabled
for the physical Go2 runtime.

## Pass criteria

`pawguide-acceptance` requires all of the following:

1. Ten X5 simulation health requests report `dimos_mcp` and
   `motion_capable=true`.
2. Gateway health p95 latency is no more than 750 ms.
3. `demo_a` is present in the X5 waypoint allowlist.
4. The initial STOP dispatch succeeds.
5. Live Socket.IO pose telemetry is present.
6. A fresh operator heartbeat and explicit `reset_stop` arm the gateway.
7. The waypoint command is accepted as `navigation_started`.
8. The simulator moves at least 0.5 m and arrives within 0.2 m of `demo_a`.
9. Removing the heartbeat latches STOP with
   `operator_heartbeat_timeout` within three seconds.
10. An unconditional final STOP succeeds and the final state is latched.

An HTTP 200 or a `navigation_started` response alone is not a pass.

## Run

The X5 must be online. Keep the operator token in its existing root-owned file
or another protected local file:

```bash
export PAWGUIDE_OPERATOR_TOKEN_FILE=/secure/path/operator.token
uv run pawguide-acceptance \
  --report artifacts/pre-hardware-acceptance.json
```

The command exits non-zero on any failed gate and still attempts STOP in its
`finally` path. Preserve the generated JSON as the timestamped evidence for a
specific run.

## Verified result

The full gate passed on 2026-07-25. The tracked evidence is
`artifacts/pre-hardware-acceptance.json` with SHA-256:

```text
cf972558bcbe999527b673416c3f479c7d4a203fd271f5e3b14f5318d21d3bff
```

All 19 checks passed. Gateway p95 latency was 43.27 ms, measured displacement
was 1.068 m, and arrival error was 0.047 m. Heartbeat loss latched STOP with
`operator_heartbeat_timeout`; the unconditional final STOP also passed. An
independent state read finished `STOPPED`, with `stop_latched=true`, no active
waypoint and a stale heartbeat.
