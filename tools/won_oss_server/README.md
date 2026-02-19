# WON OSS Server (Homeworld-oriented)

This stack now includes:

- `won_server.py` (JSON core service)
- `titan_bridge.py` (text/command Titan-style bridge)
- `titan_binary_gateway.py` (binary gateway with state machine + Titan message mode)
- `titan_messages.py` (minimal Titan-like message schemas/codecs)

## Newly completed next step toward launchable flow

### 1) Titan-like message schema module (MVP)

`tools/won_oss_server/titan_messages.py` now defines deterministic message codecs for:

- `AUTH_LOGIN_REQ / AUTH_LOGIN_REPLY`
- `DIR_GET_REQ / DIR_GET_REPLY`
- `ROUTE_REGISTER_REQ / ROUTING_STATUS_REPLY`

Envelope format:
- `msg_type:u16`
- `status:u16`
- `payload_len:u32`
- payload (length-prefixed UTF-8 fields)

### 2) Typed binary gateway + protocol state machine

The binary gateway enforces connection state:

1. `AUTH_LOGIN` -> authenticated
2. `REGISTER_PLAYER` -> player-ready
3. lobby create/join
4. route register per lobby
5. route chat / start game / poll events

### 3) Titan message passthrough mode in gateway

New gateway opcode:

- `0x70` (`OP_TITAN_MESSAGE`) with field `packet_hex`

The gateway decodes Titan-like packets from `packet_hex`, maps them to backend actions, then returns encoded Titan-like reply packets in `packet_hex`.

### 4) Backend route semantics tightened

- `TITAN_ROUTE_REGISTER` validates lobby membership.
- `TITAN_ROUTE_CHAT` requires prior route registration.
- `TITAN_START_GAME` preserves owner/min-player checks and emits `game_launch` events.

## Binary frame format (gateway envelope)

- 4-byte big-endian frame length
- body:
  - 1-byte opcode
  - 2-byte field count
  - repeated fields: `[key_len:u8][key][val_len:u16][value]`

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

This is still not packet-identical historical WON/Titan, but now includes explicit Titan-like message schemas, a protocol state machine, and golden-packet coverage for core auth/dir/routing-register paths.
