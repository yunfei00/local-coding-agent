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
            store.close()

            reopened_store = SQLiteStore(data_root)
            reopened_manager = MCPSettingsManager(reopened_store)
            restored = reopened_manager.get(item.id)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.name, "filesystem")
            self.assertEqual(restored.args, ("server.py",))
            self.assertTrue(restored.enabled)
            self.assertTrue(restored.trusted)

            with patch.dict(
                os.environ,
                {
                    "PUBLIC_VALUE": "from-environment",
                    "TOKEN": "super-secret",
                },
                clear=False,
            ):
                config = restored.to_client_config()
            self.assertEqual(config.env["MODE"], "safe")
            self.assertEqual(
                config.env["FROM_ENV"],
                "from-environment",
            )
            self.assertEqual(
                config.env["TOKEN"],
                "super-secret",
            )
            reopened_store.close()

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

    def test_rejects_plaintext_sensitive_config_values(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            manager = MCPSettingsManager(store)
            with self.assertRaisesRegex(
                ValueError,
                "cannot store a literal value",
            ):
                manager.upsert(
                    {
                        "name": "bad-secret",
                        "transport": "stdio",
                        "command": "python",
                        "env": {"API_KEY": "literal-secret"},
                    }
                )

            safe = manager.upsert(
                {
                    "name": "env-reference",
                    "transport": "stdio",
                    "command": "python",
                    "env": {"API_KEY": "${MCP_TEST_API_KEY}"},
                }
            )
            self.assertEqual(
                safe.env["API_KEY"],
                "${MCP_TEST_API_KEY}",
            )
            store.close()

    def test_rejects_http_credentials_in_url(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            manager = MCPSettingsManager(store)

            with self.assertRaisesRegex(ValueError, "username/password"):
                manager.upsert(
                    {
                        "name": "userinfo",
                        "transport": "streamable_http",
                        "url": "https://user:pass@example.test/mcp",
                    }
                )
            with self.assertRaisesRegex(
                ValueError,
                "credential query parameters",
            ):
                manager.upsert(
                    {
                        "name": "query-token",
                        "transport": "streamable_http",
                        "url": "https://example.test/mcp?api_key=secret",
                    }
                )
            store.close()

    def test_rejects_duplicate_server_name_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as data_root:
            store = SQLiteStore(data_root)
            manager = MCPSettingsManager(store)
            manager.upsert(
                {
                    "name": "Docs",
                    "transport": "stdio",
                    "command": "python",
                }
            )
            with self.assertRaisesRegex(ValueError, "already exists"):
                manager.upsert(
                    {
                        "name": "docs",
                        "transport": "stdio",
                        "command": "python",
                    }
                )
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
