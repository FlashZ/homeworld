# WON OSS Server (Homeworld-oriented)

This stack now includes:

- `won_server.py` (JSON core service)
- `titan_bridge.py` (text/command Titan-style bridge)
- `titan_binary_gateway.py` (binary gateway with session flow)

## Newly completed next step toward launchable flow

### Binary session flow MVP

The binary gateway now supports a session-oriented multiplayer flow that exercises:

1. auth
2. player registration
3. lobby create/join
4. route registration
5. start-game handoff (launch event broadcast)

### Wire format (MVP)

- 4-byte big-endian frame length
- frame body:
  - 1-byte opcode
  - UTF-8 JSON payload bytes

### Supported binary opcodes

- `0x01` (`OP_PING`) -> `PING`
- `0x10` (`OP_DIR_GET`) -> `TITAN_DIR_GET`
- `0x20` (`OP_ROUTE_CHAT`) -> `TITAN_ROUTE_CHAT`
- `0x30` (`OP_AUTH_LOGIN`) -> `AUTH_LOGIN`
- `0x31` (`OP_REGISTER_PLAYER`) -> `REGISTER_PLAYER`
- `0x32` (`OP_CREATE_LOBBY`) -> `CREATE_LOBBY` (uses session token)
- `0x33` (`OP_JOIN_LOBBY`) -> `JOIN_LOBBY`
- `0x34` (`OP_START_GAME`) -> `TITAN_START_GAME`
- `0x35` (`OP_POLL_EVENTS`) -> `ROUTE_POLL`
- `0x36` (`OP_ROUTE_REGISTER`) -> `TITAN_ROUTE_REGISTER`

### Backend additions for launch path

- `TITAN_ROUTE_REGISTER` action (explicit routing registration ack)
- `TITAN_START_GAME` action:
  - validates owner + minimum players
  - allocates/reuses server capacity (including factory path)
  - emits `game_launch` event to all lobby players

## Run core server

```bash
python3 tools/won_oss_server/won_server.py --host 0.0.0.0 --port 9000 --db-path tools/won_oss_server/won_server.db
```

## Run text bridge

```bash
python3 tools/won_oss_server/titan_bridge.py --host 0.0.0.0 --port 9100 --backend-host 127.0.0.1 --backend-port 9000
```

## Run binary gateway

```bash
python3 tools/won_oss_server/titan_binary_gateway.py --host 0.0.0.0 --port 9200 --backend-host 127.0.0.1 --backend-port 9000
```

## Notes

This is still not full packet-identical WON/Titan compatibility, but now includes a binary session flow that can drive a two-player lobby-to-launch sequence in integration tests.
