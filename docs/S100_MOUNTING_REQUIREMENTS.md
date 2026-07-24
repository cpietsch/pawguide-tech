# Go2 S100 payload harness brief

Do not print a dimensioned mount before measuring the actual Go2, S100 cooling
assembly, mobile DC supply, Wi-Fi antennas and Pixel case. D-Robotics publishes
an official S100 STEP model, which should seed the CAD layout, but the assembled
cooler, cables and power system still need physical measurement. This brief
fixes the architecture and acceptance criteria.

## Layout

Use a quick-removable padded saddle with three independent modules:

```text
front
┌──────────────────────────────────────────────┐
│ Pixel cradle       cable channel             │
│ speaker exposed    USB strain relief         │
├──────────────────────────────────────────────┤
│ S100 + heatsink/fan central and low           │
├──────────────────────────────────────────────┤
│ fused DC supply    central and low           │
└──────────────────────────────────────────────┘
rear
```

The S100 and its mobile power system should sit near the longitudinal and
lateral center of the torso. The Pixel may angle upward for screen access, but
must remain inside the body footprint as far as practical. Keep the phone
speaker, microphones, buttons, cameras, the S100 Wi-Fi antenna and cellular
antenna areas unobstructed.

Use mechanical retention for every module. Hook-and-loop may provide preload,
but it must not be the only thing preventing a component from leaving the
robot. Add one tool-free master release for the complete saddle.

## Interface and materials

- Two shaped saddle rails joined by cross-members form the printable structure.
- A replaceable 2–3 mm TPU, neoprene or EVA layer contacts the robot body.
- Use two independent non-stretch straps with locking buckles and keepers.
- Route straps only across measured static body surfaces; never across joints,
  moving covers, vents, cameras, lidar apertures, battery release or controls.
- Print functional parts in PETG or ASA. Avoid PLA for a warm exhibition hall
  or a sun-heated transport case.
- Use heat-set inserts or captive nuts for frequently removed modules.
- Round every robot-facing edge and cover exposed fastener ends.

The fan needs an open intake and exhaust path. Do not let the phone or battery
become the S100's fan wall. Provide at least the fan manufacturer's required
clearance and verify it with a thermal soak. The S100 documents five MAIN/MCU/BPU
temperature sensors and an operating range of 0–45 °C; expose those readings in
the soak log.

## Power system

The former small-board USB power-bank assumption is invalid. The S100 accepts
12–20 V DC through its barrel input. D-Robotics recommends 70 W for typical
loads, supplies a 90 W adapter, and specifies up to 150 W for extreme loads.

- Use a mobile source and DC conversion path rated for sustained output with
  measured headroom; a nominal USB-PD wattage alone is not evidence.
- Add a fuse close to the energy source and a physical master disconnect that
  the spotter can reach without touching the moving robot.
- Use the specified 2.5 mm inner / 6 mm outer barrel geometry and add connector
  retention and strain relief. Never let the barrel plug carry cable weight.
- Validate cold boot, CPU/BPU peak load, fan startup, Wi-Fi and USB load
  together. Any brownout, unexpected reset or connector heating fails the
  harness gate.
- Keep the supplied 90 W adapter for bench commissioning; select the mobile
  source only after measuring actual PawGuide consumption.

## Cable design

- Use the shortest practical USB data and power leads.
- Add strain relief at both ends of every connector.
- Keep every service loop inside the torso footprint and away from leg sweep.
- Separate removable module cables from the saddle with labeled connectors.
- The Pixel-to-S100 tether must be replaceable without dismantling the saddle.
- The Pixel data cable connects to an S100 USB-A host port. J16 USB-C is only
  for flashing/debugging and must remain accessible.
- No connector may carry the weight of a cable or module.

## Measurement sheet

Record millimetres and grams:

| Parameter | Measurement |
|---|---:|
| usable top-body length | |
| usable top-body width, front/centre/rear | |
| top-surface crown/radius at rail positions | |
| safe strap path circumference, front/rear | |
| clearance to each leg through stand/sit/tuck | |
| clearance to battery and controls | |
| S100 or S100P model | |
| S100 enclosure length × width × height | |
| S100 mounting-hole pattern and screw size | |
| S100 assembly mass with cooler/Wi-Fi module | |
| fan intake/exhaust locations | |
| Wi-Fi antenna position and keep-out | |
| DC supply/converter length × width × height and mass | |
| DC source continuous voltage/current/wattage | |
| fuse rating and disconnect location | |
| barrel-plug retention and cable bend radius | |
| Pixel-with-case dimensions and mass | |
| required USB plug depth and bend radius | |
| saddle, straps and fastener mass | |
| total payload mass | |

Also photograph the top, both sides, front and rear with a ruler in frame.

## CAD deliverables

1. Parameterized STEP source for the saddle and each cradle.
2. Separate printable STLs, not one monolithic print.
3. A drilling-free assembly drawing and fastener BOM.
4. Cable-routing drawing with connector access.
5. A simple centre-of-mass worksheet using measured component masses.
6. One spare Pixel latch and one spare strap anchor in the print set.

## Physical acceptance gate

Perform these tests with robot motion disabled first:

1. Pull each module firmly in every direction; nothing releases or contacts the
   robot with a hard edge.
2. Move every leg manually through its available safe range and inspect cable
   and strap clearance.
3. Run DimOS, Wi-Fi, Pixel tethering and the intended S100 model load for
   30 minutes; record all chip sensors, enclosure, connector and battery
   temperatures plus supply voltage.
4. Support the Go2 off the ground and exercise stand/sit transitions at minimum
   speed.
5. Walk at minimum speed, then STOP, checking saddle slip after every run.
6. Repeat with the Pixel USB tether disconnected and reconnected.
7. Verify the entire payload can be removed quickly without tools.

Do not progress to public roaming if the saddle shifts, a strap stretches, a
cable can enter a leg path, the supply browns out, cooling throttles, or the
phone speaker is muffled.
