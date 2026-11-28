"""Read-only configured Ollama availability; never prints endpoint or credentials."""
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.validation.local_ollama_benchmark import discover


async def main():
    candidate = discover(profiles=True).get("gemma4:31b")
    report = {"configured": bool(candidate), "model_requests": 0}
    if candidate:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(candidate[0] + "/api/tags",
                                       timeout=aiohttp.ClientTimeout(total=10)) as response:
                    value = await response.json()
                    report.update(http_status=response.status, models=[
                        row["name"] for row in value.get("models", [])
                        if row["name"] in {"gemma4:31b", "gpt-oss:20b"}])
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            report["error"] = type(error).__name__
            if isinstance(error, aiohttp.ClientConnectorError):
                report["os_error"] = type(error.os_error).__name__
                report["errno"] = error.os_error.errno
    output = Path("build/opencode-p0/ollama-availability.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


asyncio.run(main())
