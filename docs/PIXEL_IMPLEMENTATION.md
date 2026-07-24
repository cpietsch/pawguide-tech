# Pixel local-AI implementation choice

Deferred while the X5 no-LLM motion and navigation tests are in progress.

Decision recorded on 2026-07-24:

- Use Google AI Edge Gallery to benchmark candidate models on the actual Pixel.
- Build the PawGuide app against the stable LiteRT-LM Kotlin API, pinned to
  `com.google.ai.edge.litertlm:litertlm-android:0.14.0`.
- Use GPU first. Treat NPU as a later optimization because it requires
  device-specific native libraries.
- Set `automaticToolCalling=false`. The model may propose a tool call, but only
  PawGuide application code may validate and execute it.
- Do not expose heartbeat, reset-stop or STOP as model tools.

The official Android guide documents background engine initialization, Kotlin
Flow streaming, GPU native-library declarations, OpenAPI tools and manual tool
calling:

<https://developers.google.com/edge/litert-lm/android>

AI Edge Gallery is the official model sandbox and reference app:

<https://github.com/google-ai-edge/gallery>

## Why Gallery is not the PawGuide runtime

Gallery is excellent for measuring load time, time-to-first-token and output
quality on the Pixel. It is not the operator safety host: PawGuide also needs
the ring transport, USB gateway discovery, a foreground heartbeat, a latched
arming state, deterministic STOP, schema validation and idempotent command
submission.

The PawGuide app owns those pieces and embeds LiteRT-LM as one replaceable
inference component.

## Engine skeleton

Initialize on a background coroutine before allowing a conversation:

```kotlin
val config = EngineConfig(
    modelPath = modelPath,
    backend = Backend.GPU(),
    cacheDir = context.cacheDir.path,
)
val engine = Engine(config)
engine.initialize()
```

The Android manifest must declare the optional GPU libraries inside
`<application>`:

```xml
<uses-native-library android:name="libvndksupport.so" android:required="false"/>
<uses-native-library android:name="libOpenCL.so" android:required="false"/>
```

Register only these model-visible actions:

- `go_to_waypoint(waypoint_id)`
- `pause()`
- `start_patrol()`
- `return_home()`

The waypoint parameter is generated from the authenticated
`GET /v1/capabilities` response. Configure the conversation with
`automaticToolCalling=false`, inspect returned tool calls, reject unknown names
or arguments, normalize the proposal through
`contracts/local-agent-output.schema.json`, then translate it to the PawGuide
HTTP contract. The LiteRT tool object's `execute` method must never call the
gateway.

The host sends the tool result back to the conversation only after the gateway
returns `accepted=true`. A rejected command becomes a short spoken failure, not
a retry with broader authority.

## Model selection gate

Use `pixel/model-evaluation.json` in Gallery Prompt Lab against:

1. the smallest tool-capable FunctionGemma model available for command routing;
2. a roughly 1B instruction model for richer tour speech;
3. one larger model only if load time and thermals remain acceptable.

Measure:

- cold model load;
- warm time-to-first-token;
- total structured response time;
- valid-output rate across all evaluation cases;
- RAM use and temperature after 30 minutes;
- behavior with airplane mode enabled.

For the MVP, reliability wins over conversational range. Tour facts should come
from a small curated local content pack; the model phrases that content rather
than inventing venue facts.

## Build blockers

The generic host architecture is frozen. Completing the Android app requires:

- the ring BLE/audio/haptic protocol;
- the physical Pixel for backend/model benchmarking;
- the USB-tether address or discovery behavior seen when the Pixel is connected
  to an X5 USB-A host port.

Until the ring handoff arrives, use the Pixel microphone and an on-screen
hold-to-talk control against exactly the same state machine.
