# PawGuide

PawGuide is the control, simulation, and deployment repository for a Unitree
Go2 Air guide-robot prototype. The current system has three supported runtime
targets:

- an RDK X5 beside the robot, providing the physical Go2 bridge and the
  fail-closed HTTP gateway;
- a China server providing the browser command center and stable relay
  endpoints;
- a Hyper.ai GPU container running the DimOS/MuJoCo hardware-free simulation.

The phone and ring are developed separately. They integrate only through the
HTTP API defined in
[`contracts/pawguide-openapi.json`](contracts/pawguide-openapi.json). They do
not connect to DimOS or the Go2 directly.

## Current physical behavior

The X5 is the sole normal motion gateway. Its current physical MCP bridge
exposes reviewed posture and greeting commands plus a bounded commissioning
route:

- `home` is the assumed starting position;
- `demo_gate` moves forward approximately one metre;
- returning to `home` reverses the same bounded motion;
- STOP interrupts the motion loop;
- startup and heartbeat loss latch STOP.

This is an open-loop commissioning route, not mapped autonomous navigation.
The Hyper simulation remains the qualified environment for the larger
obstacle-aware concept course.

## Source of truth

Start with these documents:

- [Current recovery runbook](docs/CURRENT_RECOVERY_RUNBOOK.md) — complete
  rebuild and restart procedure;
- [Deployment inventory](docs/DEPLOYMENT_INVENTORY.md) — tracked-to-installed
  file map and external-state boundary;
- [Runtime manifest](docs/RUNTIME_MANIFEST.md) — observed OS, package, and
  service versions;
- [HTTP client contract](docs/PIXEL_CLIENT.md) — app/ring integration behavior;
- [Hyper simulation](docs/HYPER_SIMULATION.md) — simulation topology and
  operations;
- [Physical Go2 handoff](docs/PHYSICAL_GO2_HANDOFF.md) — current physical
  controls and recovery;
- [Pre-hardware acceptance](docs/PRE_HARDWARE_ACCEPTANCE.md) — retained
  qualification evidence;
- [X5 payload harness](docs/MOUNTING_REQUIREMENTS.md) — mounting measurements
  and acceptance checks.

The exact external DimOS base is pinned to commit
`4a78e1400c4334c280970e4610c655d16b9661ae`. Its source archive and the complete
PawGuide patch are tracked under `vendor/`.

## Repository layout

```text
src/pawguide/        gateway, supervisor, adapters, clients, acceptance tools
contracts/           generated OpenAPI contract and local-agent schema
config/              non-secret runtime and acceptance configuration
provision/           X5, China, and Hyper installers and service definitions
provision/x5/        isolated X5 simulation gateway configuration
provision/hyper/     GPU simulation runit entrypoints and fixtures
artifacts/           retained final acceptance evidence
vendor/              pinned DimOS source archive and PawGuide patch
tests/               unit, API, installer, and acceptance tests
```

## Development

```bash
uv sync --extra dev
uv run pytest
```

Build the X5 recovery bundle from a clean checkout. The pinned DimOS source
archive is already tracked:

```bash
./provision/build-edge-bundle.sh
sha256sum dist/pawguide-x5-mvp.tar.gz
```

Secrets are never stored in this repository. The recovery runbook lists every
required credential, its installed location, and how to restore or reissue it.
