#!/usr/bin/env python3
"""Minimal binary Titan gateway.

Wire format (MVP):
- 4-byte big-endian length (N)
- N-byte frame payload:
  - 1-byte opcode
  - UTF-8 JSON payload bytes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
from dataclasses import dataclass
from typing import Dict, Tuple

# Core opcodes
OP_PING = 0x01
OP_DIR_GET = 0x10
OP_ROUTE_CHAT = 0x20
OP_AUTH_LOGIN = 0x30

# Session-flow opcodes for launchable flow
OP_REGISTER_PLAYER = 0x31
OP_CREATE_LOBBY = 0x32
OP_JOIN_LOBBY = 0x33
OP_START_GAME = 0x34
OP_POLL_EVENTS = 0x35
OP_ROUTE_REGISTER = 0x36


@dataclass
class ConnectionContext:
    token: str | None = None
    player_id: str | None = None


def encode_frame(opcode: int, payload: Dict[str, object]) -> bytes:
    body = bytes([opcode]) + json.dumps(payload).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def decode_frame(data: bytes) -> Tuple[int, Dict[str, object]]:
    if not data:
        raise ValueError("empty_frame")
    opcode = data[0]
    payload = json.loads(data[1:].decode("utf-8")) if len(data) > 1 else {}
    return opcode, payload


def opcode_to_action(opcode: int, payload: Dict[str, object], ctx: ConnectionContext) -> Dict[str, object]:
    if opcode == OP_PING:
        return {"action": "PING"}
    if opcode == OP_DIR_GET:
        return {"action": "TITAN_DIR_GET", "path": str(payload.get("path", "/TitanServers"))}
    if opcode == OP_ROUTE_CHAT:
        return {
            "action": "TITAN_ROUTE_CHAT",
            "lobby_id": str(payload["lobby_id"]),
            "from_player": str(payload.get("from_player", ctx.player_id or "unknown")),
            "message": str(payload["message"]),
        }
    if opcode == OP_AUTH_LOGIN:
        return {
            "action": "AUTH_LOGIN",
            "username": str(payload.get("username", "guest")),
            "password": str(payload.get("password", "")),
        }
    if opcode == OP_REGISTER_PLAYER:
        return {
            "action": "REGISTER_PLAYER",
            "player_id": str(payload["player_id"]),
            "nickname": str(payload.get("nickname", payload["player_id"])),
        }
    if opcode == OP_CREATE_LOBBY:
        if not ctx.token:
            return {"action": "INVALID", "error": "auth_required"}
        return {
            "action": "CREATE_LOBBY",
            "token": ctx.token,
            "owner_id": str(payload.get("owner_id", ctx.player_id or "")),
            "name": str(payload.get("name", "Lobby")),
            "map_name": str(payload.get("map_name", "Garden")),
            "region": str(payload.get("region", "global")),
            "max_players": int(payload.get("max_players", 4)),
        }
    if opcode == OP_JOIN_LOBBY:
        return {
            "action": "JOIN_LOBBY",
            "lobby_id": str(payload["lobby_id"]),
            "player_id": str(payload.get("player_id", ctx.player_id or "")),
            "password": str(payload.get("password", "")),
        }
    if opcode == OP_START_GAME:
        return {
            "action": "TITAN_START_GAME",
            "lobby_id": str(payload["lobby_id"]),
            "requester_id": str(payload.get("requester_id", ctx.player_id or "")),
            "port": payload.get("port"),
        }
    if opcode == OP_POLL_EVENTS:
        return {"action": "ROUTE_POLL", "player_id": str(payload.get("player_id", ctx.player_id or "")), "after_seq": int(payload.get("after_seq", 0))}
    if opcode == OP_ROUTE_REGISTER:
        return {"action": "TITAN_ROUTE_REGISTER", "player_id": str(payload.get("player_id", ctx.player_id or ""))}
    return {"action": "UNKNOWN_BINARY_OPCODE", "opcode": opcode}


def action_to_response_opcode(opcode: int) -> int:
    return opcode


async def call_backend(host: str, port: int, payload: Dict[str, object]) -> Dict[str, object]:
    reader, writer = await asyncio.open_connection(host, port)
    writer.write((json.dumps(payload) + "\n").encode("utf-8"))
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(line.decode("utf-8")) if line else {"ok": False, "error": "backend_no_response"}


class BinaryGatewayServer:
    def __init__(self, backend_host: str, backend_port: int):
        self.backend_host = backend_host
        self.backend_port = backend_port

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ctx = ConnectionContext()
        try:
            while True:
                hdr = await reader.readexactly(4)
                length = struct.unpack(">I", hdr)[0]
                if length <= 0 or length > 10_000_000:
                    raise ValueError("invalid_frame_length")
                body = await reader.readexactly(length)
                opcode, payload = decode_frame(body)
                action = opcode_to_action(opcode, payload, ctx)

                if action.get("action") == "INVALID":
                    response = {"ok": False, "error": action.get("error", "invalid")}
                elif action.get("action") == "UNKNOWN_BINARY_OPCODE":
                    response = {"ok": False, "error": "unknown_binary_opcode", "opcode": opcode}
                else:
                    try:
                        response = await call_backend(self.backend_host, self.backend_port, action)
                    except Exception as exc:
                        response = {"ok": False, "error": str(exc)}

                # maintain connection context
                if opcode == OP_AUTH_LOGIN and response.get("ok") and isinstance(response.get("token"), str):
                    ctx.token = str(response["token"])
                if opcode == OP_REGISTER_PLAYER and response.get("ok"):
                    player = response.get("player", {})
                    if isinstance(player, dict) and isinstance(player.get("player_id"), str):
                        ctx.player_id = str(player["player_id"])

                wire = encode_frame(action_to_response_opcode(opcode), response)
                writer.write(wire)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:
            writer.write(encode_frame(0xFF, {"ok": False, "error": str(exc)}))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def main_async(args: argparse.Namespace) -> None:
    srv = BinaryGatewayServer(args.backend_host, args.backend_port)
    server = await asyncio.start_server(srv.handle_client, args.host, args.port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"Titan binary gateway listening on {addrs} -> {args.backend_host}:{args.backend_port}")
    async with server:
        await server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Minimal binary Titan gateway")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9200)
    p.add_argument("--backend-host", default="127.0.0.1")
    p.add_argument("--backend-port", type=int, default=9000)
    return p


if __name__ == "__main__":
    asyncio.run(main_async(build_parser().parse_args()))
