# WON OSS Server (Homeworld-oriented)

This stack now includes:

- `won_server.py` (JSON core service)
- `titan_bridge.py` (text/command Titan-style bridge)
- `titan_binary_gateway.py` (minimal binary frame gateway)

## Newly completed next step

### Binary gateway MVP

A new binary transport path is now available for incremental client compatibility work.

**Wire format (MVP):**
- 4-byte big-endian frame length
- frame body:
  - 1-byte opcode
  - UTF-8 JSON payload bytes

**Supported binary opcodes:**
- `0x01` (`OP_PING`) -> `PING`
- `0x10` (`OP_DIR_GET`) -> `TITAN_DIR_GET`
- `0x20` (`OP_ROUTE_CHAT`) -> `TITAN_ROUTE_CHAT`
- `0x30` (`OP_AUTH_LOGIN`) -> `AUTH_LOGIN`

This is intentionally not full historical Titan packet parity yet, but it creates a real binary listener so compatibility can evolve away from command-only bridging.

## Previously implemented high-value items

1. Typed Homeworld data objects (`HomeworldValidVersions`, `Description`, `RoomFlags`, `__RSClientCount`, `__FactCur_RoutingServHWGame`, `__FactTotal_RoutingServHWGame`, `__ServerUptime`)
2. Stricter Titan bridge mapping (`TITAN DIR GET`, `TITAN ROUTE CHAT`)
3. Persistent sessions and routing events
4. Managed factory process supervision

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

This remains a practical compatibility stack, not a full binary packet-identical WON/Titan replacement yet.
