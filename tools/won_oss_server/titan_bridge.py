#!/usr/bin/env python3
"""Titan-oriented bridge daemon.

Accepts either legacy short commands or stricter TITAN verbs and translates to
backend JSON actions for won_server.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Dict, List


def _need(parts: List[str], n: int, usage: str) -> None:
    if len(parts) < n:
        raise ValueError(f"usage:{usage}")


def parse_legacy_command(line: str) -> Dict[str, object]:
    parts: List[str] = line.strip().split()
    if not parts:
        return {"action": "PING"}

    cmd = parts[0].upper()

    # stricter Titan-style command forms:
    # TITAN DIR GET /TitanServers
    # TITAN ROUTE CHAT <lobby> <from> <message...>
    if cmd == "TITAN":
        _need(parts, 3, "TITAN <DIR|ROUTE> ...")
        domain = parts[1].upper()
        op = parts[2].upper()
        if domain == "DIR" and op == "GET":
            _need(parts, 4, "TITAN DIR GET <path>")
            return {"action": "TITAN_DIR_GET", "path": parts[3]}
        if domain == "ROUTE" and op == "CHAT":
            _need(parts, 6, "TITAN ROUTE CHAT <lobby_id> <from_player> <message...>")
            return {
                "action": "TITAN_ROUTE_CHAT",
                "lobby_id": parts[3],
                "from_player": parts[4],
                "message": " ".join(parts[5:]),
            }
        return {"action": "INVALID", "raw": line.strip(), "error": "unsupported_titan_command"}

    # legacy shorthand
    if cmd == "PING":
        return {"action": "PING"}
    if cmd == "HEALTH":
        return {"action": "HEALTH"}
    if cmd == "LOGIN":
        _need(parts, 2, "LOGIN <username> [password]")
        return {"action": "AUTH_LOGIN", "username": parts[1], "password": parts[2] if len(parts) > 2 else ""}
    if cmd == "REGISTER_PLAYER":
        _need(parts, 2, "REGISTER_PLAYER <player_id> [nickname...]")
        return {"action": "REGISTER_PLAYER", "player_id": parts[1], "nickname": " ".join(parts[2:]) or parts[1]}
    if cmd == "DIR_LIST":
        return {"action": "DIR_LIST", "path": parts[1] if len(parts) > 1 else "/Homeworld"}
    if cmd == "LOBBY_CREATE":
        _need(parts, 7, "LOBBY_CREATE <token> <owner> <name> <map> <region> <max> [password]")
        return {
            "action": "CREATE_LOBBY",
            "token": parts[1],
            "owner_id": parts[2],
            "name": parts[3],
            "map_name": parts[4],
            "region": parts[5],
            "max_players": int(parts[6]),
            "password": parts[7] if len(parts) > 7 else "",
        }
    if cmd == "LOBBY_LIST":
        return {"action": "LIST_LOBBIES", "region": parts[1] if len(parts) > 1 else None}
    if cmd == "LOBBY_JOIN":
        _need(parts, 3, "LOBBY_JOIN <lobby_id> <player_id> [password]")
        return {"action": "JOIN_LOBBY", "lobby_id": parts[1], "player_id": parts[2], "password": parts[3] if len(parts) > 3 else ""}
    if cmd == "MATCHMAKE":
        _need(parts, 2, "MATCHMAKE <player_id> [region] [game_type] [map]")
        return {
            "action": "MATCHMAKE",
            "player_id": parts[1],
            "region": parts[2] if len(parts) > 2 else None,
            "game_type": parts[3] if len(parts) > 3 else "homeworld",
            "map_name": parts[4] if len(parts) > 4 else None,
        }
    if cmd == "REGISTER_FACTORY":
        _need(parts, 5, "REGISTER_FACTORY <factory_id> <host> <region> <max_processes>")
        return {"action": "REGISTER_FACTORY", "factory_id": parts[1], "host": parts[2], "region": parts[3], "max_processes": int(parts[4])}
    if cmd == "FACTORY_START":
        _need(parts, 5, "FACTORY_START <factory_id> <process_name> <game_name> <port>")
        return {"action": "FACTORY_START_PROCESS", "factory_id": parts[1], "process_name": parts[2], "game_name": parts[3], "port": int(parts[4])}
    return {"action": "INVALID", "raw": line.strip(), "error": "unknown_command"}


async def call_backend(host: str, port: int, payload: Dict[str, object]) -> Dict[str, object]:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(line.decode("utf-8")) if line else {"ok": False, "error": "backend_no_response"}


class BridgeServer:
    def __init__(self, backend_host: str, backend_port: int):
        self.backend_host = backend_host
        self.backend_port = backend_port

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    payload = parse_legacy_command(raw.decode("utf-8"))
                    if payload.get("action") == "INVALID":
                        response = {"ok": False, "error": payload.get("error", "invalid_command"), "raw": payload.get("raw")}
                    else:
                        response = await call_backend(self.backend_host, self.backend_port, payload)
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                writer.write((json.dumps(response) + "\n").encode("utf-8"))
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def main_async(args: argparse.Namespace) -> None:
    bridge = BridgeServer(args.backend_host, args.backend_port)
    srv = await asyncio.start_server(bridge.handle_client, args.host, args.port)
    addrs = ", ".join(str(s.getsockname()) for s in srv.sockets or [])
    print(f"Titan bridge listening on {addrs} -> {args.backend_host}:{args.backend_port}")
    async with srv:
        await srv.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Titan command bridge daemon")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--backend-host", default="127.0.0.1")
    p.add_argument("--backend-port", type=int, default=9000)
    return p


if __name__ == "__main__":
    asyncio.run(main_async(build_parser().parse_args()))
