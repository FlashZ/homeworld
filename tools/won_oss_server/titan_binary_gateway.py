#!/usr/bin/env python3
"""Binary Titan gateway with session state machine.

MVP wire format:
- 4-byte big-endian frame length
- body:
  - 1-byte opcode
  - 2-byte field count
  - repeated fields: [1-byte key_len][key][2-byte val_len][value]

Values are UTF-8 strings; numeric values are stringified.
"""

from __future__ import annotations

import argparse
import asyncio
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Tuple
import json
import binascii

from tools.won_oss_server.titan_messages import (
    STATUS_FAIL,
    STATUS_OK,
    AuthLoginReply,
    DirGetReply,
    RoutingStatusReply,
    decode_request,
)

OP_PING = 0x01
OP_DIR_GET = 0x10
OP_ROUTE_CHAT = 0x20
OP_AUTH_LOGIN = 0x30
OP_REGISTER_PLAYER = 0x31
OP_CREATE_LOBBY = 0x32
OP_JOIN_LOBBY = 0x33
OP_START_GAME = 0x34
OP_POLL_EVENTS = 0x35
OP_ROUTE_REGISTER = 0x36
OP_TITAN_MESSAGE = 0x70


class ConnState(str, Enum):
    CONNECTED = "CONNECTED"
    AUTHED = "AUTHED"
    PLAYER_READY = "PLAYER_READY"


@dataclass
class ConnectionContext:
    token: str | None = None
    player_id: str | None = None
    state: ConnState = ConnState.CONNECTED
    registered_lobbies: set[str] = field(default_factory=set)


def _to_wire_map(payload: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in payload.items():
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            out[k] = json.dumps(v)
        else:
            out[k] = str(v)
    return out


def _from_wire_map(payload: Dict[str, str]) -> Dict[str, object]:
    out: Dict[str, object] = {}
    numeric_keys = {"after_seq", "max_players", "port"}
    for k, v in payload.items():
        vv = v.strip()
        if vv in ("true", "false"):
            out[k] = vv == "true"
        elif k in numeric_keys and vv.isdigit():
            out[k] = int(vv)
        elif (vv.startswith("{") and vv.endswith("}")) or (vv.startswith("[") and vv.endswith("]")):
            try:
                out[k] = json.loads(vv)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def encode_frame(opcode: int, payload: Dict[str, object]) -> bytes:
    wm = _to_wire_map(payload)
    fields = []
    for k, v in wm.items():
        kb = k.encode("utf-8")
        vb = v.encode("utf-8")
        if len(kb) > 255:
            raise ValueError("key_too_long")
        fields.append(struct.pack(">B", len(kb)) + kb + struct.pack(">H", len(vb)) + vb)
    body = bytes([opcode]) + struct.pack(">H", len(fields)) + b"".join(fields)
    return struct.pack(">I", len(body)) + body


def decode_frame(data: bytes) -> Tuple[int, Dict[str, object]]:
    if len(data) < 3:
        raise ValueError("short_frame")
    opcode = data[0]
    nfields = struct.unpack(">H", data[1:3])[0]
    i = 3
    raw: Dict[str, str] = {}
    for _ in range(nfields):
        if i >= len(data):
            raise ValueError("truncated_keylen")
        klen = data[i]
        i += 1
        if i + klen > len(data):
            raise ValueError("truncated_key")
        key = data[i : i + klen].decode("utf-8")
        i += klen
        if i + 2 > len(data):
            raise ValueError("truncated_vallen")
        vlen = struct.unpack(">H", data[i : i + 2])[0]
        i += 2
        if i + vlen > len(data):
            raise ValueError("truncated_value")
        val = data[i : i + vlen].decode("utf-8")
        i += vlen
        raw[key] = val
    return opcode, _from_wire_map(raw)


def opcode_to_action(opcode: int, payload: Dict[str, object], ctx: ConnectionContext) -> Dict[str, object]:
    if opcode == OP_PING:
        return {"action": "PING"}
    if opcode == OP_DIR_GET:
        return {"action": "TITAN_DIR_GET", "path": str(payload.get("path", "/TitanServers"))}
    if opcode == OP_AUTH_LOGIN:
        return {"action": "AUTH_LOGIN", "username": str(payload.get("username", "guest")), "password": str(payload.get("password", ""))}
    if opcode == OP_REGISTER_PLAYER:
        if ctx.state == ConnState.CONNECTED:
            return {"action": "INVALID", "error": "auth_required"}
        return {"action": "REGISTER_PLAYER", "player_id": str(payload["player_id"]), "nickname": str(payload.get("nickname", payload["player_id"]))}
    if opcode == OP_CREATE_LOBBY:
        if ctx.state != ConnState.PLAYER_READY or not ctx.token:
            return {"action": "INVALID", "error": "player_not_ready"}
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
        if ctx.state != ConnState.PLAYER_READY:
            return {"action": "INVALID", "error": "player_not_ready"}
        return {"action": "JOIN_LOBBY", "lobby_id": str(payload["lobby_id"]), "player_id": str(payload.get("player_id", ctx.player_id or "")), "password": str(payload.get("password", ""))}
    if opcode == OP_ROUTE_REGISTER:
        if ctx.state != ConnState.PLAYER_READY:
            return {"action": "INVALID", "error": "player_not_ready"}
        return {"action": "TITAN_ROUTE_REGISTER", "lobby_id": str(payload["lobby_id"]), "player_id": str(payload.get("player_id", ctx.player_id or ""))}
    if opcode == OP_ROUTE_CHAT:
        lid = str(payload["lobby_id"])
        if lid not in ctx.registered_lobbies:
            return {"action": "INVALID", "error": "route_not_registered"}
        return {"action": "TITAN_ROUTE_CHAT", "lobby_id": lid, "from_player": str(payload.get("from_player", ctx.player_id or "unknown")), "message": str(payload["message"])}
    if opcode == OP_START_GAME:
        if ctx.state != ConnState.PLAYER_READY:
            return {"action": "INVALID", "error": "player_not_ready"}
        return {"action": "TITAN_START_GAME", "lobby_id": str(payload["lobby_id"]), "requester_id": str(payload.get("requester_id", ctx.player_id or "")), "port": payload.get("port")}
    if opcode == OP_POLL_EVENTS:
        if ctx.state == ConnState.CONNECTED:
            return {"action": "INVALID", "error": "auth_required"}
        return {"action": "ROUTE_POLL", "player_id": str(payload.get("player_id", ctx.player_id or "")), "after_seq": int(payload.get("after_seq", 0))}
    if opcode == OP_TITAN_MESSAGE:
        return {"action": "TITAN_MESSAGE", "packet_hex": str(payload.get("packet_hex", ""))}
    return {"action": "UNKNOWN_BINARY_OPCODE", "opcode": opcode}


def action_to_response_opcode(opcode: int) -> int:
    return opcode


async def call_backend(host: str, port: int, payload: Dict[str, object]) -> Dict[str, object]:
    r, w = await asyncio.open_connection(host, port)
    w.write((json.dumps(payload) + "\n").encode("utf-8"))
    await w.drain()
    line = await r.readline()
    w.close()
    await w.wait_closed()
    return json.loads(line.decode("utf-8")) if line else {"ok": False, "error": "backend_no_response"}


class BinaryGatewayServer:
    def __init__(self, backend_host: str, backend_port: int):
        self.backend_host = backend_host
        self.backend_port = backend_port

    async def _handle_titan_packet(self, packet_hex: str) -> Dict[str, object]:
        try:
            packet = binascii.unhexlify(packet_hex.encode("ascii"))
        except Exception:
            return {"ok": False, "error": "invalid_packet_hex"}

        req = decode_request(packet)
        kind = req.get("kind")
        if kind == "auth_login":
            backend = await call_backend(self.backend_host, self.backend_port, {"action": "AUTH_LOGIN", "username": req["username"], "password": req["password"]})
            if backend.get("ok"):
                reply = AuthLoginReply(STATUS_OK, str(backend.get("token", ""))).encode()
            else:
                reply = AuthLoginReply(STATUS_FAIL, str(backend.get("error", "auth_failed"))).encode()
            return {"ok": True, "packet_hex": binascii.hexlify(reply).decode("ascii")}

        if kind == "dir_get":
            backend = await call_backend(self.backend_host, self.backend_port, {"action": "TITAN_DIR_GET", "path": req["path"]})
            if backend.get("ok"):
                reply = DirGetReply(STATUS_OK, json.dumps(backend.get("entities", {}))).encode()
            else:
                reply = DirGetReply(STATUS_FAIL, json.dumps({"error": backend.get("error", "dir_failed")})).encode()
            return {"ok": True, "packet_hex": binascii.hexlify(reply).decode("ascii")}

        if kind == "route_register":
            backend = await call_backend(self.backend_host, self.backend_port, {"action": "TITAN_ROUTE_REGISTER", "lobby_id": req["lobby_id"], "player_id": req["player_id"]})
            if backend.get("ok"):
                reply = RoutingStatusReply(STATUS_OK, "registered").encode()
            else:
                reply = RoutingStatusReply(STATUS_FAIL, str(backend.get("error", "route_register_failed"))).encode()
            return {"ok": True, "packet_hex": binascii.hexlify(reply).decode("ascii")}

        reply = RoutingStatusReply(STATUS_FAIL, "unknown_message").encode()
        return {"ok": True, "packet_hex": binascii.hexlify(reply).decode("ascii")}

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
                        if action.get("action") == "TITAN_MESSAGE":
                            response = await self._handle_titan_packet(str(action.get("packet_hex", "")))
                        else:
                            response = await call_backend(self.backend_host, self.backend_port, action)
                    except Exception as exc:
                        response = {"ok": False, "error": str(exc)}

                if opcode == OP_AUTH_LOGIN and response.get("ok") and isinstance(response.get("token"), str):
                    ctx.token = str(response["token"])
                    ctx.state = ConnState.AUTHED
                if opcode == OP_REGISTER_PLAYER and response.get("ok"):
                    p = response.get("player", {})
                    if isinstance(p, dict) and isinstance(p.get("player_id"), str):
                        ctx.player_id = str(p["player_id"])
                        ctx.state = ConnState.PLAYER_READY
                if opcode == OP_ROUTE_REGISTER and response.get("ok"):
                    lid = str(action.get("lobby_id", ""))
                    if lid:
                        ctx.registered_lobbies.add(lid)

                writer.write(encode_frame(action_to_response_opcode(opcode), response))
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
    addrs = ", ".join(str(s.getsockname()) for s in (server.sockets or []))
    print(f"Titan binary gateway listening on {addrs} -> {args.backend_host}:{args.backend_port}")
    async with server:
        await server.serve_forever()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Binary Titan gateway with connection state machine")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9200)
    p.add_argument("--backend-host", default="127.0.0.1")
    p.add_argument("--backend-port", type=int, default=9000)
    return p


if __name__ == "__main__":
    asyncio.run(main_async(build_parser().parse_args()))
