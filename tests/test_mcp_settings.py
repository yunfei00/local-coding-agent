from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from agent.mcp.settings import MCPSettingsManager
from agent.persistence.store import SQLiteStore


class MCPSettingsTests(unittest.TestCase):
    def test_persists_non_secret_server_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            manager = MCPSettingsManager(store)
            item = manager.upsert(
                {
                    "name": "filesystem",
                    "transport": "stdio",
                    "command": "python",
                    "args": ["server.py"],
                    "env": {
                        "MODE": "safe",
                        "FROM_ENV": "${PUBLIC_VALUE}",
                    },
                    "secret_env_keys": ["TOKEN"],
                    "enabled": True,
                    "trusted": True,
                    "timeout_seconds": 12,
                }
            )
            store.connection.commit()

            rows = store.list_mcp_servers()
            serialized = json.dumps(rows, ensure_ascii=False)
            self.assertEqual(len(rows), 1)
            self.assertNotIn("super-secret", serialized)
            self.assertIn("TOKEN", serialized)
            self.assertEqual(item.name, "filesystem")
            self.assertTrue(item.trusted)

            with patch.dict(
                os.environ,
                {
                    "PUBLIC_VALUE": "from-environment",
                    "TOKEN": "super-secret",
                },
                clear=False,
            ):
                config = item.to_client_config()
            self.assertEqual(config.env["MODE"], "safe")
            self.assertEqual(
                config.env["FROM_ENV"],
                "from-environment",
            )
            self.assertEqual(
                config.env["TOKEN"],
                "super-secret",
            )
            store.close()

    def test_runtime_secret_overrides_environment_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            manager = MCPSettingsManager(store)
            item = manager.upsert(
                {
                    "name": "remote",
                    "transport": "streamable_http",
                    "url": "https://example.test/mcp",
                    "secret_env_keys": ["TOKEN"],
                }
            )
            config = item.to_client_config(
                secret_env={"TOKEN": "session-secret"}
            )
            self.assertEqual(
                config.env["TOKEN"],
                "session-secret",
            )
            serialized = json.dumps(
                store.list_mcp_servers(),
                ensure_ascii=False,
            )
            self.assertNotIn("session-secret", serialized)
            store.close()

    def test_rejects_same_key_as_secret_and_non_secret(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            manager = MCPSettingsManager(store)
            with self.assertRaises(ValueError):
                manager.upsert(
                    {
                        "name": "bad",
                        "transport": "stdio",
                        "command": "python",
                        "env": {"TOKEN": "plain"},
                        "secret_env_keys": ["TOKEN"],
                    }
                )
            store.close()


if __name__ == "__main__":
    unittest.main()
