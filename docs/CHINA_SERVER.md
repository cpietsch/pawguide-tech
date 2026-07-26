# China development server

The current admin/nginx and X5-token recovery procedure is in
[CURRENT_RECOVERY_RUNBOOK.md](CURRENT_RECOVERY_RUNBOOK.md). The mock gateway
deployer below is only one part of the complete China rebuild.

## Role

The Aliyun Hangzhou server is PawGuide's in-region development, integration and
tailnet relay node. It hosts the same authenticated HTTP gateway contract used
by Hetzner and the physical X5, but it deliberately runs `MockRobotAdapter`.
During hardware-free testing it also relays command-center and MCP traffic to
the Hyper.ai GPU simulator:

```text
developer / prototype agent
             |
         Tailscale
             |
China gateway (mock, no motion)

browser / X5 simulation gateway
             |
         Tailscale
             |
China nginx + persistent SSH tunnel
             |
Hyper.ai DimOS + MuJoCo

Local heartbeat + X5 safety + DimOS + Go2 remain an edge-only runtime.
```

The China server is suitable for API integration, local-agent experiments,
artifact distribution, simulation relay and later in-region telemetry. It
must never become the physical Go2 WebRTC peer or the source of the local
safety heartbeat. Selecting the RDK X5 for the moving MVP does not change this
boundary. See [Hyper.ai Go2 simulation](HYPER_SIMULATION.md) for the active
simulation topology.

## Deployment

From the Hetzner development server:

```bash
cd /root/pawguide
sudo ./provision/deploy-china-dev.sh
```

The deployer:

1. runs the PawGuide test suite and builds the current wheel;
2. creates a content-addressed source and runtime release;
3. repairs the server's persistent DNS, APT and pip mirror configuration if
   necessary;
4. installs dependencies into an isolated Python 3.12 virtual environment;
5. generates or preserves separate operator and developer credentials;
6. binds the service only to the China node's Tailscale IPv4 address;
7. enables `pawguide-china-gateway.service` in mock mode.

The China-specific developer credential remains at
`/etc/pawguide/china-dev.token` on Hetzner and
`/etc/pawguide/dev.token` on the China server. Do not paste either value into
source, shell history, logs or chat.

## Operations

On the China server:

```bash
systemctl status pawguide-china-gateway.service
journalctl -u pawguide-china-gateway.service -f
curl -fsS http://100.102.208.90:8765/health
readlink -f /opt/pawguide/current
readlink -f /srv/pawguide/current
```

From Hetzner, use the packaged client without exposing the credential:

```bash
export PAWGUIDE_GATEWAY_URL=http://100.102.208.90:8765
export PAWGUIDE_DEV_TOKEN_FILE=/etc/pawguide/china-dev.token
/root/pawguide/.venv312/bin/pawguide-client state
/root/pawguide/.venv312/bin/pawguide-client stop
```

The developer role may inspect state, request mock missions and always request
STOP. It cannot send the operator heartbeat or clear the fail-closed stop latch.

## Security invariants

- TCP 8765 is not opened in UFW and is not bound to the public interface.
- Physical motion stays disabled with both `PAWGUIDE_ADAPTER=mock` and
  `PAWGUIDE_ENABLE_REAL_MOTION=NO`.
- The operator credential stays on the China server. Hetzner receives only the
  China-specific developer credential.
- Deployments create immutable release directories and atomically update the
  `/opt/pawguide/current` and `/srv/pawguide/current` symlinks.
- DimOS and raw Unitree WebRTC are not installed on this server.
- The active simulator runs on Hyper.ai. The retained local DimOS environment
  is rollback-only and is not an active service.
