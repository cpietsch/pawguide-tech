# RDK S100 future deployment

All software preparation can be completed without the S100. The commands marked
as hardware gates are intentionally deferred until the board and Go2 are
physically present.

## 1. Transfer and verify the bundle

The release artifact is built on Hetzner:

```bash
cd /root/pawguide
./provision/build-edge-bundle.sh s100
```

Copy `dist/pawguide-s100-mvp.tar.gz` to the S100, extract it, and verify every
packaged input before installing:

```bash
tar -xzf pawguide-s100-mvp.tar.gz
cd pawguide-s100-mvp
sha256sum --check SHA256SUMS
```

The bundle carries a pinned DimOS source snapshot and patch. The S100 therefore
does not need GitHub during the normal install. Python packages still require an
internet route; wired `eth0` is the simplest installation-time uplink.

## 2. Bootstrap the board

Use XBurn to flash the current RDK S100 Server image
`RDKS100-V4.0.5_20260507` to the onboard 64 GB eMMC. The release is based on
Ubuntu 22.04 with a 6.1 real-time kernel. Prefer the Server image: the current
desktop release can fall back to CPU-rendered X11 when no HDMI display is
connected.

The factory image documents default `sunrise` and `root` passwords. Replace both
before connecting the board to an untrusted network. After first boot:

```bash
sudo bash provision/bootstrap-rdk-s100.sh
sudo bash provision/install-s100-bridge.sh
sudo bash provision/install-dimos-s100.sh
```

The gateway starts in mock mode. The DimOS service is installed but is neither
enabled nor able to start without the robot credential. The edge dependency set
has been resolved for Python 3.12 on AArch64 and deliberately excludes the
PyTorch/visual-semantic stack.

The standard S100 has 12 GB LPDDR5, an 80-TOPS BPU and 64 GB eMMC. The S100P
has 24 GB and 128 TOPS. The PawGuide MVP works on either, but the bootstrap
verifies S100-family hardware and at least 10 GB usable memory.

## 3. Configure power, robot and Pixel links

The S100 has no guaranteed onboard Wi-Fi. Install a supported PCIe M.2 Key-E
Wi-Fi module before powering the board, or use a supported USB Wi-Fi adapter.
The board must expose a Linux Wi-Fi interface before Go2 AP mode can work.

The target topology is:

```text
Go2 AP (192.168.12.1) <--- Wi-Fi ---> RDK S100
                                         |
                               USB-A host/data
                                         |
                                    Pixel 9 Pro
                              ring / local AI / cellular
```

The Go2 is the access point. Its AP-mode control address is `192.168.12.1`.
A robot address learned in STA mode must not be used for `LocalAP`.

Only the S100 joins the Go2 Wi-Fi and only the S100 opens a WebRTC session. The
Pixel does not join the Go2 AP during normal operation. Do not open the official
Unitree app while PawGuide owns the robot; the second peer may be rejected.

Configure the S100 without putting the Go2 password in shell history:

```bash
sudo bash provision/configure-go2-ap.sh
```

The generated NetworkManager connection is `never-default`. Enable Pixel USB
tethering and verify that the default route uses the USB interface, while
`192.168.12.1` routes over Wi-Fi.

The S100's USB-C J16 connector is device-only and reserved for flashing and
serial debugging. Connect the Pixel to one of the four USB-A host ports with a
data-capable A-to-C cable. Each S100 USB-A port is rated for at most 5 V/1 A, so
verify that the Pixel does not slowly discharge during tethering, local
inference and TTS. A powered data hub may be required.

Power the S100 through its DC input, not a USB port. It accepts 12–20 V;
D-Robotics recommends 70 W for typical use, includes a 90 W bench adapter, and
specifies up to 150 W for extreme loads. The mobile supply must be fused,
strain-relieved and load-tested at continuous output. Do not assume the former
power-bank plan is valid merely because the connector can be adapted.

## 4. Join the S100 to Tailscale

Create a tagged auth key that may assign `tag:pawguide-edge`. Enter it only at a
hidden prompt; do not drop it into a file or paste it into the environment
configuration:

```bash
read -rsp "Tailscale auth key: " tailscale_auth_key
echo
sudo tailscale up \
  --auth-key="${tailscale_auth_key}" \
  --advertise-tags=tag:pawguide-edge \
  --hostname=pawguide-edge \
  --ssh
unset tailscale_auth_key
```

The current tailnet policy is permissive. A restrictive replacement is prepared
in `provision/tailnet-policy.example.hujson`, but applying it affects the whole
tailnet and therefore remains an explicit administrator action.

Do not advertise `192.168.12.0/24` in the runtime topology. Tailscale carries
SSH, diagnostics, mission requests and a secondary STOP request—not Unitree
WebRTC and not the local safety heartbeat.

## 5. Read-only acceptance gate

With the S100, Pixel and Go2 present, run:

```bash
sudo provision/check-s100-readiness.sh
```

Before enabling motion:

1. Confirm the mobile DC supply holds voltage under simultaneous CPU, BPU,
   fan, Wi-Fi and USB load.
2. Join only the S100 to the Go2 AP.
3. Confirm the Go2 answers at `192.168.12.1`.
4. Confirm Pixel USB owns the default route.
5. Confirm the mock gateway is reachable from both Pixel USB and Tailscale.
6. Let the operator heartbeat test run for 30 minutes in mock mode while recording
   all five S100 chip temperature sensors.
7. Stop the heartbeat and confirm a stop latches within two seconds.
8. Disconnect cellular; USB heartbeat and STOP must continue to work.
9. Disconnect USB; the gateway must latch STOP.
10. Reboot all three devices twice and repeat the route and heartbeat checks.

If USB tethering is unreliable, use a travel router or a second USB/Ethernet
network adapter. Do not make two-client Go2 AP behavior part of the MVP.

## 6. Physical connection gate

Install the robot credential through the hidden prompt:

```bash
sudo provision/install-robot-credential.sh
```

Support the Go2 off the ground, keep a safety spotter beside it, and deliberately
enable the physical adapter:

```bash
sudo provision/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
```

This starts local DimOS, verifies its MCP endpoint, switches both real-motion
gates, and restarts the gateway. Startup actively dispatches the complete stop
sequence and leaves the software STOP latch set. Do not reset it until the test
area is clear.

Run the read-only DimOS diagnostic before clearing the stop latch:

```bash
sudo /opt/pawguide/bin/diagnose-dimos-s100.sh
```

DimOS runs in the foreground under systemd. Use `systemctl` and `journalctl`
for lifecycle and logs; do not use DimOS's separate CLI-daemon lifecycle on
the S100. The complete operator command set is in `docs/DIMOS_OPERATIONS.md`.

To return to the non-moving mock at any time:

```bash
sudo provision/disable-real-motion.sh
```

## 7. Calibrate exact waypoints

Waypoint IDs must match `PAWGUIDE_WAYPOINTS` in
`/etc/pawguide/pawguide.env`. Place the supported robot at each pose and invoke
the setup-only tool locally on the S100:

```bash
sudo -u pawguide /opt/pawguide/.venv/bin/python \
  /opt/pawguide/bin/tag-waypoint.py home
sudo -u pawguide /opt/pawguide/.venv/bin/python \
  /opt/pawguide/bin/tag-waypoint.py demo_a
```

The file `/var/lib/pawguide/waypoints.json` is mode `0600` and updated
atomically. A corrupt file or unknown waypoint fails closed.

Validate STOP first, then one waypoint at minimum speed, then return-home, then
the second waypoint. Mapped patrol/roaming is the final motion test. Keep the
MVP on one floor; stairs remain out of scope.

## 8. Pixel and ring gate

The app contract is in `docs/PIXEL_CLIENT.md`; the generated HTTP definition is
`contracts/pawguide-openapi.json`; local model output is restricted by
`contracts/local-agent-output.schema.json`.

The phone/ring implementation remains blocked only on the ring’s BLE, audio and
haptic protocol. Until that specification arrives, exercise the same state
machine with the Pixel microphone and an on-screen hold-to-talk button.

The S100 can host quantized perception, detection, pose, OCR or multimodal
models through D-Robotics' `hbm_runtime`. TogetherROS also documents S100/S100P
support for 1.5B and 7B DeepSeek-R1-Distill-Qwen models. That is not an excuse
to move heartbeat, STOP or arming into a model. For the first moving MVP,
language inference starts on the Pixel; the loaded physical benchmark in
`docs/S100_LOCAL_AI.md` decides whether it moves to the S100.

Never store the robot credential, API tokens or a Tailscale auth key in source,
logs, screenshots or documentation.

The printable harness remains dimension-gated, not design-gated. Follow
`docs/S100_MOUNTING_REQUIREMENTS.md` when all physical components are together.

Official references:

- <https://d-robotics.github.io/rdk_s_doc/en/01_Quick_start/01_hardware_introduction/01_rdk_s100/01_rdk_s100_kit/>
- <https://d-robotics.github.io/rdk_s_doc/en/Release_Note/s100/v4_0_5_260507/>
- <https://d-robotics.github.io/rdk_s_doc/en/System_configuration/network_bluetooth/>
- <https://d-robotics.github.io/rdk_s_doc/en/System_configuration/frequency_management/>
- <https://d-robotics.github.io/rdk_doc/en/Robot_development/quick_start/changelog/>
