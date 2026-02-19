#!/usr/bin/env python3
"""Packet sniffing framework for WON/Titan compatibility testing.

Provides:
- TCP MITM capture proxy (client <-> server)
- NDJSON capture logs with direction/timestamp/hex bytes
- Optional Titan-message decode attempts for each frame
- Capture summarizer for quick protocol analysis
"""

from __future__ import annotations

import argparse
import asyncio
import binascii
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

from tools.won_oss_server.titan_messages import decode_titan_message


@dataclass
class PacketRecord:
    ts: float
    direction: str
    nbytes: int
    payload_hex: str
    titan: Optional[Dict[str, Any]] = None


class CaptureWriter:
    def __init__(self, out_path: Path):
        self.out_path = out_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.out_path.open("a", encoding="utf-8")

    def write(self, rec: PacketRecord) -> None:
        self._fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def try_decode_titan(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        msg_type, status, payload = decode_titan_message(raw)
        return {
            "msg_type": msg_type,
            "status": status,
            "payload_len": len(payload),
            "payload_hex": binascii.hexlify(payload).decode("ascii"),
        }
    except Exception:
        return None


class SniffProxy:
    def __init__(self, listen_host: str, listen_port: int, target_host: str, target_port: int, writer: CaptureWriter, decode_titan_frames: bool):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.writer = writer
        self.decode_titan_frames = decode_titan_frames

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, direction: str) -> None:
        while True:
            chunk = await reader.read(8192)
            if not chunk:
                break
            titan = try_decode_titan(chunk) if self.decode_titan_frames else None
            self.writer.write(
                PacketRecord(
                    ts=time.time(),
                    direction=direction,
                    nbytes=len(chunk),
                    payload_hex=binascii.hexlify(chunk).decode("ascii"),
                    titan=titan,
                )
            )
            writer.write(chunk)
            await writer.drain()

    async def handle_client(self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        server_r, server_w = await asyncio.open_connection(self.target_host, self.target_port)
        try:
            await asyncio.gather(
                self._pipe(client_r, server_w, "client_to_server"),
                self._pipe(server_r, client_w, "server_to_client"),
            )
        finally:
            client_w.close()
            server_w.close()
            await client_w.wait_closed()
            await server_w.wait_closed()

    async def run(self) -> None:
        srv = await asyncio.start_server(self.handle_client, self.listen_host, self.listen_port)
        async with srv:
            await srv.serve_forever()


def summarize_capture(path: Path) -> Dict[str, Any]:
    totals = {"frames": 0, "bytes": 0, "client_to_server": 0, "server_to_client": 0, "titan_decoded": 0}
    by_msg: Dict[str, int] = {}

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            totals["frames"] += 1
            totals["bytes"] += int(rec.get("nbytes", 0))
            totals[rec.get("direction", "client_to_server")] = totals.get(rec.get("direction", "client_to_server"), 0) + 1
            titan = rec.get("titan")
            if titan:
                totals["titan_decoded"] += 1
                key = str(titan.get("msg_type"))
                by_msg[key] = by_msg.get(key, 0) + 1

    return {"totals": totals, "by_msg_type": by_msg}


def maybe_start_tcpdump(interface: str, bpf_filter: str, pcap_path: Path) -> Optional[subprocess.Popen]:
    if shutil.which("tcpdump") is None:
        return None
    pcap_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["tcpdump", "-i", interface, "-w", str(pcap_path), bpf_filter]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Packet sniffing framework for WON/Titan testing")
    sub = p.add_subparsers(dest="cmd", required=True)

    px = sub.add_parser("proxy", help="Run MITM TCP capture proxy")
    px.add_argument("--listen-host", default="0.0.0.0")
    px.add_argument("--listen-port", type=int, required=True)
    px.add_argument("--target-host", required=True)
    px.add_argument("--target-port", type=int, required=True)
    px.add_argument("--out", required=True, help="NDJSON capture file path")
    px.add_argument("--decode-titan", action="store_true", help="Attempt decode_titan_message on each chunk")
    px.add_argument("--tcpdump-interface", default="", help="Optional interface for raw pcap capture")
    px.add_argument("--tcpdump-filter", default="tcp", help="Optional tcpdump BPF filter")
    px.add_argument("--pcap-out", default="", help="Optional pcap file output path")

    sm = sub.add_parser("summary", help="Summarize NDJSON capture")
    sm.add_argument("--in", dest="in_path", required=True)

    return p


async def run_proxy(args: argparse.Namespace) -> None:
    writer = CaptureWriter(Path(args.out))
    tcpdump_proc: Optional[subprocess.Popen] = None
    try:
        if args.tcpdump_interface and args.pcap_out:
            tcpdump_proc = maybe_start_tcpdump(args.tcpdump_interface, args.tcpdump_filter, Path(args.pcap_out))
        proxy = SniffProxy(args.listen_host, args.listen_port, args.target_host, args.target_port, writer, args.decode_titan)
        await proxy.run()
    finally:
        writer.close()
        if tcpdump_proc is not None:
            tcpdump_proc.terminate()


def main() -> None:
    p = build_parser()
    args = p.parse_args()
    if args.cmd == "summary":
        print(json.dumps(summarize_capture(Path(args.in_path)), indent=2))
        return
    asyncio.run(run_proxy(args))


if __name__ == "__main__":
    main()
