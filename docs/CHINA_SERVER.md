# China server operations

The China server provides the PawGuide browser command center, a non-moving
development gateway, and stable relays to the Hyper simulation. It never opens
the physical Go2 WebRTC connection; that belongs to the X5.

The complete disaster-recovery sequence is in
[`CURRENT_RECOVERY_RUNBOOK.md`](CURRENT_RECOVERY_RUNBOOK.md). This file covers
normal operation of an already provisioned server.

## Services and files

| Component | Installed path |
| --- | --- |
| Development gateway unit | `/etc/systemd/system/pawguide-china-gateway.service` |
| Development gateway environment | `/etc/pawguide/pawguide.env` |
| Current Python release | `/opt/pawguide/current` |
| Admin nginx site | `/etc/nginx/sites-available/pawguide-admin` |
| Dashboard document | `/var/www/pawguide/dashboard.html` |
| Dashboard JavaScript | `/var/www/pawguide/dashboard.js` |
| Hyper relay unit | `/etc/systemd/system/pawguide-hyper-tunnel.service` |
| Mirrored X5 operator credential | `/etc/pawguide/x5-operator.token` |
| Generated nginx auth include | `/etc/pawguide/nginx-operator-auth.conf` |
| Hyper SSH identity | `/root/.ssh/pawguide_gpu_server` |

The tracked counterparts and parity checks are listed in
[`DEPLOYMENT_INVENTORY.md`](DEPLOYMENT_INVENTORY.md).

## Endpoints

```text
http://100.102.208.90:7780/command-center
http://100.102.208.90:7780/admin/status/x5
http://100.102.208.90:7780/admin/api/physical/
http://100.102.208.90:7780/admin/api/sim/
http://100.102.208.90:9991/mcp
http://100.102.208.90:9879
```

The command center is a tokenless browser kiosk. Nginx adds the X5 operator
credential to the physical API request on the server. The browser never
receives that credential.

## Routine checks

```bash
systemctl is-active \
  tailscaled nginx pawguide-china-gateway pawguide-hyper-tunnel
nginx -t
curl -fsS http://100.102.208.90:8765/health
curl -fsS http://100.102.208.90:7780/admin/status/x5
curl -fsS http://100.102.208.90:7780/command-center >/dev/null
curl -fsS http://100.102.208.90:9991/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"tools","method":"tools/list","params":{}}'
```

Logs:

```bash
journalctl -u pawguide-china-gateway -n 100 --no-pager
journalctl -u pawguide-hyper-tunnel -n 100 --no-pager
journalctl -u nginx -n 100 --no-pager
```

The local development gateway binds to the server's private network address,
not loopback. Use that address when checking it directly.

## Deploy application changes

From an authenticated external deployment host:

```bash
PAWGUIDE_CHINA_IDENTITY=/secure/path/china-key \
  provision/deploy-china-dev.sh
```

The deployer builds a wheel, uploads a staged release, installs locked
dependencies, atomically changes `/opt/pawguide/current`, restarts the gateway,
and verifies `/health`. Older release directories are rollback material and
are not source-of-truth code.

Dashboard or nginx changes are installed on the server from its repository
checkout:

```bash
cd /root/pawguide
git pull --ff-only
sudo provision/install-china-admin.sh
```

After rotating the X5 operator credential:

```bash
cd /root/pawguide
sudo provision/sync-x5-operator-token.sh
sudo provision/install-china-admin.sh
```

The synchronization script streams the credential without printing it.

## Shutdown

Before shutting down the server, confirm the physical X5 is STOP-latched:

```bash
curl -fsS \
  http://100.102.208.90:7780/admin/api/physical/v1/state
```

The required final fields are:

```json
{
  "stop_latched": true,
  "operator_heartbeat_fresh": false,
  "mission_state": "stopped",
  "active_waypoint": null
}
```

The X5 physical gateway continues to own its local STOP/watchdog behavior when
the China server is unavailable. Browser control and the Hyper relay are
unavailable until the China services return.
