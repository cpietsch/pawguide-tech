# Physical Go2 operations

The RDK X5 is the sole normal physical control gateway. The complete rebuild
procedure is in
[`CURRENT_RECOVERY_RUNBOOK.md`](CURRENT_RECOVERY_RUNBOOK.md); this file covers
the currently deployed physical profile.

## Verified deployment

Observed on 2026-07-26:

- X5 private-network address: `100.72.30.53`;
- production gateway: `http://100.72.30.53:8765`;
- physical MCP: X5 loopback `127.0.0.1:9990`;
- adapter: `dimos_mcp`, motion capable;
- exact waypoint IDs: `home`, `demo_gate`;
- Go2 LocalAP control address: `192.168.12.1` over X5 `wlan0`;
- Go2 AP SSID: `Go_62554`;
- commissioned X5 Wi-Fi lease: `192.168.12.13/24`;
- China command center:
  `http://100.102.208.90:7780/command-center`;
- simulation gateway `:8876` remains isolated from physical control.

The saved Wi-Fi profile is selected by SSID without a BSSID lock because the
separately supplied hardware MAC was not verified as the AP radio BSSID. The
AP password and Unitree credential are installed as root-owned external
state; their values are not stored in this repository.

## Current direct bridge

The physical service starts `provision/direct-go2-mcp.py` through
`provision/run-dimos-x5.sh`. It provides:

- RecoveryStand, Sit, and Hello through `execute_sport_command`;
- a best-effort redundant STOP sequence;
- `demo_gate`, a bounded forward movement at `0.2 m/s` for five seconds;
- `home`, the matching bounded reverse movement.

The bridge enables obstacle avoidance before bounded travel. STOP interrupts
the motion loop. Waypoint state exists only in bridge process memory and
resets to `home` when the service restarts. Reposition the robot at the assumed
home pose before using the route after any restart.

This profile does not map the room, persist a physical pose, or perform SLAM.
The larger exact-waypoint navigation course is simulation-only.

## Checks

On the X5:

```bash
sudo /opt/pawguide/bin/check-x5-readiness.sh --require-physical
systemctl is-active pawguide-dimos pawguide-gateway
curl -fsS http://127.0.0.1:8765/health
ip -4 route get 192.168.12.1
```

The route must use `wlan0`, while the default route uses an independent
uplink. Expected gateway health:

```json
{"status":"ok","adapter":"dimos_mcp","motion_capable":true}
```

The command center maintains the operator heartbeat and resets STOP before an
action. China nginx supplies the credential server-side, so the browser does
not ask for or receive it.

## Enable and disable

The installer leaves physical motion disabled. After the local readiness check
passes:

```bash
sudo /opt/pawguide/bin/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
```

The command starts the direct MCP bridge, verifies the minimal physical tool
set, switches the gateway to the real adapter, and leaves STOP latched.

Rollback:

```bash
sudo /opt/pawguide/bin/disable-real-motion.sh
```

Rollback sends a best-effort STOP, restores the mock adapter, restarts the
gateway, and disables the physical bridge.

## Restart rule

After the Go2, X5, or physical service restarts:

1. position the robot at the intended `home` pose;
2. verify LocalAP routing and gateway health;
3. confirm the gateway is STOP-latched with no active waypoint;
4. start a fresh command-center session;
5. test one posture command before using the bounded route.

An accepted HTTP result confirms dispatch only. Observe the robot before
sending the next physical action.
