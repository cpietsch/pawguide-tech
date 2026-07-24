# Pixel client contract

This is a deferred interaction-stage contract. The first X5 motion test uses
the local `pawguide-operator` console and runs no LLM.

The Pixel owns the human interaction loop. It receives ring button events and
ring microphone audio, performs speech recognition and language inference
locally, speaks through the phone, and calls the X5 gateway over the USB-tether
network. The Pixel never opens a Unitree WebRTC session.

The physical data path is X5 USB-A host to Pixel USB-C. The X5 USB-C power
input remains dedicated to a stable 5 V/5 A supply.

The ring transport is intentionally an adapter boundary until its BLE/audio
protocol is specified. Accelerometer gestures are outside the first MVP.

The selected inference host is LiteRT-LM's stable Kotlin API, with AI Edge
Gallery used for model benchmarking rather than as the PawGuide safety app.
See `PIXEL_IMPLEMENTATION.md`.

## Authority split

| Operation | Pixel operator token | Hetzner developer token | Local model |
|---|---:|---:|---:|
| Heartbeat | yes | no | no |
| Reset stop latch | yes | no | no |
| STOP | yes | yes | bypassed |
| Pause, waypoint, patrol, home | yes | yes | proposes only |
| Raw velocity, arbitrary trick | unavailable | unavailable | unavailable |

The inference adapter produces only data matching
`contracts/local-agent-output.schema.json`. Native LiteRT-LM tool calls are
normalized to that shape; a model without native tool support must emit the
same shape directly. The Android host validates it, checks a requested waypoint
against `/v1/capabilities`, creates a UUID, and then calls `/v1/commands`. The
model is never given a generic HTTP or MCP tool.

## Operator state machine

```text
DISCONNECTED
    │ ring audio/button + USB gateway healthy
    ▼
CONNECTED_STOPPED ── heartbeat every 500 ms
    │ explicit operator arm action
    │ POST heartbeat, then RESET_STOP
    ▼
ARMED ── PTT → local ASR → deterministic safety router → local model
    │
    ├── STOP intent/button → POST STOP immediately, then speak
    ├── model command → validate schema + capabilities → POST command
    └── ring/USB/app loss → stop heartbeat → X5 latches stop ≤ 2 s
```

There is no inferred arming. Until the ring specification defines a deliberate
button gesture, the app must remain in `CONNECTED_STOPPED`. Arming, STOP,
heartbeat and stop reset are application logic and must never depend on model
output.

## PTT pipeline

1. Button down starts capture from the ring microphone and acknowledges locally
   when the ring protocol supports haptics.
2. Button release ends capture and runs on-device ASR.
3. Normalize the transcript. A direct STOP intent takes the deterministic STOP
   path before any LLM call.
4. Other input is passed to the local model with only the four allowlisted
   manual tools, or with the strict output schema for a non-tool model.
5. `reply` output goes only to on-device TTS.
6. `command` output is checked against current gateway capabilities and sent to
   the X5. Speak success only after `accepted=true`.

If inference fails, times out, emits invalid JSON or names an unavailable
waypoint, do not move. Speak a short failure response.

## HTTP contract

The generated API is `contracts/pawguide-openapi.json`. All protected requests
use:

```http
Authorization: Bearer <operator token>
Content-Type: application/json
```

On connection:

```text
GET /health
GET /v1/capabilities
GET /v1/state
```

The client must reject a deployment while `/health` reports
`motion_capable=false` if a physical-motion test is expected. The current
Hetzner and bundled X5 services intentionally report the mock adapter.

Heartbeat:

```json
{"source":"pixel-ring-operator"}
```

Send it to `POST /v1/heartbeat` every 500 ms using a monotonic scheduler. Do not
continue heartbeats while the ring link, USB gateway link, foreground operator
session or app safety state is unhealthy.

Command:

```json
{
  "command_id": "9921f88d-04c4-44e9-830f-a83fcfddf8a1",
  "action": "go_to_waypoint",
  "arguments": {"waypoint_id":"demo_a"}
}
```

Reuse the same `command_id` when retrying an uncertain HTTP response. The X5
caches recent results, preventing duplicate execution.

## Remaining ring-specific inputs

Implementation can begin when the ring handoff supplies:

- BLE service/characteristic UUIDs and button event encoding;
- microphone transport/profile, codec, sample rate and Android routing behavior;
- haptic command encoding;
- reconnect semantics and battery reporting;
- accelerometer sample/event format.

None of those details changes the X5 API or local-agent JSON schema.
