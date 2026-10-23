"""uv run python scripts/validation/model_diagnostics.py --help (offline by default)."""
import argparse
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.core.model_catalog import validate_catalog
from agent.core.model_diagnostics import ModelDiagnostics
from agent.llm.openai_compatible import OpenAICompatibleProvider

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


async def main():
    parser = argparse.ArgumentParser(description='Read-only model diagnostics; no requests without --live-test. OS-protected keys are available in Settings UI; CLI accepts environment only.')
    parser.add_argument('--data-dir', type=Path, default=Path(os.getenv('LCA_DATA_DIR') or (Path(os.getenv('APPDATA', str(Path.home()))) / 'local-coding-agent-desktop')))
    parser.add_argument('--profile', required=True, help='Saved model_profile_id')
    parser.add_argument('--live-test', action='store_true', help='Explicitly authorize up to 3 paid API requests, one synthetic JPEG, no retry')
    parser.add_argument('--no-vision', action='store_true')
    args = parser.parse_args()
    with closing(sqlite3.connect('file:' + (args.data_dir/'local-coding-agent.sqlite3').resolve().as_posix() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', ('models.catalog.v1',)).fetchone()
        if not row:
            parser.error('No saved model catalog; use Settings first')
        catalog = validate_catalog(json.loads(row[0]))
    profile = next((p for p in catalog['profiles'] if p['model_profile_id'] == args.profile), None)
    if not profile:
        parser.error('Unknown saved profile')
    connection = next(c for c in catalog['connections'] if c['connection_id'] == profile['connection_id'])
    # No key arguments, shell history, encrypted-file mutation or plaintext reports.
    key = os.getenv('LCA_DIAGNOSTIC_API_KEY', '')
    provider = OpenAICompatibleProvider(base_url=connection['base_url'], api_key=key, preferred_model=profile['model_id'])
    report = await ModelDiagnostics().run(provider, connection, profile, live=args.live_test, vision=not args.no_vision)
    report['credential_source'] = 'environment' if key else 'unavailable_in_cli; use Settings OS protected storage'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    stages = ('connection', 'text', 'tools') + (() if args.no_vision else ('vision',))
    return 0 if report['configuration'] == 'PASS' and (not args.live_test or all(report[s] == 'PASS' for s in stages)) else 2


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
