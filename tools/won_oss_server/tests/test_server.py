import contextlib
import asyncio
import json
import struct
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.won_oss_server.won_server import (
    OBJ_FACT_CUR_SERVER_COUNT,
    OBJ_ROOM_CLIENTCOUNT,
    OBJ_ROOM_FLAGS,
    StateStore,
    WONLikeState,
    run_server,
)
from tools.won_oss_server.titan_bridge import parse_legacy_command
from tools.won_oss_server.titan_binary_gateway import (
    OP_AUTH_LOGIN,
    OP_DIR_GET,
    OP_PING,
    decode_frame,
    encode_frame,
    opcode_to_action,
    BinaryGatewayServer,
)


class WONServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "won_test.db")
        self.server, _, self.store = await run_server("127.0.0.1", 0, timeout_s=60, db_path=self.db_path)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        with contextlib.suppress(Exception):
            self.server.close()
            await self.server.wait_closed()
        with contextlib.suppress(Exception):
            self.store.close()
        self.tmp.cleanup()

    async def _request(self, payload):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write((json.dumps(payload) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        writer.close()
        await writer.wait_closed()
        return json.loads(line.decode())

    async def _auth(self, username="u1", password="pw1"):
        r = await self._request({"action": "AUTH_LOGIN", "username": username, "password": password})
        self.assertTrue(r["ok"])
        return r["token"]

    async def test_typed_room_objects_and_titan_dir_get(self):
        tok = await self._auth()
        await self._request({"action": "REGISTER_PLAYER", "player_id": "p1", "nickname": "One"})
        created = await self._request(
            {
                "action": "CREATE_LOBBY",
                "token": tok,
                "owner_id": "p1",
                "name": "Lobby1",
                "map_name": "Garden",
                "max_players": 4,
                "region": "na",
                "metadata": {"room_flags": 3},
            }
        )
        lobby_id = created["lobby"]["lobby_id"]
        d = await self._request({"action": "TITAN_DIR_GET", "path": "/Homeworld"})
        self.assertTrue(d["ok"])
        payload = d["entities"][lobby_id]["payload"]
        self.assertEqual(payload[OBJ_ROOM_FLAGS], 3)
        self.assertEqual(payload[OBJ_ROOM_CLIENTCOUNT], 1)

    async def test_sessions_and_events_persist(self):
        tok = await self._auth("persist_user", "persist_pw")
        await self._request({"action": "REGISTER_PLAYER", "player_id": "p1", "nickname": "One"})
        await self._request({"action": "REGISTER_PLAYER", "player_id": "p2", "nickname": "Two"})
        created = await self._request({"action": "CREATE_LOBBY", "token": tok, "owner_id": "p1", "name": "L", "map_name": "M", "max_players": 4, "region": "na"})
        lobby_id = created["lobby"]["lobby_id"]
        await self._request({"action": "JOIN_LOBBY", "lobby_id": lobby_id, "player_id": "p2"})
        await self._request({"action": "ROUTE_SEND_CHAT", "lobby_id": lobby_id, "from_player": "p1", "message": "hello"})

        self.server.close()
        await self.server.wait_closed()
        self.store.close()

        store2 = StateStore(self.db_path)
        state2 = WONLikeState(store=store2, heartbeat_timeout_s=60)
        self.assertIn(tok, state2.sessions)
        self.assertTrue(any(e["type"] == "chat" for e in state2.events_by_player.get("p2", [])))
        store2.close()

    async def test_factory_managed_process_and_factory_objects(self):
        await self._request({"action": "REGISTER_FACTORY", "factory_id": "f1", "host": "127.0.0.1", "region": "eu", "max_processes": 1})
        r = await self._request({"action": "FACTORY_START_PROCESS", "factory_id": "f1", "process_name": "RoutingServHWGame", "game_name": "homeworld", "port": 2201})
        self.assertTrue(r["ok"])
        d = await self._request({"action": "DIR_LIST", "path": "/TitanServers"})
        self.assertGreaterEqual(d["entities"]["Factory:f1"]["payload"][OBJ_FACT_CUR_SERVER_COUNT], 1)
        h = await self._request({"action": "HEALTH"})
        self.assertGreaterEqual(h["managed_processes"], 1)


class BridgeParserTests(unittest.TestCase):
    def test_parse_commands(self):
        self.assertEqual(parse_legacy_command("PING")["action"], "PING")
        self.assertEqual(parse_legacy_command("LOGIN u p")["action"], "AUTH_LOGIN")
        self.assertEqual(parse_legacy_command("TITAN DIR GET /TitanServers")["action"], "TITAN_DIR_GET")
        self.assertEqual(parse_legacy_command("TITAN ROUTE CHAT lob_1 p1 hi there")["action"], "TITAN_ROUTE_CHAT")
        self.assertEqual(parse_legacy_command("REGISTER_FACTORY f1 127.0.0.1 na 2")["action"], "REGISTER_FACTORY")


class BinaryGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "won_test.db")
        self.backend, _, self.store = await run_server("127.0.0.1", 0, timeout_s=60, db_path=self.db_path)
        self.backend_port = self.backend.sockets[0].getsockname()[1]

        gateway = BinaryGatewayServer("127.0.0.1", self.backend_port)
        self.gateway_srv = await asyncio.start_server(gateway.handle_client, "127.0.0.1", 0)
        self.gateway_port = self.gateway_srv.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.gateway_srv.close()
        await self.gateway_srv.wait_closed()
        self.backend.close()
        await self.backend.wait_closed()
        self.store.close()
        self.tmp.cleanup()

    async def _binary_roundtrip(self, opcode: int, payload: dict):
        r, w = await asyncio.open_connection("127.0.0.1", self.gateway_port)
        w.write(encode_frame(opcode, payload))
        await w.drain()
        hdr = await r.readexactly(4)
        ln = struct.unpack(">I", hdr)[0]
        body = await r.readexactly(ln)
        w.close()
        await w.wait_closed()
        return decode_frame(body)

    async def test_ping_and_dir_get(self):
        op, payload = await self._binary_roundtrip(OP_PING, {})
        self.assertEqual(op, OP_PING)
        self.assertTrue(payload["ok"])

        op, payload = await self._binary_roundtrip(OP_DIR_GET, {"path": "/TitanServers"})
        self.assertEqual(op, OP_DIR_GET)
        self.assertTrue(payload["ok"])
        self.assertIn("AuthServer", payload["entities"])

    async def test_auth_login_opcode(self):
        op, payload = await self._binary_roundtrip(OP_AUTH_LOGIN, {"username": "buser", "password": "pw"})
        self.assertEqual(op, OP_AUTH_LOGIN)
        self.assertTrue(payload["ok"])
        self.assertIn("token", payload)

    def test_opcode_mapping(self):
        self.assertEqual(opcode_to_action(OP_PING, {})["action"], "PING")
        self.assertEqual(opcode_to_action(OP_DIR_GET, {"path": "/Homeworld"})["action"], "TITAN_DIR_GET")


if __name__ == "__main__":
    unittest.main()
