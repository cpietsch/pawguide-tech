# RDK X5 MVP deployment

The RDK X5 8 GB is the current physical target. The Pixel is only an optional
USB internet/Tailscale uplink in this phase; no Pixel or X5 LLM is installed.

## 1. Prepare RDK OS

Use the current RDK X5 Server image (RDK OS 3.5.0 or newer, Ubuntu 22.04) on the
64 GB microSD card. During initial installation, give the X5 internet through
wired Ethernet or Pixel USB tethering. Do not use the Go2 AP as the default
route because it has no internet.

Change the image's default password before joining an untrusted network.

Official references:

- <https://d-robotics.github.io/rdk_doc/en/Quick_start/hardware_introduction/rdk_x5/>
- <https://archive.d-robotics.cc/downloads/os_images/rdk_x5/rdk_os_3.5.0-2026-4-9/>

## 2. Transfer and verify the bundle

Build on Hetzner:

```bash
cd /root/pawguide
./provision/build-edge-bundle.sh
sha256sum dist/pawguide-x5-mvp.tar.gz
```

Copy that archive to the X5 by SCP, Tailscale file transfer or a USB drive.
On the X5:

```bash
tar -xzf pawguide-x5-mvp.tar.gz
cd pawguide-x5-mvp
sha256sum --check SHA256SUMS
```

The archive includes the pinned DimOS source and patch. Python dependencies are
installed through the X5's current internet route.

## 3. Bootstrap and install in mock mode

```bash
sudo bash provision/bootstrap-rdk-x5.sh
sudo bash provision/install-x5-bridge.sh
sudo bash provision/install-dimos-x5.sh
```

The gateway starts in non-moving mock mode. DimOS is installed but not enabled.
The installer records the `x5` hardware profile so an S100 bundle cannot be
accidentally enabled on this board.

## 4. Configure the two network paths

Target topology:

```text
Go2 AP (192.168.12.1) <--- onboard Wi-Fi ---> RDK X5
                                                 |
                                       USB-A host/data
                                                 |
                                            Pixel 9 Pro
                                      cellular + Tailscale
```

Configure the Go2 connection without putting its password in shell history:

```bash
sudo bash provision/configure-go2-ap.sh
```

The NetworkManager profile is `never-default`, ignores Go2 DNS and disables
Wi-Fi power saving. Verify:

```bash
ip -4 route get 192.168.12.1
ip -4 route show default
```

The first command must use `wlan0`; the default route must use Pixel USB or
Ethernet. Use `192.168.12.1` for LocalAP, not the old `10.88.15.7` STA address.

Do not open the Unitree app while DimOS owns the robot connection.

## 5. Join Tailscale

Enter the existing tagged auth key only through a hidden prompt:

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

Do not place the auth key in `pawguide.env`, the release archive or shell
history. Tailscale is for SSH, diagnostics and secondary STOP—not for Unitree
WebRTC and not for the local heartbeat.

## 6. Install the robot credential

The installer prompts without echo:

```bash
sudo provision/install-robot-credential.sh
```

Do not put the AES value on a command line or in an environment file.

## 7. Run the read-only gate

```bash
sudo provision/check-x5-readiness.sh
```

Resolve every `FAIL` before enabling motion. Warnings about physical power,
cooling, mounting and connector retention require manual inspection.

## 8. Exercise the console in mock mode

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
quit
```

The commands must be accepted while the robot remains motionless because the
adapter is still `mock`.

## 9. Physical enable gate

Follow `docs/FIRST_MOTION_TEST.md`. The deliberate enable command is:

```bash
sudo provision/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
```

Return to mock mode at any time:

```bash
sudo provision/disable-real-motion.sh
```

## 10. Waypoints after posture tests

Do not begin mapping or roaming until `stand`, `hello`, `sit`, console exit and
heartbeat-loss STOP have passed. Exact waypoint tagging then uses:

```bash
sudo -u pawguide /opt/pawguide/.venv/bin/python \
  /opt/pawguide/bin/tag-waypoint.py home
```

Unknown and corrupt waypoints fail closed. Keep the MVP on one floor.
