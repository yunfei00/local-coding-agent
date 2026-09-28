import json
import unittest

from aiohttp import web

from agent.llm.base import ModelInfo
from agent.llm.ollama import (
    OllamaProvider,
    choose_default_model,
    parse_model_list,
)


class OllamaParsingTests(unittest.TestCase):
    def test_parse_models(self) -> None:
        models = parse_model_list(
            {
                "models": [
                    {
                        "name": "qwen3-coder:30b",
                        "size": 19_000_000_000,
                        "digest": "abc",
                        "details": {
                            "family": "qwen3moe",
                            "parameter_size": "30.5B",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            }
        )

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, "qwen3-coder:30b")
        self.assertEqual(models[0].family, "qwen3moe")

    def test_choose_default_prefers_exact_model(self) -> None:
        models = [
            ModelInfo(name="other:latest"),
            ModelInfo(name="qwen3-coder:30b"),
        ]
        self.assertEqual(
            choose_default_model(models, "qwen3-coder:30b"),
            "qwen3-coder:30b",
        )


class OllamaProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        async def tags(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "models": [
                        {
                            "name": "qwen3-coder:30b",
                            "size": 19_000_000_000,
                            "digest": "abc",
                            "details": {"family": "qwen3moe"},
                        }
                    ]
                }
            )

        async def chat(request: web.Request) -> web.StreamResponse:
            body = await request.json()
            self.assertEqual(body["model"], "qwen3-coder:30b")
            self.assertTrue(body["stream"])
            self.assertEqual(body["options"]["num_ctx"], 32768)

            response = web.StreamResponse(
                status=200,
                headers={"Content-Type": "application/x-ndjson"},
            )
            await response.prepare(request)
            for payload in [
                {
                    "message": {"role": "assistant", "content": "Hello "},
                    "done": False,
                },
                {
                    "message": {"role": "assistant", "content": "world"},
                    "done": False,
                },
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 11,
                    "eval_count": 7,
                },
            ]:
                await response.write((json.dumps(payload) + "\n").encode("utf-8"))
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/api/tags", tags)
        app.router.add_post("/api/chat", chat)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        sockets = self.site._server.sockets
        port = sockets[0].getsockname()[1]
        self.provider = OllamaProvider(
            base_url=f"http://127.0.0.1:{port}",
            preferred_model="qwen3-coder:30b",
            context_window=32768,
        )

    async def asyncTearDown(self) -> None:
        await self.runner.cleanup()

    async def test_status_and_stream_chat(self) -> None:
        status = await self.provider.get_status()
        self.assertTrue(status["online"])
        self.assertEqual(status["default_model"], "qwen3-coder:30b")

        chunks = []
        async for chunk in self.provider.stream_chat(
            model="qwen3-coder:30b",
            messages=[{"role": "user", "content": "Hi"}],
        ):
            chunks.append(chunk)

        self.assertEqual("".join(item.content for item in chunks), "Hello world")
        self.assertTrue(chunks[-1].done)
        self.assertEqual(chunks[-1].eval_count, 7)


if __name__ == "__main__":
    unittest.main()
