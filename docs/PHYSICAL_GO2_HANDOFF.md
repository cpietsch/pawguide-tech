# Physical Go2 handoff

This is the operational handoff from the qualified simulation to the physical
Unitree Go2 Air. The X5 is prepared but remains deliberately fail-closed until
the robot is present.

## Prepared state

As verified on 2026-07-26:

- X5 is online over Tailscale and uses Pixel USB tethering for its default
  route;
- production gateway `:8765` is active in `mock` mode with motion disabled;
- physical DimOS is installed but inactive and disabled;
- simulation gateway `:8876` remains independent and operational;
- the current physical allowlist is exactly `home,demo_gate`;
- the DimOS Go2 import succeeds with the pinned PyYAML dependency;
- physical enablement now runs the complete `--require-physical` readiness
  gate before starting DimOS or switching the gateway adapter;
- the command center contains the bounded physical controls, per-tab
  interlock, readiness checklists, and guarded exact-waypoint recording.
- the target unit is tracked as `Go2 62554`, with supplied robot address
  `10.88.15.7`; that address is configuration, not assumed from the usual
  `192.168.12.1` LocalAP default;
- its root-owned NetworkManager profile and root-owned Unitree credential are
  installed on the X5 without storing either secret in this repository.

No physical waypoint pose has been fabricated from simulation. `home` and
`demo_gate` must be recorded from the real robot at the venue.

## Remaining physical input

The supplied network and AES information is installed. The robot still needs
to be powered and within Wi-Fi range. The X5 has not yet observed the supplied
BSSID or reached `10.88.15.7`, so real motion remains disabled. Physical
confirmation of the support stand, clear leg envelope, charged battery, X5
power/cooling, operator, spotter, and immediate STOP access is also required.

Do not paste passwords or the AES key into chat or shell arguments. Enter them
only into the hidden/local prompts below.

## Connect the robot

When the robot is powered, the saved profile should autoconnect. On the X5:

```bash
ssh sunrise@100.72.30.53
sudo /opt/pawguide/bin/check-x5-readiness.sh --require-physical
```

The readiness command must finish with zero failures. Specifically verify that
the configured robot address routes over `wlan0`, while the default route
remains on Pixel USB/Ethernet.

## Supported-off-ground enable

Only with the Go2 physically supported, feet clear, official app closed, and a
spotter ready:

```bash
sudo /opt/pawguide/bin/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
```

This command starts physical DimOS, verifies every required MCP tool, switches
the production gateway to `dimos_mcp`, and leaves STOP latched. A failure rolls
back to mock mode.

Confirm:

```bash
curl -fsS http://127.0.0.1:8765/health
```

Expected:

```json
{"status":"ok","adapter":"dimos_mcp","motion_capable":true}
```

Then use `http://100.102.208.90:7780/command-center`, select the physical
gateway, connect with the operator token, and follow
`docs/FIRST_MOTION_TEST.md`.

## Exact waypoint commissioning API

The app does not need direct DimOS access. With an operator token, a fresh
heartbeat, STOP still latched, and the robot visually confirmed stationary:

```http
POST /v1/commissioning/waypoints/home
Authorization: Bearer <operator-token>
Content-Type: application/json

{"confirm_stationary":true}
```

Use the same route with `demo_gate`. Non-allowlisted names, a stale heartbeat,
a released STOP, invalid confirmation, or a non-operator token fail closed.
The admin command center exposes this as **Record current pose**.

## Immediate rollback

At any time:

```bash
sudo /opt/pawguide/bin/disable-real-motion.sh
```

This sends a best-effort redundant STOP, restores the mock adapter, restarts
the gateway, and disables physical DimOS. STOP does not force a standing Go2
to sit; keep physical support available throughout the posture test.
