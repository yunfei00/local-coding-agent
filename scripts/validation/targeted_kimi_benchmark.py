"""One approved synthetic benchmark via the same production Agent as Gemma."""
import argparse
import asyncio
import json
import sqlite3
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

import aiohttp

from scripts.validation.local_ollama_benchmark import attempt
from scripts.validation.realworld_benchmark import collect, save_json
from scripts.validation.realworld_extended import CASES


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("04", "30"), required=True)
    args = parser.parse_args()
    key = os.environ.pop("LCA_TARGETED_KIMI_SECRET", "")
    url = os.environ.pop("LCA_TARGETED_KIMI_ENDPOINT", "")
    parsed = urlsplit(url)
    if (not key or parsed.scheme != "https" or not (parsed.hostname or "").endswith(".aliyuncs.com")
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise SystemExit("Configured, authorized Kimi connection required.")
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix="lca-kimi-targeted-")) / args.case
    options = {"context_window":32768, "max_output_tokens":1024, "model_steps":100,
               "request_seconds":180, "case_seconds":480,
               "api_budget":{"api_calls":12,"global_api_calls":12,"api_tokens":100000,"global_api_tokens":100000,
                             "api_cost":10,"global_api_cost":10}}
    profile = {"model_id":"kimi-k3","display_name":"kimi-k3","context_window":32768,
               "max_output_tokens":1024,"pricing":{"input_price":20,"output_price":100}}
    async with aiohttp.ClientSession() as session:
        row = await attempt(session, Path(sys.executable), url, "kimi-k3", args.case, root, 1,
                            True, profile=profile, options=options, scenario=CASES[args.case], api_key=key)
    row.update(collect(root))
    usage = row.get("tokens")
    row["retail_estimate_cny"] = round((20 * usage["input"] + 100 * usage["output"])/1_000_000, 4) if usage else None
    row["cost_basis"] = "public reference tariff, account invoice unavailable"
    save_json(args.output / "results.json", {"results":[row]})
    print(args.case, row["status"], row.get("failure") or "")


def discover_connection():
    """Called through a private pipe by the Windows vault launcher."""
    file = Path(os.environ["APPDATA"]) / "local-coding-agent-desktop" / "local-coding-agent.sqlite3"
    with sqlite3.connect(file.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key='models.catalog.v1'").fetchone()
    catalog = json.loads(row[0])
    ids = {profile["connection_id"] for profile in catalog["profiles"] if profile["model_id"] == "kimi-k3"}
    eligible = [item for item in catalog["connections"] if item["connection_id"] in ids
                and item["enabled"] and item["provider_type"] == "openai_compatible"
                and item.get("credential_reference")]
    if len(eligible) != 1:
        raise SystemExit("Exactly one saved, enabled Kimi connection is required.")
    print(json.dumps({"reference":eligible[0]["credential_reference"],"url":eligible[0]["base_url"]}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--discover"]:
        discover_connection()
    else:
        asyncio.run(main())
