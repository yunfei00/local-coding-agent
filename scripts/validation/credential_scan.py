"""Bounded repository credential/artifact scan; findings never print secret values."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = [re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
            re.compile(r'\b(?:sk-[A-Za-z0-9_-]{28,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16})\b')]
known = [v for k,v in os.environ.items() if any(s in k.upper() for s in ('API_KEY','ACCESS_TOKEN','SECRET_KEY')) and len(v) >= 16]
paths = subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
findings=[]; count=0
for name in filter(None, paths):
    path=ROOT/name
    if not path.is_file(): continue
    if re.search(r'(?:^|/)(?:provider-secrets|model-secrets|mcp-secrets)\.json$|(?:^|/)(?:desktop-artifacts|validation-reports)/',name):
        findings.append({'path':name,'kind':'private artifact tracked'})
    if path.stat().st_size > 2_000_000: continue
    raw=path.read_bytes()
    if b'\0' in raw: continue
    text=raw.decode('utf-8',errors='replace');count+=1
    for line_no,line in enumerate(text.splitlines(),1):
        if any(p.search(line) for p in PATTERNS) or any(value in line for value in known):
            findings.append({'path':name,'line':line_no,'kind':'possible credential'})
report={'ok':not findings,'files_scanned':count,'findings':findings,'limitations':'Pattern and available environment-secret scan; not a proof against every possible credential format.'}
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(0 if report['ok'] else 1)
