#!/usr/bin/env python3
"""Minimal binary Titan gateway.

Wire format (MVP):
- 4-byte big-endian length (N)
- N-byte frame payload:
  - 1-byte opcode
  - UTF-8 JSON payload bytes

This is not full historical Titan framing, but provides a binary transport bridge
for incremental compatibility work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
from typing import Dict, Tuple

# Minimal opcode map for next-step binary path
OP_PING = 0x01
OP_DIR_GET = 0x10
OP_ROUTE_CHAT = 0x20
OP_AUTH_LOGIN = 0x30


def encode_frame(opcode: int, payload: Dict[str, object]) -> bytes:
    body = bytes([opcode]) + json.dumps(payload).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def decode_frame(data: bytes) -> Tuple[int, Dict[str, object]]:
    if not data:
        raise ValueError("empty_frame")
    opcode = data[0]
    payload = json.loads(data[1:].decode("utf-8")) if len(data) > 1 else {}
    return opcode, payload


def opcode_to_action(opcode: int, payload: Dict[str, object]) -> Dict[str, object]:
    if opcode == OP_PING:
        return {"action": "PING"}
    if opcode == OP_DIR_GET:
        return {"action": "TITAN_DIR_GET", "path": str(payload.get("path", "/TitanServers"))}
    if opcode == OP_ROUTE_CHAT:
        return {
            "action": "TITAN_ROUTE_CHAT",
            "lobby_id": str(payload["lobby_id"]),
            "from_player": str(payload["from_player"]),
            "message": str(payload["message"]),
        }
    if opcode == OP_AUTH_LOGIN:
        return {
            "action": "AUTH_LOGIN",
            "username": str(payload.get("username", "guest")),
            "password": str(payload.get("password", "")),
        }
    return {"action": "UNKNOWN_BINARY_OPCODE", "opcode": opcode}


def action_to_response_opcode(opcode: int) -> int:
    # keep 1:1 response opcode for now
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
        try:
            while True:
                hdr = await reader.readexactly(4)
                length = struct.unpack(">I", hdr)[0]
                if length <= 0 or length > 10_000_000:
                    raise ValueError("invalid_frame_length")
                body = await reader.readexactly(length)
                opcode, payload = decode_frame(body)
                action = opcode_to_action(opcode, payload)
                if action.get("action") == "UNKNOWN_BINARY_OPCODE":
                    response = {"ok": False, "error": "unknown_binary_opcode", "opcode": opcode}
                else:
                    try:
                        response = await call_backend(self.backend_host, self.backend_port, action)
                    except Exception as exc:
                        response = {"ok": False, "error": str(exc)}
                wire = encode_frame(action_to_response_opcode(opcode), response)
                writer.write(wire)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:
            err = encode_frame(0xFF, {"ok": False, "error": str(exc)})
            writer.write(err)
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
