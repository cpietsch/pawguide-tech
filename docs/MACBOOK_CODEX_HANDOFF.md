# PawGuide MacBook Codex handoff

## Mission

Provision the RDK X5 from the MacBook, validate the no-LLM PawGuide stack in
mock mode, and prepare the supported-off-ground Go2 posture test. Stop and ask
the user for an explicit physical-safety confirmation before enabling real
motion.

Do not redesign the architecture during this session. The immediate milestone
is:

```text
manual console -> X5 safety gateway -> DimOS MCP -> Go2 WebRTC
```

## Current status

This handoff reflects the state on 2026-07-25:

- The 64 GB microSD has already been flashed with the official RDK X5 Ubuntu
  22.04 server image. Do not reflash it unless first-boot diagnostics establish
  that the image is unusable.
- The X5 is provisioned and reachable on Tailscale as `pawguide-x5`
  (`100.72.30.53`). Its production mock gateway remains on port 8765.
- An isolated simulation gateway is enabled on X5 port 8876. It keeps the
  fail-closed safety contract while dispatching its allowlisted MCP calls to
  the GPU simulator through a loopback relay.
- The active hardware-free simulator has migrated to
  `ssh root@ssh.hyper.ai -p 31612`. The Hyper.ai container runs DimOS, MuJoCo,
  CUDA ONNX Runtime, the command center and MCP under runit supervision.
- Hyper.ai has no `/dev/net/tun`. The China server therefore provides a
  persistent SSH relay while preserving stable tailnet endpoints. The command
  center is `http://100.102.208.90:7780/command-center`; MCP remains
  `100.102.208.90:9991`.
- The end-to-end simulation acceptance sequence
  `STOP -> reset/arm -> hello -> STOP` passed. The X5 finished with STOP
  latched and the production gateway was untouched.
- The tested PawGuide bundle is ready on the China artifact mirror. Hetzner is
  retained only as a recovery and cross-border egress host.
- Codex is installed and authenticated on the China development server. Its
  localhost-only Hysteria2 proxy is healthy; no Tailscale exit node is
  selected.
- On the Mac, use the current ChatGPT desktop app in **Codex** mode and connect
  directly to the SSH host alias `china`. Do not tunnel Codex through another
  terminal session or through the mobile remote-control relay.

The authoritative simulator operations record is
[Hyper.ai Go2 simulation](HYPER_SIMULATION.md).

> **Obsolete-path stop condition:** if a setup session asks the X5 to connect,
> tunnel or copy credentials to `hetzner` or `2.28.11.114`, stop that step.
> Resume from this handoff on the China Codex session. Hysteria2 terminates on
> Hetzner for China-server Codex egress only; it is not an X5 dependency.

## Fixed decisions

- Physical target: RDK X5, 8 GB RAM, 64 GB microSD.
- Future target only: RDK S100. Do not install its profile on the X5.
- Robot: Unitree Go2 Air, device name `Go2 62554`.
- No Unitree remote controller or hardware emergency stop is available.
- No LLM runs on the Pixel, X5 or Mac during this milestone.
- Pixel 9 Pro is only an optional USB internet/Tailscale uplink.
- X5 onboard Wi-Fi is the sole Go2 AP client and WebRTC peer.
- Go2 LocalAP address is `192.168.12.1`.
- The old STA address `10.88.15.7` is not used in LocalAP mode.
- Tailscale is for SSH, diagnostics and secondary STOP. Do not route Go2
  WebRTC through Tailscale and do not select an exit node on the X5.
- The X5 never initiates a connection to Hetzner. After joining Tailscale,
  management connections originate from the Mac or China server toward the
  X5. Neither remote server owns the local safety heartbeat.
- The China server is the primary development/control host. Hetzner is a
  fallback only and must not become an X5 or Go2 runtime dependency.
- Keep the X5 beside the robot for all initial tests. Do not mount the X5,
  Pixel or power bank yet.

## Source and artifact

Private source repository:

```text
https://github.com/cpietsch/pawguide
```

The canonical handoff lives on the default branch:

```text
main
```

If the repository is not already present on the Mac:

```bash
gh repo clone cpietsch/pawguide ~/Code/pawguide
cd ~/Code/pawguide
git switch main
git pull --ff-only
```

If the repository already exists locally:

```bash
cd ~/Code/pawguide
git fetch origin
git switch main
git pull --ff-only
```

On the user's MacBook, the China development server is configured in
`~/.ssh/config` under the host alias `china`. Use that alias instead of
reconstructing its address, port or key settings:

```bash
ssh china
scp china:/root/pawguide/docs/MACBOOK_CODEX_HANDOFF.md .
```

Do not modify the Mac's working SSH configuration unless the alias fails and
the user explicitly asks for it to be repaired.

In the current ChatGPT desktop app:

1. Select **Codex** from the top-left product menu.
2. Add or select the SSH connection named `china`.
3. Open `/root/pawguide`.
4. Start a new session with:

   ```text
   Read docs/MACBOOK_CODEX_HANDOFF.md completely. Execute Phases 1-4.
   Resolve and report every readiness failure. Stop before Phase 5 and ask me
   to confirm the physical support, spotter, and clear area before enabling
   real motion.
   ```

The ChatGPT desktop SSH connection is only the development/control surface for
the China server. During X5 first boot, the Mac also needs a separate direct
LAN SSH session to the X5. Once the X5 is on Tailscale, the China server may
connect directly to it; the Mac must not remain an always-on tunnel or runtime
dependency. The connection direction is always Mac/China to X5—never X5 to
Hetzner.

The tested artifact corresponds to initial commit:

```text
0e62467e0c10f86ffca9c11ed6ab0fae0299580b
```

Artifact:

```text
pawguide-x5-mvp.tar.gz
SHA-256: de7a79c2753821749ec53082551a4898a8a296628df82e85cee98effe3e4b9f7
```

China mirror:

```text
root@120.55.44.117:/srv/pawguide/artifacts/current/
SSH port: 28796
```

If the artifact is not already on the Mac:

```bash
scp -P 28796 \
  root@120.55.44.117:/srv/pawguide/artifacts/current/pawguide-x5-mvp.tar.gz .
scp -P 28796 \
  root@120.55.44.117:/srv/pawguide/artifacts/current/SHA256SUMS .
```

Verify on macOS:

```bash
shasum -a 256 -c SHA256SUMS
```

Expected:

```text
pawguide-x5-mvp.tar.gz: OK
```

Do not copy SSH, GitHub, Codex or proxy credentials from either development
server to the Mac or X5. Use the user's existing Mac credentials and a
dedicated X5/Tailscale enrollment path.

## Safety contract

The software begins with STOP latched, but it is not a hardware emergency
stop. Before any real-motion command:

1. Use a stable support under the Go2 torso with every foot clear.
2. Clear the complete leg sweep and surrounding area.
3. Charge the Go2 battery.
4. Power the X5 from a stable 5 V/5 A supply with its fan running.
5. Close the Unitree app so it does not compete for the WebRTC session.
6. Have one operator and one spotter present.
7. Keep an independent SSH tab ready with
   `sudo provision/disable-real-motion.sh`.

Never enable motion while alone, in a public area, with the payload mounted, or
before every readiness failure has been resolved.

STOP cancels locomotion. It does not automatically force a standing robot to
sit.

## Secret handling

Never print, record, commit or paste any of these into a Codex message or shell
command:

- Unitree AES key;
- Go2 AP password;
- Tailscale auth key;
- PawGuide operator/developer tokens;
- SSH or GitHub private credentials.

Use the prepared hidden prompts:

```bash
sudo provision/configure-go2-ap.sh
sudo provision/install-robot-credential.sh
```

For Tailscale, read the auth key without echo:

```bash
read -rsp "Tailscale auth key: " tailscale_auth_key
echo
sudo tailscale up \
  --auth-key="${tailscale_auth_key}" \
  --advertise-tags=tag:pawguide-edge \
  --hostname=pawguide-x5 \
  --ssh
unset tailscale_auth_key
```

Do not inspect or include the contents of `/etc/pawguide/*.token` in logs.

## Phase 1: establish Mac-to-X5 access

The microSD is already flashed. Insert it into the unpowered X5, connect the
fan and stable 5 V/5 A supply, connect the X5 Ethernet port directly to the
Mac, and then power on the X5. Do not connect the Go2 yet.

Configure only the Mac's dedicated Ethernet interface with:

```text
IPv4 address: 192.168.127.100
Subnet mask:  255.255.255.0
Router:       blank
DNS:          blank
```

Keep the Mac's normal Wi-Fi internet connection active. Test the documented X5
wired address:

```bash
ping -c 3 192.168.127.10
ssh sunrise@192.168.127.10
```

The factory login is `sunrise` / `sunrise`. Change the password immediately
when prompted or by running `passwd`; never store the replacement in the
repository or handoff.

If `192.168.127.10` is not reachable:

1. Confirm power, fan operation, Ethernet link LEDs and the Mac interface
   address.
2. Inspect `arp -an` and the Mac network settings without changing another
   interface.
3. Use the X5 Micro-USB debug serial interface as the recovery path:
   CH340, 921600 baud, 8 data bits, no parity, 1 stop bit, no flow control.
4. Collect boot output before considering a reflash. Never infer or overwrite a
   `/dev/diskN` target.

After first login, determine without changing disks:

```bash
uname -m
cat /etc/os-release
rdkos_info || true
grep MemTotal /proc/meminfo
df -h /
ip -br link
ip -4 route
```

Ask the user only for information that cannot be discovered safely:

- the Go2 AP SSID and password when the network script prompts;
- the Tailscale auth key when joining the X5.

Give the X5 initial internet through Ethernet or Pixel USB tethering. Do not
use Go2 Wi-Fi as the internet/default route.

Before continuing, confirm:

- architecture is `aarch64`;
- OS base is Ubuntu `22.04`;
- usable RAM is approximately 8 GB;
- the root filesystem uses the microSD capacity;
- the X5 has an internet route independent of the future Go2 Wi-Fi route.

## Phase 2: transfer and verify on the X5

From the Mac:

```bash
scp pawguide-x5-mvp.tar.gz <x5-user>@<x5-address>:~/
```

On the X5:

```bash
cd ~
echo \
  "de7a79c2753821749ec53082551a4898a8a296628df82e85cee98effe3e4b9f7  pawguide-x5-mvp.tar.gz" |
  sha256sum --check
tar -xzf pawguide-x5-mvp.tar.gz
cd pawguide-x5-mvp
sha256sum --check SHA256SUMS
```

Both checks must pass before executing any bundled script.

## Phase 3: install the fail-closed mock runtime

Keep the known-good internet connection active:

```bash
cd ~/pawguide-x5-mvp
sudo bash provision/bootstrap-rdk-x5.sh
sudo bash provision/configure-go2-ap.sh
```

Verify network separation:

```bash
ip -4 route get 192.168.12.1
ip -4 route show default
```

The Go2 route must use the X5 Wi-Fi interface, normally `wlan0`. The default
route must use Ethernet or Pixel USB, not Go2 Wi-Fi.

Join Tailscale with the hidden-prompt sequence above, then install:

```bash
sudo bash provision/install-x5-bridge.sh
sudo bash provision/install-dimos-x5.sh
sudo bash provision/install-robot-credential.sh
```

Record, but do not publish, the result of:

```bash
tailscale ip -4
tailscale status
```

Report the X5 hostname `pawguide-x5` and its Tailscale IP to the existing China
Codex session. Seeing the node in Tailscale is not sufficient proof of SSH
access. The China session must verify the ACL/SSH path from China to X5 before
taking over remote development. Do not configure an outbound SSH tunnel from
the X5, and never copy a private key from China, Hetzner or the Mac.

These installers must leave the physical DimOS service disabled and the
gateway in mock mode. Verify without reading secret files:

```bash
grep -E \
  '^(PAWGUIDE_ADAPTER|PAWGUIDE_ENABLE_REAL_MOTION)=' \
  /etc/pawguide/pawguide.env
systemctl is-active pawguide-gateway.service
systemctl is-enabled pawguide-dimos.service || true
curl -fsS http://127.0.0.1:8765/health
```

Expected gateway settings and health:

```text
PAWGUIDE_ADAPTER=mock
PAWGUIDE_ENABLE_REAL_MOTION=NO
{"status":"ok","adapter":"mock","motion_capable":false}
```

## Phase 4: readiness and mock console

Run:

```bash
cd ~/pawguide-x5-mvp
sudo provision/check-x5-readiness.sh
```

Resolve every `FAIL`. Do not dismiss a failure as an expected hardware
difference without tracing the relevant script and evidence. Physical power,
cooling and mounting warnings require the user's inspection.

Exercise the manual console:

```bash
sudo -u pawguide env \
  PAWGUIDE_OPERATOR_TOKEN_FILE=/etc/pawguide/operator.token \
  PAWGUIDE_GATEWAY_URL=http://127.0.0.1:8765 \
  /opt/pawguide/.venv/bin/pawguide-operator
```

Enter:

```text
state
arm
hello
stop
state
quit
```

Commands must be accepted, the final state must be stopped and latched, and
the physical robot must not move because the adapter is `mock`.

Stop here and report:

- X5 OS/architecture/RAM;
- Mac-to-X5 connection method;
- X5 Tailscale hostname and IP;
- Go2 route interface and independent default-route interface;
- readiness PASS/FAIL/WARN summary;
- mock gateway health;
- mock console final state;
- any errors, without secrets.

Obtain explicit user confirmation that the support, spotter and clear area are
ready before continuing.

## Phase 5: supported-off-ground motion test

This phase is authorized only after the user confirms the physical safety
conditions in the current session.

Use three separate X5 SSH terminals.

Terminal A, continuous logs:

```bash
sudo journalctl \
  -u pawguide-dimos.service \
  -u pawguide-gateway.service -f
```

Keep this command ready in a separate tab:

```bash
cd ~/pawguide-x5-mvp
sudo provision/disable-real-motion.sh
```

Terminal B, enable and diagnose:

```bash
cd ~/pawguide-x5-mvp
sudo provision/check-x5-readiness.sh
sudo provision/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
sudo /opt/pawguide/bin/diagnose-dimos-x5.sh
curl -fsS http://127.0.0.1:8765/health
```

Required health:

```json
{"status":"ok","adapter":"dimos_mcp","motion_capable":true}
```

STOP must still be latched.

Terminal C, operator console:

```bash
sudo -u pawguide env \
  PAWGUIDE_OPERATOR_TOKEN_FILE=/etc/pawguide/operator.token \
  PAWGUIDE_GATEWAY_URL=http://127.0.0.1:8765 \
  /opt/pawguide/.venv/bin/pawguide-operator
```

Enter one command at a time, waiting for completion:

```text
state
arm
stand
sit
stop
state
quit
```

The final state must have `stop_latched: true`. On any unexpected posture,
transport error, route change, restart, overheating or power instability,
execute `disable-real-motion.sh` and return to diagnosis. Do not improvise with
raw sport or velocity commands.

Only after the supported test passes may the user decide to run the separate
floor greeting and watchdog tests in `docs/FIRST_MOTION_TEST.md`.

## Failure diagnostics

Collect bounded, read-only evidence:

```bash
sudo systemctl status \
  pawguide-gateway.service \
  pawguide-dimos.service \
  --no-pager
sudo journalctl -u pawguide-gateway.service -n 200 --no-pager
sudo journalctl -u pawguide-dimos.service -n 200 --no-pager
ip -br address
ip -4 route
nmcli connection show --active
tailscale status
curl -fsS http://127.0.0.1:8765/health || true
```

Never include token-file contents. If real motion was selected when a failure
occurred, first run:

```bash
cd ~/pawguide-x5-mvp
sudo provision/disable-real-motion.sh
```

## Change discipline

- Provision from the tested bundle before changing source.
- Do not patch files directly under `/opt/dimos-src` or `/opt/pawguide`.
- If a source correction is necessary, reproduce it in the PawGuide Git
  repository, add tests, and use a new branch/PR.
- Preserve the current artifact and report its checksum with all results.
- Do not involve the S100, ring, roaming, mapping, mounting or local AI until
  the first-motion acceptance sequence passes.

Primary references inside the extracted bundle:

- `docs/MVP_DEPLOYMENT.md`
- `docs/FIRST_MOTION_TEST.md`
- `docs/DIMOS_OPERATIONS.md`
- `docs/MOUNTING_REQUIREMENTS.md`
