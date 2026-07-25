# PawGuide airport showcase concept

**Showcase date:** 26 July 2026
**Target duration:** 60–90 seconds, never more than two minutes
**Hardware:** Unitree Go2 Air with RDK X5 edge computer and Pixel 9 Pro
**Status:** concept only; this document does not authorize physical motion

## 1. Product idea

PawGuide is an accessible robotic airport guide. A traveler activates a nearby
robot dog through the PawGuide app or a connected ring. The traveler selects or
speaks a destination, and PawGuide guides them to the correct gate. During the
walk, the traveler can ask for an accessible toilet, coffee, water, assistance
desk, or another mapped point of interest.

The concept is especially useful for travelers who find airport navigation
difficult, including older travelers and blind or low-vision travelers. The
ring provides an easy-to-find button, push-to-talk interaction, haptic feedback,
and a physical guide handle. It is a guidance interface, not a steering device
or weight-bearing mobility aid.

The showcase should communicate three ideas in one short experience:

1. PawGuide can be activated without operating the robot directly.
2. It can guide a traveler safely along a mapped route.
3. It has a friendly, accessible personality and can answer questions while
   walking.

## 2. Scope of tomorrow's demo

The venue demo is a small, rehearsed airport scene rather than an open-ended
autonomous navigation demonstration.

The robot starts at a waypoint named `home`, travels approximately five metres
to a waypoint named `demo_gate`, presents a physical gate sign, says goodbye,
returns to `home`, sits, and re-enters its fail-closed idle state.

The demo uses:

- one level, barrier-protected walking lane;
- two exact, pre-recorded waypoints: `home` and `demo_gate`;
- one activation through the app, with the ring as an input when its connection
  is reliable;
- one short spoken interaction;
- one known Go2 `Hello` gesture for both greeting and farewell;
- a human operator confirming arrival at the gate and at home;
- a nearby safety spotter with an immediately available STOP control.

The demo does not include:

- free roaming through the audience;
- arbitrary destinations or raw velocity control;
- person following;
- stairs, escalators, lifts, or multiple floors;
- an improvised detour through the crowd;
- an LLM deciding whether the robot may arm, stop, or move;
- unsupported or newly discovered Unitree sport commands;
- a visitor using the ring as a load-bearing handle.

## 3. Visitor experience

### Idle

PawGuide waits seated at `home`, facing the visitor area. The app shows
“PawGuide is ready” and invites the visitor to press the ring button or the
on-screen **Start guide** button.

The desired product behavior is a slow, occasional look to the left and right,
which makes the robot appear attentive. The current PawGuide command allowlist
does not contain a verified idle-look gesture. Therefore:

- for tomorrow, the safe default is to remain seated and still;
- an idle movement may be used only if it has first been implemented as one
  exact, bounded action and passed the same physical tests as `Hello`;
- raw velocity commands or arbitrary sport commands must not be used to create
  an idle animation.

### Activation

The visitor presses the ring or app button. The app acknowledges the action
visually and, where supported, with a ring vibration. The presenter explicitly
approves/arms the operator session; a visitor button press must not silently
release a latched STOP.

PawGuide stands, performs the verified `Hello` gesture, and the Pixel says:

> Hello! I am PawGuide. I will show you to your gate.

### Guided walk

PawGuide starts navigating to `demo_gate` at the lowest speed already proven
safe for the mapped lane. The visitor walks beside or behind it, outside the
leg envelope.

At roughly the middle of the route, the presenter asks:

> PawGuide, where can I get a coffee?

For this short demo, PawGuide gives a curated response without changing the
route:

> There is a coffee point close to the gate. I can guide you there next.

This demonstrates conversational assistance without adding a risky detour. In
the airport product, toilets, coffee shops, service desks, and gates become
separate exact waypoints selected by the route planner.

### Gate arrival

The `demo_gate` waypoint is recorded with the robot facing the gate sign. This
orientation, the sign, and the spoken message create the pointing effect
without introducing an unverified pointing command.

After visually confirming that navigation has stopped, the operator advances
the demo. PawGuide says:

> We have arrived. Your gate is right here. Have a good flight!

It performs the verified `Hello` gesture as a farewell wave.

### Return to idle

PawGuide returns to `home`. After the operator confirms that it has arrived and
is stationary, it sits down. The app sends STOP, verifies that STOP is latched,
ends the heartbeat, and shows “Ready for the next traveler.”

## 4. Show sequence

| Time | Visitor-facing action | Current PawGuide action | Safety condition |
|---:|---|---|---|
| Before start | Robot waits seated | Pre-position at `home`, `sit_down`, then `stop` | STOP is latched |
| 0–5 s | Ring/app activation | Start local heartbeat; presenter explicitly sends `reset_stop` | App, ring, gateway, and spotter are ready |
| 5–15 s | Stand, greet, introduction | `stand_up`, then `greeting` | Wait for each physical action |
| 15–40 s | Guide toward the gate | `go_to_waypoint` with `demo_gate` | Clear lane; heartbeat remains fresh |
| 25–35 s | Coffee question and answer | Curated speech; no motion change | No cloud response is allowed to alter safety state |
| 40–55 s | Present the gate | Human confirms arrival, then `pause` | Never advance on a timer alone |
| 55–65 s | Farewell wave | Pixel TTS, then `greeting` | Robot is stationary |
| 65–90 s | Return and sit | `return_home`; confirm arrival; `pause`; `sit_down`; `stop` | Final state is STOP-latched |

The show controller must not infer physical completion from an HTTP
`accepted=true` response. In the current API that response means the command
was accepted and dispatched, not that the robot has reached its destination or
finished a gesture.

## 5. Architecture using the current PawGuide stack

```text
Ring
button / microphone / future haptics
                |
                v
Pixel 9 Pro PawGuide app
visitor UI, audio, TTS, deterministic STOP,
operator heartbeat and scripted demo controller
                |
                | local USB-tether network
                | authenticated PawGuide HTTP API
                v
RDK X5 8 GB
FastAPI safety gateway + mission supervisor
                |
                | loopback-only MCP
                v
DimOS
LCM streams, lidar mapping, obstacle-aware navigation,
exact waypoint skill and bounded Unitree commands
                |
                | sole LocalAP WebRTC connection
                v
Unitree Go2 Air (192.168.12.1)

Cloud / China development services
airport data, optional language services, monitoring and development access
                |
                | Tailscale; never the real-time safety heartbeat
                v
RDK X5 PawGuide API
```

### Responsibility split

**Ring**

- produces a button/push-to-talk event;
- provides microphone audio when its protocol is available;
- may acknowledge states with haptics;
- never sends motor commands and is not an emergency stop.

**Pixel app**

- owns the visitor experience and spoken audio;
- validates ring connectivity and app foreground state;
- sends the operator heartbeat every 500 ms;
- handles STOP and arming deterministically, outside AI;
- runs the short demo state machine;
- validates every proposed destination against gateway capabilities;
- reuses a command UUID if an uncertain HTTP request is retried.

For tomorrow, the phone microphone and on-screen button are the fallback if the
ring BLE/audio integration is not fully commissioned.

**Cloud**

- can perform airport-data lookup, destination resolution, analytics, and
  heavier conversational processing;
- can propose only high-level intents such as “go to gate A12” or “find
  coffee”;
- cannot create the safety heartbeat, release STOP, or issue raw motion;
- is not required for the rehearsed showcase script.

The current repository also defines LiteRT-LM on the Pixel as a future local
inference option. That remains useful as an offline fallback in airports, but
tomorrow's demo should use fixed local phrases and curated facts. A busy venue
is the wrong place to make motion or the core story depend on cloud latency.

**RDK X5**

- is the only normal control bridge to the Go2;
- runs the FastAPI gateway, fail-closed supervisor, and watchdog;
- rejects commands while STOP is latched or the operator heartbeat is stale;
- exposes only exact actions and exact allowlisted waypoint IDs;
- talks to DimOS over loopback MCP;
- keeps safety and navigation local even if the internet, Tailscale, cloud, or
  Pixel AI is unavailable.

**DimOS**

- runs on the X5 using LCM and a headless configuration;
- owns lidar-based mapping, obstacle-aware navigation, and Go2 control;
- stores exact waypoint poses atomically in
  `/var/lib/pawguide/waypoints.json`;
- maps `greeting` only to the reviewed Unitree `Hello` command;
- receives STOP through a redundant local stop sequence.

**China/Hetzner development services and Tailscale**

- support deployment, diagnostics, simulation, and a secondary STOP path;
- do not own the operator heartbeat;
- do not proxy the Go2 WebRTC session;
- are not runtime dependencies for the physical show.

## 6. Existing app API

The current FastAPI gateway on the X5 already provides the small app-facing API
needed for the assisted demo.

| Endpoint | Purpose | Access |
|---|---|---|
| `GET /health` | Check adapter and real-motion capability | Public on the private interface |
| `GET /v1/capabilities` | Read actions, exact waypoints, and watchdog timing | Operator or developer token |
| `GET /v1/state` | Read STOP, heartbeat, mission state, and active waypoint | Operator or developer token |
| `POST /v1/heartbeat` | Maintain the local operator safety lease | Operator token only |
| `POST /v1/commands` | Submit one idempotent allowlisted command | Operator or developer token, with role restrictions |

Heartbeat payload:

```json
{
  "source": "pixel-ring-operator"
}
```

Example activation command:

```json
{
  "command_id": "9921f88d-04c4-44e9-830f-a83fcfddf8a1",
  "action": "reset_stop",
  "arguments": {}
}
```

Example gate command:

```json
{
  "command_id": "3411c2be-1761-49eb-8870-9d7bf20b8119",
  "action": "go_to_waypoint",
  "arguments": {
    "waypoint_id": "demo_gate"
  }
}
```

The demo needs only these existing actions:

- `reset_stop`
- `stand_up`
- `greeting`
- `go_to_waypoint`
- `pause`
- `return_home`
- `sit_down`
- `stop`

`start_patrol` exists but should not be used in the crowded showcase.

### App state machine

```text
DISCONNECTED
    |
    | health + capabilities + state are valid
    v
CONNECTED_STOPPED
    |
    | ring/app requests activation
    | presenter explicitly approves, heartbeat is fresh, reset_stop accepted
    v
GREETING
    |
    | stand and Hello have visibly completed
    v
GUIDING_TO_GATE
    |
    | operator confirms arrival and robot is stationary
    v
AT_GATE
    |
    | speech and farewell gesture complete
    v
RETURNING_HOME
    |
    | operator confirms arrival and robot is stationary
    v
SITTING -> STOP_LATCHED -> CONNECTED_STOPPED
```

From any active state:

```text
STOP button, heartbeat loss, app/ring/link loss, adapter error
    -> X5 latches STOP
    -> demo enters RECOVERY
    -> no automatic re-arm
```

### Known API gap

The current supervisor records `navigating` when a waypoint command is
dispatched, but it does not consume DimOS navigation progress or expose an
arrival event. The same limitation applies to detecting completion of a
physical gesture.

For tomorrow, use explicit operator confirmation at `demo_gate` and `home`.
Do not sequence arrival speech, a paw gesture, sitting, or return navigation
using only fixed delays.

After the showcase, the clean extension is normalized mission progress from
DimOS through the gateway, for example:

```json
{
  "mission_state": "arrived",
  "active_waypoint": "demo_gate",
  "navigation": {
    "status": "succeeded"
  }
}
```

The Pixel should consume normalized gateway state, not raw MCP frames. This
extension is not required for the operator-assisted showcase and is not part
of this concept-only change.

## 7. Booth map and waypoint setup

### Physical layout

Use a straight or gently curved route of approximately five metres. A practical
starting layout is a two-metre-wide lane enclosed with stanchions, but the
final width must be based on the measured robot footprint, leg sweep, turn
radius, tested stopping distance, and venue rules.

```text
Audience side

  app/ring activation
          |
          v
  [home] =============================== [demo_gate]
  robot       protected walking lane       gate sign
    ^                                            |
    |                                            |
  operator                                  safety spotter

No visitor enters the protected motion lane.
```

The sign should be slightly beyond or beside `demo_gate`, so the robot can stop
with clearance while facing it. Do not place the waypoint against a wall,
table, cable, glass surface, stair edge, or audience barrier.

### Map scope

Only map the booth lane and a safety margin around it. A full venue or airport
map is unnecessary and increases the chance of an untested route.

Record:

- `home`: the seated waiting pose, with enough space to stand and turn;
- `demo_gate`: the arrival pose, oriented toward the gate sign.

An optional `demo_coffee` waypoint can be added in a later rehearsal only if it
remains inside the protected lane and the total sequence stays below two
minutes. It is not needed for the primary show.

Configure the exact allowlist as:

```text
PAWGUIDE_WAYPOINTS=home,demo_gate
```

Unknown, misspelled, and corrupt waypoints must continue to fail closed.

### Mapping and rehearsal order

1. Clear the booth and establish the physical lane before visitors arrive.
2. Verify lidar/odometry health and create the smallest usable local map.
3. Place the robot exactly at `home` and tag it using the existing setup-only
   waypoint tool.
4. Place it at the gate pose, face the sign, and tag `demo_gate`.
5. Test STOP while stationary.
6. Test `home` to `demo_gate` with no audience and the lowest proven speed.
7. Test `demo_gate` to `home`.
8. Test an obstacle placed safely in the lane and confirm that the robot stops
   rather than leaving the protected area.
9. Run the complete show sequence repeatedly with the operator and spotter.
10. Do not move a sign, barrier, table, waypoint, or major lidar-visible object
    after the final rehearsal without remapping and retesting.

## 8. Safety concept

PawGuide's software is deliberately fail-closed:

- startup actively dispatches STOP and leaves it latched;
- movement requires a fresh local heartbeat and explicit `reset_stop`;
- the Pixel/operator heartbeat is sent every 500 ms;
- heartbeat loss latches STOP on the X5 within two seconds;
- closing the operator session requests STOP;
- STOP can be issued with either operator or developer credentials;
- only exact actions and allowlisted waypoint IDs are accepted;
- raw velocity and arbitrary Unitree sport commands are unavailable;
- the Go2 connection and navigation remain local to the X5.

This is not equivalent to a hardware emergency stop. The repository records
that no Unitree remote controller or hardware emergency stop is available.
Therefore public movement requires all of the following:

- a closed motion lane with no audience inside it;
- one dedicated operator and one dedicated spotter;
- the spotter close enough to intervene without entering the leg sweep;
- a local STOP control already open and tested;
- a second terminal with `disable-real-motion.sh` prepared;
- the X5 readiness check passing with no unresolved failure;
- supported-off-ground posture tests passing;
- floor greeting and heartbeat-loss tests passing;
- mounting, power, cooling, strap, and cable-retention checks passing;
- both waypoint routes passing repeatedly in the final booth layout;
- a stationary fallback ready at all times.

If a person enters the lane, the map changes, lidar is degraded, the route
deviates, the heartbeat becomes stale, the app disconnects, or the operator is
uncertain, press STOP. Do not automatically re-arm. Clear the cause, return the
robot to `home` manually when safe, and start a new supervised session.

## 9. Accessibility principles

The public story should emphasize independence without overstating the current
prototype.

- Use speech, large high-contrast controls, and haptics for the same important
  states.
- Make activation a large, single-purpose control rather than a gesture that
  requires precision.
- Announce “starting,” “stopping,” “arrived,” and “connection lost.”
- Keep speech short and repeatable in a noisy venue.
- Do not rely on color alone in the app.
- Keep the ring button physically distinguishable by touch.
- Keep STOP available on the app even while speech or cloud processing is
  running.
- Never let AI reinterpret the emergency word “stop.”
- Describe the ring as a guidance handle only after its mechanical load,
  entanglement, release, and gait interaction have been tested.

For tomorrow, blind or low-vision visitors should be accompanied by staff and
should not hold a moving prototype unless the complete handle and walking
interaction has already passed a dedicated physical assessment. Production
development should include blind travelers, orientation-and-mobility
specialists, airport accessibility teams, and older travelers from the start.

## 10. Readiness and fallback plan

The repository status dated 25 July 2026 records:

- the X5 production gateway is still in non-moving `mock` mode;
- end-to-end simulation has passed;
- physical supported-off-ground motion is the next gated milestone;
- ring transport, mapping, mounting, and local AI are not yet accepted for
  public use.

Accordingly, the moving showcase is available only if every physical gate is
completed before the event. Being able to send a command is not evidence that
the complete public demo is safe.

Use three prepared show modes:

### Mode A — full supervised route

Use only after all physical, mounting, watchdog, mapping, and route tests pass.
The app/ring triggers the assisted sequence, the operator confirms both
arrivals, and the spotter owns STOP.

### Mode B — stationary robot interaction

Keep the robot seated or supported with real locomotion disabled. Demonstrate
ring/app activation, spoken airport assistance, the app state machine, the
five-metre route on a screen or simulator, and—only if separately proven—the
single `Hello` gesture.

### Mode C — complete simulation

Keep the physical gateway in `mock` mode and show the already prepared
Hyper.ai/MuJoCo route alongside the real hardware. This still communicates the
app/API/cloud/edge architecture and preserves the physical robot for
conversation and photographs.

The presenter should decide the active mode before doors open. Do not upgrade
from a fallback mode during a crowded public session after an unresolved test.

## 11. Success criteria

The demo succeeds when a visitor can understand the PawGuide idea in under two
minutes and the system ends safely:

- activation is clear and accessible;
- the robot performs only rehearsed actions;
- the route stays inside the protected lane;
- the coffee question receives a short, relevant answer;
- the gate is unmistakable at arrival;
- the farewell feels friendly;
- the robot returns home, sits, and finishes with STOP latched;
- loss of app, ring, network, heartbeat, or cloud cannot continue motion;
- the stationary or simulated fallback tells the same product story if real
  movement is not ready.

The most important design principle is that PawGuide may be intelligent in how
it understands a traveler, but it must remain deliberately limited and
predictable in how it moves.
