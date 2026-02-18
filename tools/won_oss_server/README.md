# WON OSS Server (Homeworld-oriented)

This stack now includes a JSON backend plus a stricter Titan-oriented bridge layer.

- `won_server.py` (core service)
- `titan_bridge.py` (legacy + `TITAN ...` command translator)

## Newly completed high-value items

1. **Typed Homeworld data objects**
   - Implements and publishes key Titan/Homeworld-style object names:
     - `HomeworldValidVersions`
     - `Description`
     - `RoomFlags`
     - `__RSClientCount`
     - `__FactCur_RoutingServHWGame`
     - `__FactTotal_RoutingServHWGame`
     - `__ServerUptime`

2. **Stricter bridge mapping**
   - Supports explicit forms:
     - `TITAN DIR GET <path>`
     - `TITAN ROUTE CHAT <lobby_id> <from_player> <message...>`
   - Also keeps shorthand commands for easier ops.

3. **Persistent sessions and routing events**
   - Sessions persisted in SQLite (`sessions` table)
   - Routing/chat events persisted in SQLite (`events` table)

4. **Managed factory process supervision**
   - `FACTORY_START_PROCESS` now starts a managed subprocess placeholder and tracks live managed process count.
   - Factory object counters in `/TitanServers` are updated with running/total process info.

## Existing implemented features

- Simple auth with account-on-first-login (`AUTH_LOGIN`, `AUTH_VALIDATE`), no CD-keys.
- Lobby lifecycle with optional password.
- Matchmaking and server listing.
- Directory service with `/Homeworld` and `/TitanServers`.
- Health/metrics observability.
- SQLite persistence.

## Run core server

```bash
python3 tools/won_oss_server/won_server.py --host 0.0.0.0 --port 9000 --db-path tools/won_oss_server/won_server.db
```

## Run bridge daemon

```bash
python3 tools/won_oss_server/titan_bridge.py --host 0.0.0.0 --port 9100 --backend-host 127.0.0.1 --backend-port 9000
```

## Example bridge commands

```text
LOGIN player1 mypass
REGISTER_PLAYER p1 Kushan
TITAN DIR GET /TitanServers
TITAN ROUTE CHAT lob_abc p1 hello world
```

## Notes

This remains a practical compatibility stack, not a full binary packet-identical WON/Titan replacement yet.
