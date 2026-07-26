# Physical Go2 handoff

> **Current deployment:** use
> [CURRENT_RECOVERY_RUNBOOK.md](CURRENT_RECOVERY_RUNBOOK.md). The material
> below records the earlier full-DimOS commissioning design and is not the
> active lightweight physical profile.

This is the operational handoff from the qualified simulation to the physical
Unitree Go2 Air. The X5 is connected to the robot and the real adapter is
running, but the gateway remains deliberately fail-closed until an operator
starts the heartbeat and explicitly arms it.

## Prepared state

As verified on 2026-07-26:

- X5 is online over Tailscale and uses Pixel USB tethering for its default
  route;
- production gateway `:8765` is active with the physical `dimos_mcp` adapter;
- physical MCP is active with the direct posture, STOP, and bounded-route
  toolset;
- simulation gateway `:8876` remains independent and operational;
- the current physical allowlist is exactly `home,demo_gate`;
- the DimOS Go2 import succeeds with the pinned PyYAML dependency;
- physical enablement now runs the complete `--require-physical` readiness
  gate before starting DimOS or switching the gateway adapter;
- the command center is a tokenless kiosk with bounded physical controls and a
  large STOP button;
- the target Wi-Fi is `Go_62554`; the X5 has joined it and received
  `192.168.12.13/24`;
- live routing and ping verified that this unit's LocalAP control address is
  `192.168.12.1`; the separately supplied `10.88.15.7` address is not
  reachable on this AP and is not used by the physical runtime;
- its root-owned NetworkManager profile and root-owned Unitree credential are
  installed on the X5 without storing either secret in this repository.

No physical waypoint pose has been fabricated from simulation. `home` and
`demo_gate` must be recorded from the real robot at the venue.

## Remaining physical input

The supplied network and AES information is installed, association and routing
are verified, and the software readiness gate passes. The supplied MAC did not
match the Wi-Fi BSSID, so the saved profile uses the exact SSID rather than an
incorrect BSSID lock. After physical confirmation of the support stand, clear
leg envelope, charged battery, X5 power/cooling, operator, spotter, and
immediate STOP access, the real adapter was enabled. The gateway remains
STOP-latched with no heartbeat and no active waypoint; enabling the adapter
did not arm the robot.

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

This command starts the direct physical MCP bridge, verifies the current
minimal physical toolset, switches the production gateway to `dimos_mcp`, and
leaves STOP latched. A failure rolls back to mock mode.

The X5 installer pins the official ARM CPU build of Torch. Do not replace it
with the default PyPI ARM package, which resolves a large CUDA 13 stack that is
not used by this control path. Pixel owns showcase audio, so PulseAudio is
disabled by default in the headless physical service.

LCM multicast, its loopback route, and receive buffers are prepared by the
separate root-only `pawguide-lcm-network.service`. DimOS itself remains
unprivileged and may use netlink only for read-only network checks. The
physical runtime and gateway were verified active with isolated loopback ports
before operator handoff.

Confirm:

```bash
curl -fsS http://127.0.0.1:8765/health
```

Expected:

```json
{"status":"ok","adapter":"dimos_mcp","motion_capable":true}
```

Then use `http://100.102.208.90:7780/command-center`. China nginx supplies the
X5 operator credential; the browser does not ask for or receive it. Follow the
current procedure in `docs/CURRENT_RECOVERY_RUNBOOK.md`.

## Historical exact-waypoint commissioning API

The API below belongs to the full navigation profile and is not exposed by the
current direct physical MCP bridge. The current `demo_gate` ID means the
bounded one-metre commissioning route documented in the recovery runbook.

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
the gateway, and disables physical DimOS. The direct physical STOP uses Damp;
keep physical support available throughout the posture test.
