"""项目知识的统一读取边界；不因 Full Access 放宽自动索引。"""
from pathlib import Path
import os
import re
from pathspec import GitIgnoreSpec
from agent.tools.workspace import DEFAULT_IGNORED_DIRS

EXCLUDED = DEFAULT_IGNORED_DIRS | {'.runtime','build','out','target','coverage','release','.next','.codex-attachments','validation-reports'}
EXTENSIONS = {'.md','.txt','.py','.ts','.tsx','.js','.jsx','.json','.yaml','.yml','.toml','.log'}
MAX_BYTES = 256 * 1024
SECRET = re.compile(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|\b(?:sk-[\w-]{8,}|gh[pousr]_[\w]{20,})\b|(?i:bearer\s+[\w./+=-]{8,})')
KEY_PATTERN=r'(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|cookie|secret|authorization|_authToken)'
CREDENTIAL_LITERAL=re.compile(r'(?i)'+KEY_PATTERN+r'\s*["\x27]?\s*[:=]\s*(["\x27])([^"\x27\r\n]{3,})\1')
CREDENTIAL_BARE=re.compile(r'(?i)(?<![\w])'+KEY_PATTERN+r'["\x27]?\s*[:=]\s*([A-Za-z0-9_/+=.-]{3,})(?=\s|$|[;,}])')

def sensitive(text,*,source_code=False):
    text=str(text)
    bare=any(not source_code or not m.group(1).isidentifier() or len(m.group(1))>24 for m in CREDENTIAL_BARE.finditer(text))
    return bool(SECRET.search(text) or CREDENTIAL_LITERAL.search(text) or bare or re.search(r'(?im)^(?:cookie|set-cookie|authorization)\s*:\s*\S.+$|https?://[^/\s]+:[^@\s]+@',text))

def private_name(path):
    name=Path(path).name.lower()
    return sensitive(name) or name.startswith('.env') or name in {'id_rsa','id_ed25519','local state','.npmrc','secrets.json'} or any(s in name for s in ('credentials','provider-secrets','model-secrets','mcp-secrets')) or Path(name).suffix in {'.pem','.key','.pfx','.p12'}

class ProjectFiles:
    def __init__(self, root,exact_secrets=()):
        self.exact_secrets=tuple(s for s in exact_secrets if isinstance(s,str) and len(s)>=8)
        self.root=Path(root).resolve();self.specs={};self.excludes=[]
        config=self.root/'.lca/exclude'
        if config.resolve().is_relative_to(self.root) and not config.parent.is_symlink() and not getattr(config.parent,'is_junction',lambda:False)() and config.is_file() and not config.is_symlink() and config.stat().st_size<=MAX_BYTES:
            self.excludes=GitIgnoreSpec.from_lines(config.read_text(encoding='utf-8').splitlines())

    def allowed(self, path, *, directory=False):
        path=Path(path)
        try:
            relative=path.relative_to(self.root)
            path.resolve().relative_to(self.root)
        except (ValueError,OSError):return False
        if any(p in EXCLUDED for p in relative.parts) or private_name(path):return False
        if any((self.root/Path(*relative.parts[:i])).is_symlink() or getattr(self.root/Path(*relative.parts[:i]),'is_junction',lambda:False)() for i in range(1,len(relative.parts)+1)):return False
        key=relative.as_posix()+('/' if directory else '')
        if any(s in key for s in self.exact_secrets):return False
        if self.excludes and self.excludes.match_file(key):return False
        ignored=False
        for parent in [self.root,*list(path.parents)[:len(relative.parts)-1][::-1]]:
            if parent not in self.specs:
                file=parent/'.gitignore'
                self.specs[parent]=GitIgnoreSpec.from_lines(file.read_text(encoding='utf-8',errors='replace').splitlines()) if file.is_file() and not file.is_symlink() and file.stat().st_size<=MAX_BYTES else None
            spec=self.specs[parent]
            if spec:
                item=path.relative_to(parent).as_posix()+('/' if directory else '')
                # Preserve nested negation, without descending into excluded parents.
                for pattern in spec.patterns:
                    if pattern.include is not None and pattern.match_file(item):ignored=pattern.include
        return not ignored

    def paths(self, maximum=2500):
        count=0
        for current,dirs,files in os.walk(self.root,topdown=True,followlinks=False):
            dirs[:]=sorted(d for d in dirs if self.allowed(Path(current)/d,directory=True))
            for name in sorted(files):
                p=Path(current)/name
                if self.allowed(p) and p.suffix.lower() in EXTENSIONS:
                    yield p;count+=1
                    if count>=maximum:return

    def read(self, path, max_bytes=MAX_BYTES):
        path=Path(path)
        try:
            if not self.allowed(path) or not path.is_file() or path.stat().st_size>max_bytes:return None
            with path.open('rb') as handle:raw=handle.read(max_bytes+1)
        except OSError:return None  # Removed or permission changed during indexing; never use stale bytes.
        if len(raw)>max_bytes or b'\0' in raw:return None
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:return None
        return None if sensitive(text,source_code=path.suffix.lower() in {'.py','.js','.jsx','.ts','.tsx'}) or any(s in text for s in self.exact_secrets) else text
