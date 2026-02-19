import json
import tempfile
import unittest
from pathlib import Path

from tools.won_oss_server.packet_sniffer_framework import summarize_capture, try_decode_titan
from tools.won_oss_server.titan_messages import AuthLoginReq, MSG_AUTH_LOGIN_REQ


class PacketSnifferFrameworkTests(unittest.TestCase):
    def test_try_decode_titan_valid_packet(self):
        packet = AuthLoginReq("alice", "pw").encode()
        decoded = try_decode_titan(packet)
        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertEqual(decoded["msg_type"], MSG_AUTH_LOGIN_REQ)
        self.assertEqual(decoded["status"], 0)
        self.assertGreater(decoded["payload_len"], 0)

    def test_summarize_capture(self):
        with tempfile.TemporaryDirectory() as td:
            cap = Path(td) / "capture.ndjson"
            rows = [
                {
                    "ts": 1.0,
                    "direction": "client_to_server",
                    "nbytes": 10,
                    "payload_hex": "00",
                    "titan": {"msg_type": MSG_AUTH_LOGIN_REQ},
                },
                {
                    "ts": 2.0,
                    "direction": "server_to_client",
                    "nbytes": 20,
                    "payload_hex": "ff",
                    "titan": None,
                },
            ]
            cap.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

            summary = summarize_capture(cap)

            self.assertEqual(summary["totals"]["frames"], 2)
            self.assertEqual(summary["totals"]["bytes"], 30)
            self.assertEqual(summary["totals"]["client_to_server"], 1)
            self.assertEqual(summary["totals"]["server_to_client"], 1)
            self.assertEqual(summary["totals"]["titan_decoded"], 1)
            self.assertEqual(summary["by_msg_type"][str(MSG_AUTH_LOGIN_REQ)], 1)


if __name__ == "__main__":
    unittest.main()
