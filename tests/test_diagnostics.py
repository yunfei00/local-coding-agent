from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.core.diagnostics import redact_text, redact_url
from agent.server.main import AgentServer


class FakeProvider:
    provider_name = "openai_compatible"
    preferred_model = "coder-model"
    context_window = 65536

    async def get_status(self) -> dict:
        return {
            "provider": self.provider_name,
            "online": True,
            "base_url": "https://user:pass@example.test/v1?api_key=query-secret",
            "models": [{"name": "coder-model"}],
            "default_model": "coder-model",
            "preferred_model": "coder-model",
            "context_window": self.context_window,
            "error": None,
        }


class DiagnosticsRedactionTests(unittest.TestCase):
    def test_redacts_embedded_home_and_common_secrets(self) -> None:
        home = str(Path.home())
        text = redact_text(
            f"Bearer abc123 path={home}/project api_key=secret-value",
            exact_secrets=("secret-value",),
        )
        self.assertNotIn("abc123", text)
        self.assertNotIn("secret-value", text)
        self.assertNotIn(home, text)
        self.assertIn("<HOME>", text)
        self.assertIn("<REDACTED>", text)

    def test_redacted_url_removes_credentials_query_and_fragment(self) -> None:
        value = redact_url(
            "https://user:pass@example.test:9443/v1?api_key=secret#frag"
        )
        self.assertEqual(value, "https://example.test:9443/v1")


class DiagnosticsPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_payload_excludes_chat_prompt_rules_and_api_key(self) -> None:
        with (
            tempfile.TemporaryDirectory() as data_root,
            tempfile.TemporaryDirectory() as project_root,
            patch.dict(os.environ, {"LCA_DATA_DIR": data_root}, clear=False),
        ):
            Path(project_root, "pyproject.toml").write_text(
                "[project]\nname='diag-demo'\n",
                encoding="utf-8",
            )
            server = AgentServer("token")
            server.provider = FakeProvider()
            server.openai_api_key = "secret-value"
            project, thread, _ = server.projects.open(
                project_root,
                active_model="coder-model",
            )
            project.state.append_exchange(
                thread.id,
                user="CHAT-SHOULD-NOT-LEAK",
                assistant="ASSISTANT-SHOULD-NOT-LEAK",
            )
            server.prompt_rules.set(
                "global",
                None,
                "PROMPT-RULE-SHOULD-NOT-LEAK",
                enabled=True,
            )
            server._record_diagnostic_error(
                "TEST_ERROR",
                f"Bearer secret-value at {Path.home()}/private",
                source="test",
            )
            server.last_context_usage = {
                "estimated_input_tokens": 1234,
                "input_budget_tokens": 60000,
            }

            try:
                payload = await server._diagnostics_payload()
            finally:
                server.close()

        serialized = str(payload)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("query-secret", serialized)
        self.assertNotIn("CHAT-SHOULD-NOT-LEAK", serialized)
        self.assertNotIn("ASSISTANT-SHOULD-NOT-LEAK", serialized)
        self.assertNotIn("PROMPT-RULE-SHOULD-NOT-LEAK", serialized)

        self.assertEqual(payload["provider"]["base_url"], "https://example.test/v1")
        self.assertEqual(payload["provider"]["model_count"], 1)
        self.assertEqual(payload["context"]["last_usage"]["estimated_input_tokens"], 1234)
        self.assertTrue(payload["prompt_rules"]["global"]["configured"])
        self.assertTrue(payload["prompt_rules"]["global"]["enabled"])
        self.assertGreaterEqual(payload["database"]["counts"]["messages"], 2)
        self.assertEqual(payload["database"]["quick_check"], "ok")
        self.assertIn("python", payload["workspace"]["detection"]["detected"])
        self.assertIn("<HOME>", payload["recent_errors"][0]["message"])
        self.assertTrue(payload["redaction"]["api_keys"])
        self.assertTrue(payload["redaction"]["chat_history"])


if __name__ == "__main__":
    unittest.main()
