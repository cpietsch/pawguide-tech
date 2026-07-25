# PawGuide

PawGuide is an autonomous event-guide prototype built from:

- a Unitree Go2 Air for sensing and locomotion;
- an RDK X5 8 GB for the current navigation and safety runtime;
- a Pixel 9 Pro for USB tethering now, and ring audio/TTS later;
- an RDK S100 12 GB/80 TOPS reserved for a later perception/local-AI upgrade.

The first physical milestone deliberately has no LLM. A local terminal console
on the X5 maintains the safety heartbeat and exposes only exact commands:
`stand`, `sit`, `hello`, `goto`, `pause`, `patrol`, `home` and `stop`.
Arbitrary velocity and arbitrary Unitree sport commands are not exposed.

## Runtime topology

```text
Hetzner / China development services
               |
           Tailscale
               |
Pixel USB tether -- RDK X5 -- Wi-Fi --> Go2 AP (192.168.12.1)
                       |
              gateway + DimOS + MCP
                       |
              local manual console
```

While the physical Go2 is unavailable, the active hardware-free path runs
DimOS and MuJoCo on a Hyper.ai GPU container. The China server provides stable
tailnet ingress for its command center and MCP endpoint, and the isolated X5
simulation gateway treats that endpoint as the robot. See
[Hyper.ai Go2 simulation](docs/HYPER_SIMULATION.md).

Only the X5 joins the Go2 access point and only the X5 opens a Unitree WebRTC
session. The Pixel does not run an LLM in this test phase. It supplies an
internet/Tailscale uplink over USB; an Ethernet uplink can be used on the bench.
The previously observed `10.88.15.7` address belongs to a different network
mode and is not used for Go2 `LocalAP`.

## Safety model

There is no Unitree remote controller, so the software starts fail-closed:

- the gateway boots with STOP latched and actively dispatches the stop sequence;
- the manual console sends a local heartbeat every 500 ms;
- movement requires a fresh heartbeat and an explicit `arm`;
- heartbeat loss latches STOP within two seconds;
- closing the console requests STOP immediately;
- STOP remains callable from a second Tailscale/SSH terminal;
- posture tests use exact `StandUp`, `Sit` and `Hello` commands;
- waypoint IDs are exact allowlisted values;
- neither Hetzner nor the China server owns the safety heartbeat;
- real motion requires a credential, reachable Go2, compatible hardware profile
  and an explicit danger acknowledgement on the X5.

This is not equivalent to a hardware emergency stop. Physical tests require a
clear area, a nearby spotter, the robot initially supported off the ground and
a second terminal already prepared to disable real motion.

## Prepared state

- Hetzner and China run Tailscale-only, fail-closed mock gateways.
- The DimOS patch supports Go2 `LocalAP`, direct emergency stop, exact persistent
  waypoints and the MCP tool bus.
- The X5 and future S100 have separate provisioning/readiness profiles.
- The X5 bundle carries the gateway wheel, pinned dependency list, pinned DimOS
  snapshot, reviewed patch, systemd units and motion enable/disable scripts.
- The local `pawguide-operator` console has no model or cloud dependency.

## Development

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
pytest
```

Build the current X5 artifact:

```bash
./provision/build-edge-bundle.sh
sha256sum dist/pawguide-x5-mvp.tar.gz
```

The future S100 artifact remains reproducible:

```bash
./provision/build-edge-bundle.sh s100
```

## Start here

- [MacBook Codex provisioning handoff](docs/MACBOOK_CODEX_HANDOFF.md)
- [First motion test](docs/FIRST_MOTION_TEST.md)
- [X5 installation and deployment](docs/MVP_DEPLOYMENT.md)
- [X5 harness requirements](docs/MOUNTING_REQUIREMENTS.md)
- [DimOS operations](docs/DIMOS_OPERATIONS.md)
- [Hyper.ai Go2 simulation](docs/HYPER_SIMULATION.md)
- [S100 future deployment](docs/S100_DEPLOYMENT.md)
- [S100 local-AI track](docs/S100_LOCAL_AI.md)
