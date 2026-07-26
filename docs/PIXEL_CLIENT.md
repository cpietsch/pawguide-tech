# Phone and ring client contract

The phone and ring application is maintained in a separate repository. This
document defines its complete PawGuide integration boundary. The
machine-readable source of truth is
[`../contracts/pawguide-openapi.json`](../contracts/pawguide-openapi.json).

The app calls the X5 gateway over its local/private network path. It never
opens a Unitree WebRTC connection, sends MCP directly, or controls raw
velocity. Ring transport, audio, haptics, inference, and UI implementation are
outside this repository.

## Authority split

| Operation | Operator credential | Developer credential | Model output |
| --- | ---: | ---: | ---: |
| Read capabilities and state | yes | yes | no direct access |
| Maintain heartbeat | yes | no | no |
| Reset STOP latch | yes | no | no |
| STOP | yes | yes | bypassed |
| Submit other allowlisted commands | yes | restricted subset | proposes only |
| Raw velocity or arbitrary sport command | unavailable | unavailable | unavailable |

Any language or intent model may produce only data matching
[`../contracts/local-agent-output.schema.json`](../contracts/local-agent-output.schema.json).
The app validates that output, checks current gateway capabilities, and creates
the command UUID. A model never receives generic HTTP, MCP, heartbeat, arming,
or STOP tools.

## Connection and safety state

On connection:

```text
GET /health
GET /v1/capabilities
GET /v1/state
```

The app must read capabilities instead of assuming an action or waypoint is
available. A physical session requires `motion_capable=true`.

The operator heartbeat payload is:

```json
{"source":"phone-ring-operator"}
```

Send it to `POST /v1/heartbeat` every 500 ms with a monotonic scheduler. Stop
sending it whenever the foreground operator session, phone-to-X5 link, or app
safety state is unhealthy. The X5 then latches STOP within the advertised
timeout.

There is no inferred arming. Resetting STOP and maintaining the heartbeat are
deterministic application behavior, never model behavior. From any active
state, a STOP request bypasses speech and inference.

## Commands and retries

Protected requests use:

```http
Authorization: Bearer <operator credential>
Content-Type: application/json
```

Example bounded physical destination command:

```json
{
  "command_id": "3411c2be-1761-49eb-8870-9d7bf20b8119",
  "action": "go_to_waypoint",
  "arguments": {
    "waypoint_id": "demo_gate"
  }
}
```

Reuse the same `command_id` when retrying an uncertain response. The gateway
caches recent results to prevent duplicate execution.

`accepted=true` means the action was accepted and dispatched. It is not proof
that a physical movement or gesture completed. Until the gateway exposes a
normalized completion event, the app must not chain physical actions solely
from that response or from a fixed delay.

The API action enum is:

```text
stop
pause
reset_stop
stand_up
sit_down
greeting
go_to_waypoint
start_patrol
return_home
```

Capabilities and role restrictions remain authoritative. In the current
physical profile, `home` and `demo_gate` are the only waypoint IDs and
`start_patrol` is omitted from the advertised/accepted actions because the
direct Go2 bridge does not implement it.

## Browser command center exception

The China command center is an operator-only kiosk. The browser does not hold
or request a credential; China nginx injects the X5 operator credential
server-side for the physical API route. This convenience is specific to that
private admin surface and does not change the app-facing authentication
contract.

## Integration acceptance

The app/ring integration is ready only when it proves:

1. connection validation against health, capabilities, and state;
2. a monotonic 500 ms heartbeat during a healthy operator session;
3. heartbeat termination on app, link, or ring-session loss;
4. deterministic STOP without inference;
5. no automatic reset after STOP;
6. exact action and waypoint validation;
7. UUID reuse for uncertain retries;
8. no action chaining based only on command acceptance;
9. token values remain outside logs, analytics, screenshots, and source.
