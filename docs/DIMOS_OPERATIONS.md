# DimOS operating guide for PawGuide

This is the PawGuide-specific distillation of DimOS `docs/usage`. The bundled
source is pinned to commit `4a78e1400c4334c280970e4610c655d16b9661ae`.
The upstream usage documentation had no changes between that revision and
upstream `main` at `2ec2ba43d4683bfedbce2e643a821243b7cbff37` when reviewed on
2026-07-24.

## Decisions taken from the usage documentation

- Compose the runtime from blueprints instead of creating another robot SDK
  layer: `unitree-go2`, `unitree-skill-container`,
  `paw-guide-waypoint-skill`, and `mcp-server`.
- Make the edge settings explicit. The X5 uses LCM for its local multiprocess
  streams, a headless viewer, the Go2 AP address, and `LocalAP`.
- Keep the X5 safety gateway as the WAN boundary. `Dimos.connect()` discovers a
  daemon on an LCM bus and is useful for local development, but it is not the
  authenticated Hetzner-to-X5 application protocol.
- Use MCP only on X5 loopback. The PawGuide gateway exposes a smaller,
  authenticated, allowlisted API over Tailscale.
- Run DimOS in the foreground under systemd. DimOS's own `--daemon` registry
  and lifecycle commands are for CLI-owned processes, not this service.
- Use replay, stream inspection, structured service logs and MCP
  introspection as the hardware bring-up ladder.

## Runtime command

The installed service executes:

```bash
/opt/dimos/bin/dimos \
  --transport lcm \
  --viewer none \
  --robot-ip 192.168.12.1 \
  --unitree-webrtc-connection-method local_ap \
  run unitree-go2 unitree-skill-container paw-guide-waypoint-skill mcp-server \
  --disable perceive-loop-skill \
  --disable websocket-vis-module
```

The AES credential is injected by systemd and is intentionally absent above.
The explicit transport avoids depending on platform defaults. LCM stays inside
the X5; it is not forwarded through Tailscale. The command-center WebSocket
module is disabled because the headless X5 does not need a second local motion
UI or its extra worker.

DimOS configuration precedence is default, `.env`, environment, blueprint,
then CLI. The service's CLI flags therefore win. Before changing a module
option, inspect the supported paths:

```bash
/opt/dimos/bin/dimos \
  run unitree-go2 unitree-skill-container paw-guide-waypoint-skill mcp-server \
  --disable perceive-loop-skill \
  --help
```

Use `--option/-o module.field=value` only after validating the resulting
configuration in replay. Do not edit DimOS source just to tune a module field.

## Lifecycle and logs on the X5

Because systemd owns the foreground process, use:

```bash
sudo systemctl status pawguide-dimos.service
sudo systemctl restart pawguide-dimos.service
sudo journalctl -u pawguide-dimos.service -n 100 --no-pager
sudo journalctl -u pawguide-dimos.service -f
```

Do not use `dimos run --daemon`, `dimos status`, `dimos stop`, `dimos restart`
or `dimos log` for the X5 service. Those commands operate DimOS's per-user run
registry and may not see the systemd process.

Run the packaged read-only diagnostic after DimOS starts:

```bash
sudo /opt/pawguide/bin/diagnose-dimos-x5.sh
```

It prints only non-secret resolved settings, checks systemd and MCP, and
verifies every tool required by PawGuide.

## MCP and stream inspection

These commands connect to the loopback MCP server:

```bash
/opt/dimos/bin/dimos mcp status
/opt/dimos/bin/dimos mcp modules
/opt/dimos/bin/dimos mcp list-tools
```

`dimos mcp call` bypasses the PawGuide supervisor, heartbeat and waypoint
allowlist. Treat it as a commissioning interface, not an application API.
Never invoke a movement skill this way during normal operation.

To inspect local stream health interactively:

```bash
sudo -u pawguide /opt/dimos/bin/dimos spy --transport lcm
```

The table shows topic rate, bandwidth, message size and liveness. After finding
an exact typed topic, `dimos topic echo <topic>` can inspect its messages.

`dtop` is useful during the first 30-minute thermal and memory run:

```bash
sudo -u pawguide /opt/dimos/bin/dtop
```

Record every thermal zone exposed under `/sys/class/thermal` during the X5
acceptance soak. Watch for throttling, fan problems and service restarts while
DimOS, Wi-Fi and the gateway are loaded.

## Replay on Hetzner

Linux defaults to LCM, but DimOS recommends Zenoh for heavy replay. Use the
same lean blueprint as the X5:

```bash
cd /root/dimos
source .venv/bin/activate
dimos \
  --transport zenoh \
  --viewer none \
  --replay \
  run unitree-go2 unitree-skill-container paw-guide-waypoint-skill mcp-server \
  --disable perceive-loop-skill \
  --disable websocket-vis-module
```

From a second terminal:

```bash
cd /root/dimos
source .venv/bin/activate
dimos mcp status
dimos mcp modules
dimos mcp list-tools
```

For visual debugging, replace `--viewer none` with `--viewer rerun`. Keep any
web viewer private to localhost or the tailnet.

## Patterns reserved for the next iterations

- The current lean DimOS runtime does not use the X5 BPU. Add BPU perception
  only through a separately benchmarked X5 model adapter; keep navigation,
  heartbeat, arming and STOP deterministic. The S100 remains the later
  high-compute option.
- Camera/VLM work on the X5 should use backpressured streams so a slow model
  receives the latest frame without blocking camera or navigation consumers.
- Downsample camera input with `sharpness_barrier` rather than arbitrary frame
  sampling, and align camera/lidar messages by capture timestamp when adding
  3D explanations.
- Ring accelerometer gestures should be debounced before they become commands.
  A ReactiveX `throttle_first`-style rule fits this better than processing
  every sample.
- Long-running patrol or following skills can emit DimOS tool-stream progress,
  but the Pixel must receive normalized gateway state—not raw MCP frames.
- Sensor-level deterministic capture is available through
  `TimedSensorStorage`/`TimedSensorReplay`. Do not assume that merely starting
  DimOS creates a complete portable session recording; recording must be added
  explicitly to the relevant streams.
- Hot-restarting a module is useful while developing locally. Changes to
  stream declarations, module references, or blueprint membership still
  require a full service restart.

The complete upstream usage documents remain available inside the pinned DimOS
source at `/opt/dimos-src/docs/usage`.
