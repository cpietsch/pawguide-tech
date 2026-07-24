# Go2 X5 payload harness brief

Do not strap the X5 to the Go2 for the first bench and posture tests. Prove the
network, heartbeat, STOP and WebRTC paths with the X5 beside the robot first.

Before roaming, use a quick-removable padded saddle with three independent
modules:

```text
front
┌──────────────────────────────────────────────┐
│ Pixel cradle       cable channel             │
│ speaker exposed    USB strain relief         │
├──────────────────────────────────────────────┤
│ X5 + heatsink/fan  central and low           │
├──────────────────────────────────────────────┤
│ 5 V power system   central and low           │
└──────────────────────────────────────────────┘
rear
```

The X5 requires a stable 5 V/5 A supply. Use the official supply for the bench.
Select a mobile USB-C supply only after confirming it holds the required
5 V/high-current mode under DimOS, Wi-Fi and USB load. Any reboot, voltage sag,
connector heating or fan obstruction fails the mounting gate.

## Mechanical requirements

- Two padded saddle rails with two independent non-stretch locking straps.
- Mechanical retention for every component; hook-and-loop is not the sole
  retention method.
- X5 and battery close to the torso's longitudinal and lateral centre.
- No strap or cable across joints, vents, cameras, lidar, battery release,
  controls or moving body panels.
- Open fan intake and exhaust with a 30-minute loaded thermal soak.
- Short USB leads with strain relief at both connectors.
- All service loops inside the torso footprint and outside every leg sweep.
- PETG or ASA functional prints with rounded robot-facing edges.
- One tool-free master release for the complete saddle.

## Measurement sheet

| Parameter | Measurement |
|---|---:|
| usable top-body length and widths | |
| top crown/radius at rail positions | |
| safe front/rear strap paths | |
| leg clearance through stand/sit/tuck | |
| X5 enclosure dimensions and mass | |
| X5 hole pattern and fan keep-out | |
| mobile power dimensions and mass | |
| Pixel dimensions and mass | |
| cable plug depths and bend radii | |
| saddle/strap/fastener mass | |
| complete payload mass | |

## Acceptance gate

1. Pull every retained module firmly in all directions with motion disabled.
2. Check straps and cables against the complete leg/body motion envelope.
3. Run DimOS, Go2 Wi-Fi and Pixel tethering for 30 minutes while logging
   temperatures and checking supply stability.
4. Repeat supported-off-ground stand/sit and heartbeat-loss tests.
5. Walk at minimum speed, STOP, and inspect saddle shift after every run.
6. Disconnect and reconnect USB; heartbeat loss must latch STOP.
7. Confirm the complete payload can be removed without tools.

The future S100 harness has separate requirements in
`docs/S100_MOUNTING_REQUIREMENTS.md`.
