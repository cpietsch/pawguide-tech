# First Go2 motion test — no LLM

This test proves the shortest useful path:

```text
manual console -> X5 gateway -> local DimOS MCP -> Go2 WebRTC
```

It does not test mapping, navigation, autonomous roaming, the ring or any LLM.

## Preconditions

- X5 is on its official 5 V/5 A supply beside the robot, not mounted.
- X5 fan is running and unobstructed.
- Go2 battery is charged.
- Only the X5 is connected to the Go2 AP; close the Unitree app.
- A stable stand supports the robot with every foot clear of the floor.
- Nobody is within the leg sweep.
- One person operates the console; a second watches the robot and power state.
- The area is clear even if the robot unexpectedly transitions posture.

There is no hardware emergency stop or remote controller. Do not perform this
test alone or in a public area.

## Terminal A — logs and emergency disable

Open an SSH session to the X5 and prepare:

```bash
sudo journalctl -u pawguide-dimos.service \
  -u pawguide-gateway.service -f
```

Keep another command ready in a second tab:

```bash
cd ~/pawguide-x5-mvp
sudo provision/disable-real-motion.sh
```

Do not execute it unless you need to stop and return to mock mode.

## Terminal B — validate and enable

From the extracted bundle:

```bash
cd ~/pawguide-x5-mvp
sudo provision/check-x5-readiness.sh
sudo provision/enable-real-motion.sh \
  --i-understand-this-can-move-the-robot
sudo /opt/pawguide/bin/diagnose-dimos-x5.sh
```

Expected health:

```bash
curl -fsS http://127.0.0.1:8765/health
```

The result must contain:

```json
{"status":"ok","adapter":"dimos_mcp","motion_capable":true}
```

Motion is still blocked because STOP starts latched.

## Terminal C — local operator console

Run the console on the X5:

```bash
sudo -u pawguide env \
  PAWGUIDE_OPERATOR_TOKEN_FILE=/etc/pawguide/operator.token \
  PAWGUIDE_GATEWAY_URL=http://127.0.0.1:8765 \
  /opt/pawguide/.venv/bin/pawguide-operator
```

First inspect:

```text
state
```

Confirm `stop_latched` is `true`. With the robot supported and the spotter
ready, enter one command at a time:

```text
arm
stand
```

Wait for the posture transition to finish. Then:

```text
sit
stop
state
quit
```

The final state must be stopped and latched. `quit`, Ctrl-C, EOF, SIGHUP and
SIGTERM request STOP; a hard process/network loss stops heartbeat and the
gateway latches STOP within two seconds.

## Floor greeting test

Only after the supported test passes:

1. Disable real motion.
2. Place the Go2 on a level, non-slip floor in a clear area.
3. Re-enable real motion and reopen the console.
4. Enter:

```text
state
arm
stand
hello
sit
stop
quit
```

Wait for each action to finish before typing the next. `hello` is the only
entertainment action exposed; arbitrary sport commands remain unavailable.

## Watchdog test

With the robot standing in a clear area:

1. Enter `arm`, then `stand`.
2. Terminate the SSH session or disconnect the X5 uplink.
3. Verify the gateway latches STOP within two seconds.
4. Reconnect and run `state`; `last_stop_reason` should report heartbeat
   timeout.
5. Enter `sit` only after starting a new console and explicitly entering `arm`.

Note that STOP cancels locomotion; it does not automatically force a standing
robot to sit.

## Pass criteria

- The console cannot act before `arm`.
- `stand`, `sit` and `hello` map to their exact Unitree commands.
- `stop` latches immediately.
- Console exit requests STOP.
- Heartbeat loss latches STOP within two seconds.
- The gateway remains bound locally/Tailscale rather than to the public network.
- No unexpected reboot, Wi-Fi route change, thermal issue or DimOS restart.

After this passes, proceed to map creation and exact waypoint tests.
