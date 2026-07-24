# Remote development bridge

## Decision

Use an application bridge for normal development:

```text
Hetzner: agent, LLM, UI, simulation
                 |
             Tailscale
                 |
RDK X5: safety gateway + sole Unitree WebRTC connection
        |                              |
 Pixel USB-A                      Go2 AP Wi-Fi
heartbeat/STOP                    192.168.12.1
```

This is deliberately not an Ethernet or Wi-Fi Layer-2 bridge. The X5 translates
the stable PawGuide command API into Unitree operations. That boundary remains
the same if the agent later moves from Hetzner to the X5, Pixel or a stronger
mini computer.

## Why the X5 owns WebRTC

- Go2 accepts only one WebRTC peer in the normal local flow.
- Local safety does not depend on the China-to-Europe path.
- WebRTC video and sensor traffic do not have to cross the GFW unless explicitly
  requested for diagnostics.
- The Hetzner credential cannot synthesize the operator heartbeat or release a
  latched stop.
- Replacing the edge computer does not change the agent's command schema.

The Hetzner deployment remains a mock and cannot move hardware. The real
`DimOSMcpAdapter` is packaged for the X5 and can select `LocalAP`, but both its
configuration flags remain off until the physical acceptance gate.

The DimOS checkout on Hetzner is on local branch
`feat/pawguide-local-ap`. It adds a configurable connection method. The
resolved configuration for Go2 AP mode is:

```bash
cd /root/dimos
source .venv/bin/activate
dimos \
  --robot-ip 192.168.12.1 \
  --unitree-webrtc-connection-method local_ap \
  show-config
```

The same flags will select `LocalAP` when the branch is installed on the X5.
Do not run the physical blueprint from Hetzner in normal application-bridge
mode; the X5 should own that connection.

The X5 uses its onboard Wi-Fi for the Go2 AP. The Pixel connects to one of the
X5's USB-A host ports; the X5 USB-C power input remains dedicated to a stable
5 V/5 A supply. The application bridge and the requirement that the robot link
remain `never-default` do not change.

The verified lean runtime composition is:

```bash
dimos \
  --transport lcm \
  --viewer none \
  --robot-ip 192.168.12.1 \
  --unitree-webrtc-connection-method local_ap \
  run unitree-go2 unitree-skill-container paw-guide-waypoint-skill mcp-server \
  --disable perceive-loop-skill \
  --disable websocket-vis-module
```

It retains lidar mapping, obstacle-aware planning, patrol and exact waypoint
navigation. It does not load SpatialMemory, CLIP, a VLM or PyTorch. Exact poses
are stored atomically in `/var/lib/pawguide/waypoints.json`.

DimOS's Python `Dimos.connect()` remote mode discovers a daemon over an LCM
bus. It is useful on one trusted LAN, but it is not the Hetzner bridge and is
not exposed through Tailscale. The authenticated PawGuide HTTP API remains the
only normal WAN command boundary. See `docs/DIMOS_OPERATIONS.md` for the
systemd, MCP, stream-inspection and replay commands.

## Tailscale roles

Use two tagged nodes:

- `tag:pawguide-dev`: this Hetzner server;
- `tag:pawguide-edge`: the X5 bridge.

Apply `provision/tailnet-policy.example.hujson`, authenticate both nodes with
tagged keys, and expose only TCP 8765 plus administrative SSH. The Go2 subnet is
not advertised in the normal mode.

On Hetzner:

```bash
sudo tailscale up \
  --hostname=pawguide-dev \
  --advertise-tags=tag:pawguide-dev
```

On the X5:

```bash
sudo tailscale up \
  --hostname=pawguide-edge \
  --advertise-tags=tag:pawguide-edge \
  --ssh
```

Set the Hetzner client variables without committing them:

```bash
export PAWGUIDE_GATEWAY_URL=http://pawguide-edge:8765
read -rsp "PawGuide dev token: " PAWGUIDE_DEV_TOKEN
export PAWGUIDE_DEV_TOKEN
echo

pawguide-client state
pawguide-client stop
```

Use Tailscale MagicDNS or the X5's Tailscale IP for
`PAWGUIDE_GATEWAY_URL`.

## Optional transparent diagnostic route

If direct driver debugging becomes necessary, the X5 can temporarily advertise
only the Go2 host:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
sudo tailscale set --advertise-routes=192.168.12.1/32
```

Linux clients such as Hetzner must then accept subnet routes:

```bash
sudo tailscale set --accept-routes=true
ip route get 192.168.12.1
```

Keep Tailscale's default subnet-route SNAT enabled so the Go2 sees the X5 as the
source and needs no return route. This path is experimental: local Unitree
WebRTC uses host ICE candidates, so successful ping and signaling do not prove
that the media/data channels traverse the routed tunnel.

Do not use the transparent route for unattended motion. Initially use it only
for supported-off-ground connection tests, state reads and video experiments.
Remove it after diagnostics:

```bash
sudo tailscale set --advertise-routes=
sudo tailscale set --accept-routes=false
```

## Development modes

1. `mock`: all services on Hetzner with `MockRobotAdapter`.
2. `remote-edge`: agent on Hetzner, X5 gateway owns the physical Go2.
3. `edge`: agent and gateway on the selected onboard computer.

The API and tests must behave identically in all three modes.

## Current Hetzner state

- PawGuide source and its Python 3.12 environment: `/root/pawguide`
- DimOS source and its Python 3.12 environment: `/root/dimos`
- Tailscale is installed and `tailscaled` is enabled. Hetzner is connected as
  `pawguide-dev` with `tag:pawguide-dev`; subnet routes are not accepted.
- `pawguide-gateway.service` is enabled, is reachable only over Tailscale and
  reports `adapter=mock`, `motion_capable=false`.
- Replay has verified `tag_location`, `navigate_to_waypoint`,
  `stop_navigation`, the direct Unitree stop skill and the PawGuide adapter.
- TCP/UDP 443 remain assigned to Xray and Hysteria2. Tailscale uses UDP 41641.
