# Runtime manifest

Observed on 2026-07-26. This manifest contains no credentials.

## X5

```text
Board profile: x5
OS: Ubuntu 22.04.5 LTS, aarch64
Kernel: 6.1.83
Tailscale IPv4: 100.72.30.53
Go2 LocalAP: 192.168.12.1
DimOS upstream commit: 4a78e1400c4334c280970e4610c655d16b9661ae
unitree-webrtc-connect: 2.1.2
aioice: 0.10.2
physical gateway: 0.0.0.0:8765
physical MCP: 127.0.0.1:9990
simulation gateway: 100.72.30.53:8876
simulation MCP relay: 127.0.0.1:9992
PAWGUIDE_DIMOS_MCP_TIMEOUT_S: 15
```

The deployed copies of these files matched the repository byte-for-byte:

```text
provision/direct-go2-mcp.py
provision/check-dimos-tools.py
provision/run-dimos-x5.sh
provision/run-dimos-local-ap.py
provision/wait-for-dimos-mcp.sh
provision/pawguide-dimos.service
provision/pawguide-gateway.service
provision/x5/pawguide-sim-mcp-relay.service
```

## China server

```text
OS: Ubuntu 24.04, x86_64
Tailscale IPv4: 100.102.208.90
admin nginx: 100.102.208.90:7780
Hyper MCP relay: 100.102.208.90:9991
Rerun mux: 100.102.208.90:9879
```

The deployed dashboard HTML and JavaScript matched
`provision/pawguide-admin-dashboard.html` and
`provision/pawguide-admin-dashboard.js` byte-for-byte. The active nginx
configuration is tracked as `provision/pawguide-admin.nginx.conf`, and the
active tunnel unit is tracked as `provision/pawguide-hyper-tunnel.service`.

## Hyper

```text
OS: Ubuntu 22.04.5 LTS, x86_64
Kernel: 6.8.0-124-generic
GPU: NVIDIA RTX PRO 6000 Blackwell Server Edition
Driver: 580.159.03
GPU memory: 97887 MiB
Python: 3.12.13
dimos: 0.0.14b1
mujoco: 3.10.0
onnxruntime-gpu: 1.27.0
torch: 2.13.0
rerun-sdk: 0.32.0
unitree-webrtc-connect: 2.1.2
numpy: 2.4.6
scipy: 1.18.0
```

The active runit entrypoints matched these tracked files byte-for-byte:

```text
provision/hyper/pawguide-dimos.run
provision/hyper/pawguide-mcp-relay.run
```

At inspection time both runit services were healthy. The active environment
selected `DIMOS_MUJOCO_FIXTURE=concept_gate`.
