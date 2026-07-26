# Hyper.ai Go2 simulation

> Recovery order, current physical/simulation port isolation, and the
> tokenless admin installation are authoritative in
> [CURRENT_RECOVERY_RUNBOOK.md](CURRENT_RECOVERY_RUNBOOK.md). This document
> remains the detailed simulation engineering record.

## Current topology

As of 2026-07-25, the hardware-free Go2 test runtime is:

```text
browser
  |
  | private HTTP :7780
  v
China server (100.102.208.90)
  |  static physical command center -> X5 gateway :8765
  |  MCP :9991 -> SSH local forward -> Hyper MCP relay :9991
  |  Rerun :9879 -> SSH local forwards -> Hyper :9877/:9878
  |
  +---------------- SSH, persistent -------------------+
                                                       |
                                                       v
Hyper.ai GPU container
  DimOS + MuJoCo + Go2 policy + MCP + command center
                                                       ^
                                                       |
X5 safety gateway :8876 -> loopback MCP relay ---------+
```

All simulation compute runs on Hyper.ai. The China server is a thin relay so
the X5 and browser retain stable addresses. The X5 remains the gateway
boundary: its isolated simulation gateway owns heartbeat and STOP state. The
physical gateway on port 8765 is separate and must remain untouched by
simulation work.

## Endpoints

| Purpose | Endpoint |
| --- | --- |
| Hyper SSH | `ssh root@ssh.hyper.ai -p 31612` |
| Command center | `http://100.102.208.90:7780/command-center` |
| Live 3D viewer | `http://100.102.208.90:9879/?url=rerun%2Bhttp%3A%2F%2F100.102.208.90%3A9879%2Fproxy` |
| Relayed DimOS MCP | `http://100.102.208.90:9991/mcp` |
| X5 simulation gateway | `http://100.72.30.53:8876` |
| X5 physical gateway | `http://100.72.30.53:8765` |

Use the dedicated local key at `/root/.ssh/pawguide_gpu_server` for Hyper SSH.
Never commit the private key.

## Why Hyper is relayed

The Hyper.ai workload is a container whose PID 1 is `runsvdir`. It has no
`/dev/net/tun` and cannot run kernel-mode Tailscale. Direct Tailscale
enrollment is therefore not part of the active runtime. The persistent SSH
tunnel from the China server provides the stable tailnet ingress instead.

## Hyper runtime

The copied DimOS source is at `/opt/pawguide-dimos` and the Python environment
is `/opt/pawguide-venv`. Runit supervises:

```text
/etc/service/pawguide-dimos
/etc/service/pawguide-mcp-relay
```

The DimOS command is:

```bash
/opt/pawguide-venv/bin/dimos \
  --transport zenoh \
  --simulation mujoco \
  --mujoco-steps-per-frame 5 \
  --viewer rerun \
  --rerun-open none \
  --rerun-web \
  --rerun-host 127.0.0.1 \
  --memory-limit 4GB \
  --listen-host 127.0.0.1 \
  --mcp-port 9990 \
  run unitree-go2 unitree-skill-container paw-guide-waypoint-skill mcp-server
```

The service runs MuJoCo under Xvfb because NVIDIA EGL starts but exits before
publishing telemetry in the Hyper.ai container. Its `LD_LIBRARY_PATH` includes
the CUDA 13 and cuDNN wheel libraries in the environment. ONNX Runtime uses
the CUDA execution provider and DimOS voxel mapping reports `CUDA:0`; only
MuJoCo rendering uses the software/Xvfb compatibility path.

The Hyper-only service also sets `DIMOS_MUJOCO_KINEMATIC_DRIVE=1`. The bundled
Go1 ONNX locomotion policy did not reliably turn the simulated body even
though the planner published correct angular commands. This explicit
simulation proxy integrates planner velocity commands into the planar MuJoCo
pose so the gateway, planner, mapping, collision scene and telemetry can be
accepted end to end. Never enable it in a physical Go2 service.

The service defaults to the commissioned `engineering_short` fixture. The
five-metre concept course is separately selected by installing
`provision/hyper/fixtures/concept-gate.env` as the root-owned
`/etc/pawguide/pawguide-dimos.env`, installing
`provision/hyper/fixtures/concept-gate-waypoints.json` as
`/var/lib/pawguide/waypoints.json`, and restarting `pawguide-dimos`. Its exact
poses are `home=(0.0, -2.5)` and
`demo_gate=(3.6, 0.9698703145794942)`. This exact five-metre diagonal fits
the observed robot-centred costmap extent
`x=-4.075..4.275, y=-6.625..1.525`. Its 0.4-metre-margin arena is
`x=-0.4..4.0, y=-2.9..1.3698703145794942`, and the direct lane is the clear
protected route used for the complete, time-bounded show. Fixture
selection also places the MuJoCo base at that fixture's exact `home` position
at the final process initialization, overriding all three coordinates after
the upstream CLI start and robot-height defaults are resolved. The CLI's
default `(-1, 1)` start is therefore not used for either concept fixture.
Path smoothing preserves the commissioned goal quaternion exactly. Identity
`[0,0,0,1]` is intentional waypoint orientation, not a sentinel to replace
with the final travel direction.

The simulation-only local-planner linear cap is `0.4 m/s`, an accessible
walking pace that gives the five-metre out-and-back show timing margin. The
simulation lookahead remains `0.1 m`: it is intentionally short for fidelity
to the protected lane and is not raised with the speed cap. Physical/default
planning remains at its upstream `0.55 m/s` cap and `0.5 m` lookahead.

When the explicit MuJoCo kinematic proxy is enabled, in-place rotation has a
simulation-only `1.5 rad/s` minimum so final commissioned yaw can settle
despite slower-than-real-time rendering throughput. The nonkinematic
simulator retains its `0.8 rad/s` floor, and physical control is unchanged.

Simulation uses a `0.15 m` position goal tolerance in both global and local
planning, with replan tolerance no larger than the goal tolerance. This gives
the external `0.20 m` acceptance gate margin for telemetry noise. Physical
and default planning retain the upstream `0.20 m` tolerance.

`concept_gate_blocked` is a separate negative-test fixture selected with the
correspondingly named environment and waypoint files. Its rendered and
planner-visible wall spans the same narrow lane from boundary to boundary,
and it deliberately has no bypass. A run against it must fail closed with a
STOP and must not leave the protected lane; it is not a detour-and-arrive
test. Restore the correspondingly named engineering files to return to the
short course. Fixture geometry is tracked in `config/mujoco-fixtures.json`.

For deterministic simulation, a selected fixture owns its arena costmap:
incoming UNKNOWN, FREE, or OCCUPIED cells inside the arena are replaced with
FREE before the arena border and explicit fixture obstacles are rasterized.
Apartment-scene walls therefore cannot silently obstruct the clear concept
lane, while cells outside the fixture arena remain unchanged.

DimOS has undeclared runtime requirements that were needed during migration:

- `torch`;
- `langchain-core`;
- `git-lfs`;
- the `unitree_go1` and `unitree_go2` MuJoCo menagerie assets;
- the DimOS `mujoco_sim` LFS data archive.

Do not remove these merely because the active blueprint is named
`unitree-go2`: the current DimOS MuJoCo backend uses the Go1 simulation model
and policy for this Go2-facing test adapter.

## China relay

Systemd supervises `pawguide-hyper-tunnel.service`. It forwards:

```text
127.0.0.1:17779       -> Hyper 127.0.0.1:7779
127.0.0.1:9877        -> Hyper Rerun gRPC 127.0.0.1:9877
127.0.0.1:9878        -> Hyper Rerun web 127.0.0.1:9878
100.102.208.90:9991   -> Hyper 127.0.0.1:9991
```

Nginx listens on `100.102.208.90:7780` and serves the tracked physical command
center. Its fallback route proxies Hyper's DimOS web surface through
`127.0.0.1:17779`. Rerun is exposed separately on `:9879`.

Check the relay with:

```bash
systemctl status pawguide-hyper-tunnel.service
nginx -t
curl -fsS http://100.102.208.90:7780/command-center >/dev/null
curl -fsS -X POST http://100.102.208.90:9991/mcp \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' |
  jq '.result.tools | length'
```

The expected MCP tool count for this blueprint is 17.

## X5 simulation path

The isolated services are:

```text
pawguide-sim-mcp-relay.service
pawguide-sim-gateway.service
```

The X5 relay listens only on `127.0.0.1:9992` and targets
`100.102.208.90:9991`. Port `127.0.0.1:9990` is reserved exclusively for the
physical DimOS MCP server. Check both gateways:

```bash
curl -fsS http://100.72.30.53:8876/health
curl -fsS http://100.72.30.53:8765/health
```

Expected adapters are `dimos_mcp` with motion capability on both ports. Their
MCP backends must remain isolated: simulation uses `:9992`; physical uses
`:9990`.

The isolated simulation gateway sets `PAWGUIDE_DIMOS_MCP_TIMEOUT_S=15` because
its loopback relay crosses China to Hyper and STOP deliberately invokes several
DimOS cleanup tools. The physical gateway also uses 15 seconds because its
bounded commissioning route runs longer than five seconds.

The migration acceptance sequence passed end to end:

```text
STOP -> reset/arm -> hello -> STOP
```

The final state was `STOPPED`, `stop_latched=true`, with
`last_stop_reason=operator_stop`.

The complete concept-level pre-hardware gate is documented in
`docs/PRE_HARDWARE_ACCEPTANCE.md`; its consolidated machine-readable evidence
is `artifacts/concept-pre-hardware-acceptance.json`.

## Operations

The command center is a tokenless physical-control kiosk. It
proxies the existing X5 API while storing the required X5 operator credential
only in a root-owned nginx include on the China server:

- `/admin/api/sim/` forwards to the isolated simulation gateway on `:8876`;
- `/admin/api/physical/` forwards to the physical/production gateway on
  `:8765`;
- `/admin/api/physical/` receives its Authorization header from the generated
  `/etc/pawguide/nginx-operator-auth.conf`;
- the browser never receives or asks for the operator token;
- Rerun remains at its separate simulation-only URL and is not embedded in the
  physical kiosk;
- STOP remains available once authenticated and connected, independent of the
  heartbeat state.

The physical kiosk exposes Stand, Sit, Hello, Pause, the bounded one-metre
round trip, and the large red STOP. Simulation remains available through the
isolated `:8876` gateway and its dedicated engineering tools.

On Hyper:

```bash
sv status /etc/service/pawguide-dimos
sv status /etc/service/pawguide-mcp-relay
nvidia-smi
```

On the China server:

```bash
systemctl status pawguide-hyper-tunnel.service
systemctl status nginx
```

On the X5:

```bash
systemctl status pawguide-sim-mcp-relay.service
systemctl status pawguide-sim-gateway.service
systemctl status pawguide-gateway.service
```

Live Rerun is served through the China server's same-origin mux on port 9879.
The browser must use port 9879 for both the viewer document and the encoded
`rerun+http://...:9879/proxy` data URL. Direct browser access to Hyper's 9877
gRPC endpoint causes a cross-origin preflight failure.

`observe` and simulated battery state may return `None`. Sport-command
dispatch, MCP registration, command-center transport and the X5 safety path
are verified; do not interpret missing simulated battery telemetry as a real
Go2 readiness result.

## Recovery

Restore the tracked Hyper runit scripts and one matching fixture/environment
pair, then restart both runit services. The complete package, credential,
relay, and verification sequence is in
[`CURRENT_RECOVERY_RUNBOOK.md`](CURRENT_RECOVERY_RUNBOOK.md).

Never run two simulators behind the same `100.102.208.90:9991` endpoint.
