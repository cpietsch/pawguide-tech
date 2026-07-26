# PawGuide product and prototype scope

PawGuide is an accessible guide-robot concept for airports and other complex
public venues. A traveler uses the PawGuide phone app or a connected ring to
request a destination, receive spoken guidance, and follow a Unitree Go2 along
a prepared route.

The ring is an interaction device, not a steering control or weight-bearing
mobility aid. The phone and ring application is maintained in a separate
repository and consumes only PawGuide's authenticated HTTP API.

## Product experience

The intended event flow is:

1. PawGuide waits at `home`.
2. The traveler starts a guide session from the app or ring.
3. The robot stands and performs its reviewed greeting.
4. It guides the traveler to an allowlisted destination.
5. The app announces arrival.
6. PawGuide returns home, sits, latches STOP, and ends the operator heartbeat.

The public product should provide the same important state through speech,
large high-contrast controls, and haptics. STOP must remain available while
audio or language processing is active. AI may propose a destination or
dialogue response, but it cannot create the safety heartbeat, release STOP, or
issue raw motion.

## Implemented prototype

The current physical prototype is deliberately narrower than the product
experience:

- the RDK X5 is the only normal Go2 WebRTC peer;
- the X5 exposes a fail-closed HTTP gateway and watchdog;
- the current direct physical bridge supports stand, sit, greeting, STOP, and
  the exact waypoint IDs `home` and `demo_gate`;
- `demo_gate` is a bounded open-loop movement approximately one metre from
  `home`, not mapped navigation;
- an accepted HTTP command confirms dispatch, not physical completion;
- the browser command center maintains the heartbeat and gives a human direct
  control over every action;
- the qualified five-metre obstacle-aware course exists only in the
  Hyper.ai/MuJoCo simulation.

The current prototype does not support arbitrary destinations, free roaming,
person following, crowd detours, stairs, lifts, escalators, or raw velocity
control.

## Runtime responsibility split

```text
phone/ring app
    |
    | authenticated PawGuide HTTP API
    v
RDK X5 gateway and watchdog
    |
    | loopback MCP
    v
direct Go2 bridge
    |
    | LocalAP WebRTC
    v
Unitree Go2

China command center ---- authenticated HTTP ----> X5 gateway
China relay <---------- simulation only ---------- Hyper.ai/MuJoCo
```

The phone/ring app owns the visitor interface, audio, and scripted interaction.
The X5 owns the physical safety lease and Go2 connection. The China server
provides development, monitoring, and browser control but does not replace the
X5 watchdog. Hyper provides the hardware-free simulation.

## App-facing API

The complete machine-readable contract is
[`../contracts/pawguide-openapi.json`](../contracts/pawguide-openapi.json).
The supported surface is:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Adapter and motion-capability check |
| `GET /v1/capabilities` | Actions, waypoints, and watchdog timing |
| `GET /v1/state` | STOP, heartbeat, mission, and active-waypoint state |
| `POST /v1/heartbeat` | Maintain the operator safety lease |
| `POST /v1/commands` | Submit an idempotent allowlisted action |

Clients must reuse a command UUID when retrying an uncertain request. They must
read capabilities rather than assume a waypoint or action exists. From any
active app state, STOP, heartbeat loss, app loss, or an adapter error enters a
recovery state with no automatic re-arm.

The detailed client rules are in
[`PIXEL_CLIENT.md`](PIXEL_CLIENT.md).

## Retained simulation evidence

The final simulation qualification demonstrates the intended larger course:

- 50/50 repeated navigation legs;
- five live heartbeat-loss injections;
- the complete five-metre out-and-back show sequence;
- safe refusal of a sealed lane;
- authorization, validation, idempotency, and no-auto-rearm checks.

Those results do not prove physical navigation. The authoritative evidence and
remaining physical gates are recorded in
[`PRE_HARDWARE_ACCEPTANCE.md`](PRE_HARDWARE_ACCEPTANCE.md).

## Future product work

Product development still requires normalized motion-completion events, mapped
physical navigation, final app/ring integration, venue-specific accessibility
testing, and a suitable physical STOP and operating procedure. These are
product milestones, not hidden capabilities of the current deployment.
