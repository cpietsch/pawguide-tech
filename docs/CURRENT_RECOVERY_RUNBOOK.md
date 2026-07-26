# Current deployment recovery runbook

This is the authoritative recovery handoff for the deployment verified on
2026-07-26. It describes the supported runtime without relying on historical
commissioning paths.

## Source of truth

- Repository: `https://github.com/cpietsch/pawguide-tech.git`
- Branch: `main`
- DimOS upstream commit:
  `4a78e1400c4334c280970e4610c655d16b9661ae`
- The upstream DimOS archive and the complete PawGuide patch are tracked as
  `vendor/dimos-upstream.tar.gz` and `vendor/dimos-pawguide.patch`.
- Non-secret runtime versions and verified file parity are recorded in
  `docs/RUNTIME_MANIFEST.md`.
- The exhaustive installed-to-tracked file map is
  `docs/DEPLOYMENT_INVENTORY.md`.

Generated credentials, SSH private keys, Tailscale enrollment, and the Go2
network/AES credentials are deliberately not in GitHub. Their required
locations are listed below.

## Current topology

| Component | Address or endpoint | Role |
| --- | --- | --- |
| China server | Tailscale `100.102.208.90` | Admin UI, mock API, Hyper relay |
| Admin console | `http://100.102.208.90:7780/command-center` | Tokenless browser kiosk |
| Hyper relay MCP | `http://100.102.208.90:9991/mcp` | Simulation MCP |
| Optional Rerun mux | `http://100.102.208.90:9879` | Simulation-only 3D viewer |
| X5 | Tailscale `100.72.30.53` | Physical and simulation safety gateways |
| X5 physical gateway | `http://100.72.30.53:8765` | Physical control API |
| X5 simulation gateway | `http://100.72.30.53:8876` | Simulation control API |
| Physical MCP | X5 loopback `127.0.0.1:9990` | Direct Go2 WebRTC bridge |
| Simulation MCP relay | X5 loopback `127.0.0.1:9992` | China/Hyper relay |
| Go2 LocalAP | `192.168.12.1` via X5 `wlan0` | Physical WebRTC peer |
| Hyper container | `ssh.hyper.ai:31612` | DimOS, MuJoCo, MCP and Rerun |

The physical and simulation MCP ports must never be collapsed back onto the
same loopback listener.

The verified robot network SSID is `Go_62554`. The X5 received
`192.168.12.13/24` during commissioning. Its saved profile is selected by
SSID, without a BSSID lock, because the separately supplied hardware MAC was
not verified as the AP radio BSSID.

## Current physical profile

`provision/run-dimos-x5.sh` starts `provision/direct-go2-mcp.py`. The physical
profile is intentionally smaller than the simulation stack.

It exposes:

- `execute_sport_command` for RecoveryStand, Sit, and Hello;
- `navigate_to_waypoint` for the exact IDs `home` and `demo_gate`;
- `emergency_stop`, plus cleanup-compatible stop tools.

The commissioning route named `demo_gate` is a bounded open-loop one-metre
test, not SLAM navigation:

1. RecoveryStand and settle for 3 seconds.
2. Enter BalanceStand and settle for 0.5 seconds.
3. Move forward at `0.2 m/s` for 5 seconds.
4. Stop, pause for 1 second in the browser sequence, and reverse with the same
   speed and duration to `home`.

Obstacle avoidance is enabled before travel. STOP can interrupt the movement
loop. The bridge remembers only `home` or `demo_gate` in process memory; after
a service restart it assumes the physical robot is at `home`. Reposition the
robot before using the route after any restart.

Gateway startup is fail-closed and sends Damp while latching STOP. The browser
automatically maintains the operator heartbeat and resets STOP before an
action. The large red STOP button remains available during the bounded route.

The command center does not embed Rerun or ask for a token. China nginx injects
the X5 operator credential server-side for `/admin/api/physical/`.

## Secrets and external state

Recreation requires these inputs outside GitHub:

| Input | Installed location |
| --- | --- |
| Go2 AP password | Root-owned NetworkManager profile on X5 |
| Unitree AES key | X5 `/etc/pawguide/unitree-aes.token` |
| X5 operator token | X5 `/etc/pawguide/operator.token` |
| X5 developer token | X5 `/etc/pawguide/dev.token` |
| Mirrored X5 operator token | China `/etc/pawguide/x5-operator.token` |
| Generated nginx auth include | China `/etc/pawguide/nginx-operator-auth.conf` |
| Hyper SSH private key | China `/root/.ssh/pawguide_gpu_server` |
| China deployment SSH identity | External deploy host, configured explicitly |
| China Tailscale machine state | China `/var/lib/tailscale/tailscaled.state` |
| X5 Tailscale machine state | X5 `/var/lib/tailscale/tailscaled.state` |

Do not substitute the China mock gateway's operator token for the X5 operator
token. The admin installer must use the mirrored X5 token.

The tracked services use the observed private addresses directly. Preserve the
two Tailscale machine-state files securely if the same node identities and
addresses must survive a disk rebuild. If either identity is reissued, replace
the affected China/X5 addresses in the nginx site, tunnel unit, simulation
relay unit, simulation environment, and recovery documentation before
installation.

## Rebuild the X5

Build the X5 bundle on a Linux development host with `uv` and a clean PawGuide
checkout. The tracked upstream archive is sufficient:

```bash
git clone https://github.com/cpietsch/pawguide-tech.git
cd pawguide-tech
git switch main
./provision/build-edge-bundle.sh x5
```

If `/root/dimos` exists at the pinned commit, the builder refreshes the
tracked archive from it before packaging. Otherwise it uses the tracked
archive as-is.

Copy and extract `dist/pawguide-x5-mvp.tar.gz` on the X5. Then:

```bash
sudo provision/bootstrap-rdk-x5.sh
sudo provision/configure-go2-ap.sh
sudo provision/install-x5-bridge.sh
sudo provision/install-dimos-x5.sh
sudo provision/install-robot-credential.sh
sudo provision/check-x5-readiness.sh --require-physical
sudo provision/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
```

The Wi-Fi and credential scripts use hidden/local prompts. Enter
`Go_62554` when the network script asks for the SSID. The Go2 profile must set
`ipv4.never-default=yes`, leaving internet/Tailscale on the Pixel USB or
another independent uplink.

To restore the optional isolated simulation gateway:

```bash
sudo provision/install-x5-simulation.sh --enable
```

Expected isolation:

```text
physical gateway :8765 -> 127.0.0.1:9990
simulation gateway :8876 -> 127.0.0.1:9992 -> 100.102.208.90:9991
```

## Rebuild the China services

Join the replacement server to the same tailnet and confirm its stable
Tailscale address is `100.102.208.90`. Deploy the mock API using
`provision/deploy-china-dev.sh` from an external Linux host with the China SSH
identity configured through `PAWGUIDE_CHINA_IDENTITY`.

On the China server, clone this repository, then securely mirror the X5
operator token and install the admin surface:

```bash
cd /root/pawguide
sudo provision/sync-x5-operator-token.sh
sudo provision/install-china-admin.sh
```

`sync-x5-operator-token.sh` streams the token over the existing authenticated
SSH path without printing it. Its default target is
`sunrise@100.72.30.53`, and that account must already have authenticated SSH
access plus passwordless sudo for the single root-owned token read. Override
the target with `PAWGUIDE_X5_SSH_HOST` when restoring a different access
policy. `install-china-admin.sh` installs the tracked dashboard, nginx
configuration, and Hyper tunnel unit. It enables the Hyper tunnel only when
`/root/.ssh/pawguide_gpu_server` exists.

Verify:

```bash
nginx -t
systemctl status nginx pawguide-china-gateway pawguide-hyper-tunnel
curl -fsS http://100.102.208.90:7780/admin/status/x5
curl -fsS http://100.102.208.90:7780/command-center >/dev/null
```

## Rebuild or resume Hyper

The exact runit entrypoints and fixture files are tracked under
`provision/hyper/`. The active container uses:

```text
/opt/pawguide-dimos
/opt/pawguide-venv
/etc/service/pawguide-dimos
/etc/service/pawguide-mcp-relay
```

Restore the pinned DimOS archive, apply `vendor/dimos-pawguide.patch`, install
the Python versions from `docs/RUNTIME_MANIFEST.md`, copy the tracked runit
scripts to their corresponding `run` files, and select a tracked fixture under
`provision/hyper/fixtures/`.

The current simulation service requires Xvfb, runit, socat, Git LFS assets,
the MuJoCo menagerie Go1/Go2 models, CUDA ONNX Runtime, and the CUDA/cuDNN
libraries referenced by `provision/hyper/pawguide-dimos.run`. Hyper has no
`/dev/net/tun`; China must provide the SSH relay.

The tracked `concept-gate` fixture is the canonical qualified course.
`provision/hyper/fixtures/observed-live-waypoints-20260726.json` records the
last waypoint document observed on the running container without replacing
that canonical fixture.

## Shutdown and restart checks

Before shutdown:

```bash
curl -fsS http://100.102.208.90:7780/admin/api/physical/v1/state
```

Confirm `stop_latched=true`. After restarting infrastructure:

```bash
# China
systemctl is-active tailscaled nginx pawguide-china-gateway pawguide-hyper-tunnel

# X5
systemctl is-active \
  pawguide-dimos pawguide-gateway \
  pawguide-sim-mcp-relay pawguide-sim-gateway
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://100.72.30.53:8876/health
ip -4 route get 192.168.12.1
```

The Go2 route must resolve over `wlan0`. If it does not, reconnect the saved
NetworkManager profile before restarting `pawguide-dimos`.

## Repository completeness boundary

GitHub now contains the application, API schema, pinned dependencies, DimOS
upstream archive and patch, X5/China/Hyper service definitions, admin assets,
simulation fixtures, acceptance evidence, and recovery procedures.

The deployment cannot be recreated from a public checkout alone because the
robot credential, AP password, Tailscale enrollment, SSH private keys, and API
tokens are intentionally external. Preserve or reissue those securely.
