"""Explicit GitHub skill download; never execute untrusted content."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen
import io
import json
import tempfile
import zipfile
from agent.skills.manager import SkillManager

MAX_DOWNLOAD = 20 * 1024 * 1024

def parse_github_url(url: str) -> tuple[str, str, str, str]:
    p = urlparse(url)
    if p.scheme != "https" or p.hostname != "github.com" or p.username or p.password or p.port:
        raise ValueError("Only public github.com HTTPS URLs are supported")
    parts = [x for x in p.path.strip("/").split("/") if x]
    if len(parts) < 2 or any(x in (".", "..") for x in parts):
        raise ValueError("Invalid GitHub URL")
    owner, repo = parts[:2]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not all(s.replace("-", "").replace("_", "").isalnum() for s in (owner, repo)):
        raise ValueError("Invalid repository")
    if len(parts) == 2:
        return owner, repo, "", ""
    if len(parts) < 5 or parts[2] != "tree":
        raise ValueError("Use a repository URL or /tree/<branch>/<path> URL")
    return owner, repo, parts[3], "/".join(parts[4:])

def _download(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "LocalCodingAgent-Skills/1.2"})
    with urlopen(req, timeout=20) as response:
        if urlparse(response.url).hostname not in {"api.github.com", "codeload.github.com"}:
            raise ValueError("Unexpected download host")
        data = response.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD:
            raise ValueError("Download exceeds size limit")
        return data

def install_github(manager: SkillManager, url: str, *, skill_path: str | None = None) -> str:
    owner, repo, branch, subpath = parse_github_url(url)
    if not branch:
        metadata = json.loads(_download(f"https://api.github.com/repos/{owner}/{repo}"))
        branch = metadata["default_branch"]
    # Branch may contain slashes; the GitHub tree URL is ambiguous. Caller may
    # supply an explicit skill_path for such branches.
    if skill_path is not None:
        subpath = skill_path
    if subpath and (Path(subpath).is_absolute() or ".." in Path(subpath).parts):
        raise ValueError("Invalid skill path")
    archive = _download(f"https://codeload.github.com/{owner}/{repo}/zip/{quote(branch, safe='')}")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "repository.zip"
        package.write_bytes(archive)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            names = [n for n in z.namelist() if n.endswith("/SKILL.md")]
        matches = [n for n in names if (not subpath or n.endswith("/" + subpath.strip("/") + "/SKILL.md"))]
        if len(matches) != 1:
            raise ValueError("Specify an unambiguous skill_path within repository")
        skill_prefix = matches[0][:-len("SKILL.md")]
        entries = [x for x in zipfile.ZipFile(io.BytesIO(archive)).infolist() if x.filename.startswith(skill_prefix)]
        if len(entries) > 256 or sum(x.file_size for x in entries) > 16 * 1024 * 1024:
            raise ValueError("Skill too large")
        target = root / Path(skill_prefix.rstrip("/")).name
        target.mkdir()
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for entry in entries:
                relative = entry.filename[len(skill_prefix):]
                if not relative:
                    continue
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unsafe archive entry")
                output = (target / relative_path).resolve()
                if not output.is_relative_to(target):
                    raise ValueError("Unsafe archive path")
                if entry.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(z.read(entry))
        return manager.install_local(target)
