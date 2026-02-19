# WON OSS Server Testing Guide

This checklist covers the tests you should run to validate backend correctness, protocol compatibility progress, and real-game interoperability.

## 1) Fast local correctness checks (run every change)

1. Syntax/compile check:
   ```bash
   python3 -m py_compile \
     tools/won_oss_server/won_server.py \
     tools/won_oss_server/titan_bridge.py \
     tools/won_oss_server/titan_binary_gateway.py \
     tools/won_oss_server/titan_messages.py \
     tools/won_oss_server/packet_sniffer_framework.py
   ```
2. Full unit/integration suite:
   ```bash
   python3 -m unittest discover -s tools/won_oss_server/tests -v
   ```

## 2) Backend API behavior checks

Validate these flows through JSON actions (direct socket or existing test harness):

- Auth/session lifecycle:
  - `AUTH_LOGIN`
  - `AUTH_VALIDATE`
- Player/lobby lifecycle:
  - `REGISTER_PLAYER`
  - `CREATE_LOBBY`
  - `JOIN_LOBBY`
  - `LEAVE_LOBBY`
  - `LIST_LOBBIES`
- Match/server/factory path:
  - `REGISTER_FACTORY`
  - `FACTORY_START_PROCESS`
  - `REGISTER_SERVER`
  - `MATCHMAKE`
- Routing/data object path:
  - `TITAN_ROUTE_REGISTER`
  - `TITAN_ROUTE_JOIN`
  - `TITAN_ROUTE_SEND_CHAT`
  - `TITAN_ROUTE_SET_DATA_OBJECT`
  - `TITAN_ROUTE_GET_DATA_OBJECT`
  - `ROUTE_POLL`
- Observability:
  - `HEALTH`
  - `METRICS`

## 3) Binary gateway protocol checks

Run packet-level tests to confirm typed frame and state-machine behavior:

- Connection state enforcement (`CONNECTED -> AUTHED -> PLAYER_READY`)
- Titan passthrough opcode path (`OP_TITAN_MESSAGE`)
- Auth packet request/reply
- Directory get request/reply
- Route register/join/chat/data-object packet handling
- Two-player lobby-to-launch (`OP_START_GAME`) and launch event polling

These are covered by `tools/won_oss_server/tests/test_server.py` and should stay green.

## 4) Persistence/restart checks

Manually validate with a non-empty DB file:

1. Start `won_server.py` with a persistent sqlite path.
2. Login users, create lobby, join users, set route data object.
3. Restart server process.
4. Verify persisted entities are present (users/lobbies/data objects).
5. Verify expected ephemeral behavior is reset where intended (e.g., live connection/session queues if not persisted).

## 5) Real-client interoperability checks (required for "ready to play")

Run these with Homeworld pointed at your test services:

1. Launch client A and client B.
2. A logs in and creates lobby.
3. B logs in and joins lobby.
4. A starts game.
5. Both clients receive launch handoff and transition to game.
6. Validate chat and directory visibility before launch.

If any step fails, capture and diff packets using the sniffer framework:

```bash
python3 tools/won_oss_server/packet_sniffer_framework.py proxy \
  --listen-host 0.0.0.0 --listen-port 4000 \
  --target-host 127.0.0.1 --target-port 20000 \
  --capture-file /tmp/won_capture.ndjson --decode-titan
```

Then summarize:

```bash
python3 tools/won_oss_server/packet_sniffer_framework.py summary \
  --capture-file /tmp/won_capture.ndjson
```

## 6) Regression checklist before each release

- All commands in section 1 pass.
- No protocol state-machine regressions in packet tests.
- Two-player launch flow passes in automated tests.
- Manual client-A/client-B host/join/start flow passes.
- Packet captures for successful flow are archived as baseline artifacts for future comparison.
