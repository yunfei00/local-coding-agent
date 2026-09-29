import json
import os
import unittest
from unittest.mock import patch

from aiohttp import web

from agent.llm.factory import create_provider_from_env, normalize_provider_name
from agent.llm.openai_compatible import OpenAICompatibleProvider


class OpenAICompatibleProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.seen_authorization = None

        async def models(request: web.Request) -> web.Response:
            self.seen_authorization = request.headers.get("Authorization")
            return web.json_response(
                {
                    "object": "list",
                    "data": [
                        {"id": "coder-model", "object": "model"},
                        {"id": "other-model", "object": "model"},
                    ],
                }
            )

        async def chat(request: web.Request) -> web.StreamResponse:
            self.assertEqual(
                request.headers.get("Authorization"),
                "Bearer test-key",
            )
            body = await request.json()
            self.assertEqual(body["model"], "coder-model")
            self.assertTrue(body["stream"])
            self.assertEqual(
                body["tools"][0]["function"]["name"],
                "read_file",
            )

            response = web.StreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream"},
            )
            await response.prepare(request)

            chunks = [
                {
                    "choices": [
                        {
                            "delta": {"content": "Hello "},
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": "{\"pa",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "arguments": "th\":\"README.md\"}",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 5,
                    },
                },
            ]
            for payload in chunks:
                await response.write(
                    ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")
                )
            await response.write(b"data: [DONE]\n\n")
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        sockets = self.site._server.sockets
        port = sockets[0].getsockname()[1]
        self.provider = OpenAICompatibleProvider(
            base_url=f"http://127.0.0.1:{port}/v1",
            api_key="test-key",
            preferred_model="coder-model",
            context_window=65536,
        )

    async def asyncTearDown(self) -> None:
        await self.runner.cleanup()

    async def test_status_auth_stream_and_tool_calls(self) -> None:
        status = await self.provider.get_status()
        self.assertTrue(status["online"])
        self.assertEqual(status["default_model"], "coder-model")
        self.assertEqual(status["context_window"], 65536)
        self.assertNotIn("api_key", status)
        self.assertEqual(self.seen_authorization, "Bearer test-key")

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]
        chunks = []
        async for chunk in self.provider.stream_chat(
            model="coder-model",
            messages=[{"role": "user", "content": "Inspect README"}],
            tools=tools,
        ):
            chunks.append(chunk)

        self.assertEqual(
            "".join(chunk.content for chunk in chunks),
            "Hello ",
        )
        final = chunks[-1]
        self.assertTrue(final.done)
        self.assertEqual(final.finish_reason, "tool_calls")
        self.assertEqual(final.prompt_eval_count, 12)
        self.assertEqual(final.eval_count, 5)
        self.assertEqual(len(final.tool_calls), 1)
        self.assertEqual(final.tool_calls[0].id, "call_1")
        self.assertEqual(final.tool_calls[0].name, "read_file")
        self.assertEqual(
            final.tool_calls[0].arguments,
            {"path": "README.md"},
        )


class ProviderFactoryTests(unittest.TestCase):
    def test_normalize_provider_aliases(self) -> None:
        self.assertEqual(normalize_provider_name(None), "ollama")
        self.assertEqual(normalize_provider_name("openai"), "openai_compatible")
        self.assertEqual(
            normalize_provider_name("openai-compatible"),
            "openai_compatible",
        )

    def test_factory_selects_openai_compatible(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LCA_PROVIDER": "openai_compatible",
                "LCA_OPENAI_BASE_URL": "http://127.0.0.1:9999/v1",
                "LCA_OPENAI_MODEL": "coder-model",
                "LCA_OPENAI_API_KEY": "secret",
            },
            clear=False,
        ):
            provider = create_provider_from_env()

        self.assertIsInstance(provider, OpenAICompatibleProvider)
        self.assertEqual(provider.preferred_model, "coder-model")


if __name__ == "__main__":
    unittest.main()
