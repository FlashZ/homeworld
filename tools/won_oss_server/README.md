# WON OSS Server (Homeworld-oriented)

This stack now includes:

- `won_server.py` (JSON core service)
- `titan_bridge.py` (text/command Titan-style bridge)
- `titan_binary_gateway.py` (binary gateway with state machine)

## Newly completed next step toward launchable flow

### Binary protocol and state-machine upgrade

The binary gateway now enforces connection state for a realistic flow:

1. `AUTH_LOGIN` -> authenticated
2. `REGISTER_PLAYER` -> player-ready
3. `CREATE_LOBBY` / `JOIN_LOBBY`
4. `ROUTE_REGISTER` per-lobby
5. `ROUTE_CHAT`, `START_GAME`, `POLL_EVENTS`

### Wire format (typed key/value, no JSON payload-in-frame)

- 4-byte big-endian frame length
- frame body:
  - 1-byte opcode
  - 2-byte field count
  - repeated fields: `[key_len:u8][key][val_len:u16][value]`

Values are UTF-8 strings on the wire and converted to primitive types where possible.

### Supported binary opcodes

- `0x01` (`OP_PING`) -> `PING`
- `0x10` (`OP_DIR_GET`) -> `TITAN_DIR_GET`
- `0x20` (`OP_ROUTE_CHAT`) -> `TITAN_ROUTE_CHAT` (requires route registration)
- `0x30` (`OP_AUTH_LOGIN`) -> `AUTH_LOGIN`
- `0x31` (`OP_REGISTER_PLAYER`) -> `REGISTER_PLAYER` (requires auth)
- `0x32` (`OP_CREATE_LOBBY`) -> `CREATE_LOBBY` (requires player-ready)
- `0x33` (`OP_JOIN_LOBBY`) -> `JOIN_LOBBY`
- `0x34` (`OP_START_GAME`) -> `TITAN_START_GAME`
- `0x35` (`OP_POLL_EVENTS`) -> `ROUTE_POLL`
- `0x36` (`OP_ROUTE_REGISTER`) -> `TITAN_ROUTE_REGISTER`

### Backend launch-path semantics tightened

- `TITAN_ROUTE_REGISTER` now validates lobby membership before route registration.
- `TITAN_ROUTE_CHAT` now requires prior route registration for sender.
- `TITAN_START_GAME` still performs owner/min-player checks and emits `game_launch` events.

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

This is still not full packet-identical WON/Titan compatibility, but now uses a typed binary frame body and a stricter connection state machine that is closer to real protocol behavior.
