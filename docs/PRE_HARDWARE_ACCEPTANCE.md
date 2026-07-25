# Simulated pre-hardware acceptance

This is the authoritative hardware-free qualification for the PawGuide concept.
It exercises the real X5 fail-closed gateway, China relay, Hyper DimOS planner,
MuJoCo scene, and live telemetry. It does **not** authorize physical Go2
motion.

## Qualified topology

```text
operator command and 500 ms heartbeat
  -> X5 fail-closed gateway :8876
  -> China MCP relay :9991
  -> Hyper DimOS planner and MuJoCo
  -> live pose and path telemetry
  -> X5 watchdog and redundant STOP
```

The selected clear fixture is `concept_gate`. It contains only the two exact
show waypoints:

- `home = (0.0, -2.5, 0.295)`
- `demo_gate = (3.6, 0.9698703145794942, 0.295)`

Their planar separation is exactly 5.0 m. The protected arena is
`x=-0.4..4.0, y=-2.9..1.3698703145794942`. The separate
`concept_gate_blocked` fixture uses the same endpoints and seals the complete
lane with a planner-visible and rendered wall; there is no simulated bypass.
Fixture definitions are in `config/mujoco-fixtures.json`.

`DIMOS_MUJOCO_KINEMATIC_DRIVE=1` is an explicit simulator-only compatibility
proxy. The upstream locomotion policy did not reliably turn the simulated
body in this container, so the proxy integrates the planner's bounded planar
commands while retaining the real mapping, planning, gateway, watchdog, and
telemetry path. Never enable it for a physical robot.

## Authoritative result

The consolidated report is
`artifacts/concept-pre-hardware-acceptance.json`. It passed all four simulation
gates on 2026-07-26:

| Gate | Result | Live evidence |
| --- | --- | --- |
| Complete show | PASS | 5 m outbound and return sequence in 66.128 s; stationary arrival and exact waypoint orientation at both ends; zero protected-corridor path or trajectory exits |
| Sealed lane | PASS | Safe refusal in 11.229 s; no path, bypass, barrier crossing, or arrival claim; maximum displacement 0.003 m |
| Failure matrix | PASS | Heartbeat-loss STOP observed in 1.609 s; stale reset, bad waypoint, raw velocity, role, idempotency, and no-auto-rearm checks passed |
| Endurance | PASS | 50/50 consecutive legs, including heartbeat-loss injection on legs 10, 20, 30, 40, and 50; no service restart or observed resource degradation |

Every gate ended in the same strong invariant: mission `stopped`, STOP latched,
heartbeat stale, no active waypoint, and `last_stop_reason=operator_stop`.
The report embeds SHA-256 references to each source artifact:

- `artifacts/concept-show-acceptance.json`
- `artifacts/concept-gate-blocked-acceptance.json`
- `artifacts/concept-failure-matrix.json`
- `artifacts/soak/arena-qualification-20260726/soak-report.json`

An HTTP 200 or `navigation_started` response alone is never considered proof
of arrival or gesture completion.

## Reproduce and consolidate

Keep the operator token outside the repository in a mode-600 file:

```bash
export PAWGUIDE_OPERATOR_TOKEN_FILE=/secure/path/operator.token

uv run pawguide-show-acceptance
uv run pawguide-blocked-lane-acceptance
uv run pawguide-failure-matrix-acceptance
uv run pawguide-soak \
  --config config/simulation-soak.json \
  --artifact-dir artifacts/soak/arena-qualification-YYYYMMDD
uv run pawguide-concept-suite
```

Fixture selection and restoration are operational steps documented in
`docs/HYPER_SIMULATION.md`. Do not run the clear and blocked scenarios against
the wrong fixture. Each runner attempts an unconditional STOP in its cleanup
path and exits non-zero when a required gate fails.

The live operator view is:

- command center: `http://100.102.208.90:7780/command-center`
- full-screen 3D viewer:
  `http://100.102.208.90:9879/?url=rerun%2Bhttp%3A%2F%2F100.102.208.90%3A9879%2Fproxy`

The command center reads the consolidated artifact, not browser video. Rerun
is the primary visualization, which avoids sending unnecessary rendered image
frames through the China relay.

## Concept traceability

The simulation now proves the motion and gateway parts of `concept.md`:

- exact `home` and `demo_gate` allowlisting, with arbitrary destinations and
  raw velocity rejected;
- explicit arm, stand, greeting dispatch, five-metre navigation, stationary
  operator confirmation, farewell dispatch, return, sit, and final STOP;
- a complete sequence below the two-minute hard limit;
- commissioned endpoint position and orientation;
- protected-lane containment and fail-closed behavior when that lane is
  sealed;
- local heartbeat loss, authorization, validation, retry/idempotency, and
  endurance behavior.

Gesture confirmations in this report are simulator telemetry/operator
confirmations. They do not claim that a physical Go2 completed a sport action.
Likewise, the concept's fixed Pixel introduction, coffee answer, gate message,
and “Ready for the next traveler” state are specified deterministic product
content, but live Pixel audio, app accessibility, ring BLE/audio/haptics, and
cloud-independent interaction are integration gates, not locomotion claims.

## Still pending before physical motion

The following require the actual equipment and venue and remain explicitly
`pending_physical_hardware` in the aggregate report:

1. Go2 supported-off-ground posture and bounded gesture tests.
2. Go2 floor motion, measured stopping distance, and heartbeat-loss tests.
3. RDK X5 mounting, power, cooling, strap, and cable retention.
4. Final booth barriers, measured clearance, waypoint recording, and route
   rehearsal.
5. Ring mechanical load, entanglement, release, BLE, audio, and haptics.
6. A dedicated operator and spotter with local STOP and a stationary fallback.

Before the visitor experience is called complete, separately demonstrate the
Pixel's fixed phrases and coffee response without any motion-state change,
large accessible controls, ring/app fallback behavior, and deterministic STOP.
Simulation qualification is evidence for those later checks; it is not a
substitute for them.
