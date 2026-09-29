from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any


HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)


def _clean_git_path(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            parsed = shlex.split(value)
            if len(parsed) == 1:
                value = parsed[0]
        except ValueError:
            pass
    if value in {"/dev/null", "NUL"}:
        return value
    if value.startswith("a/") or value.startswith("b/"):
        return value[2:]
    return value


def _diff_header_paths(raw: str) -> tuple[str, str]:
    body = raw[len("diff --git ") :].strip()
    if body.startswith('"'):
        try:
            parts = shlex.split(body)
            if len(parts) >= 2:
                return _clean_git_path(parts[0]), _clean_git_path(parts[1])
        except ValueError:
            pass

    separator = body.find(" b/", 2)
    if separator >= 0:
        old_value = body[:separator]
        new_value = body[separator + 1 :]
        return _clean_git_path(old_value), _clean_git_path(new_value)

    parts = body.split(" ", 1)
    old_value = parts[0] if parts else ""
    new_value = parts[1] if len(parts) > 1 else old_value
    return _clean_git_path(old_value), _clean_git_path(new_value)


def parse_unified_diff(
    text: str,
    *,
    max_files: int = 100,
    max_lines_per_file: int = 800,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_hunk: dict[str, Any] | None = None
    old_line = 0
    new_line = 0

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            if current:
                files.append(current)
            old_path, new_path = _diff_header_paths(raw)
            current = {
                "path": new_path,
                "old_path": old_path,
                "new_path": new_path,
                "status": "modified",
                "binary": False,
                "additions": 0,
                "deletions": 0,
                "hunks": [],
                "truncated": False,
                "similarity": None,
                "_stored_lines": 0,
            }
            current_hunk = None
            continue

        if current is None:
            continue

        if raw.startswith("new file mode "):
            current["status"] = "added"
            continue
        if raw.startswith("deleted file mode "):
            current["status"] = "deleted"
            continue
        if raw.startswith("similarity index "):
            value = raw[len("similarity index ") :].strip().rstrip("%")
            try:
                current["similarity"] = int(value)
            except ValueError:
                current["similarity"] = None
            continue
        if raw.startswith("rename from "):
            current["status"] = "renamed"
            current["old_path"] = raw[len("rename from ") :]
            continue
        if raw.startswith("rename to "):
            current["new_path"] = raw[len("rename to ") :]
            current["path"] = current["new_path"]
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            current["binary"] = True
            continue
        if raw.startswith("--- "):
            current["old_path"] = _clean_git_path(raw[4:].split("\t", 1)[0])
            continue
        if raw.startswith("+++ "):
            current["new_path"] = _clean_git_path(raw[4:].split("\t", 1)[0])
            if current["new_path"] != "/dev/null":
                current["path"] = current["new_path"]
            elif current.get("old_path"):
                current["path"] = current["old_path"]
            continue

        match = HUNK_RE.match(raw)
        if match:
            old_line = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_line = int(match.group(3))
            new_count = int(match.group(4) or "1")
            current_hunk = {
                "header": raw,
                "old_start": old_line,
                "old_count": old_count,
                "new_start": new_line,
                "new_count": new_count,
                "lines": [],
            }
            current["hunks"].append(current_hunk)
            continue

        if current_hunk is None:
            continue

        line: dict[str, Any]
        if raw.startswith("+") and not raw.startswith("+++"):
            line = {
                "type": "add",
                "content": raw[1:],
                "old_line": None,
                "new_line": new_line,
            }
            current["additions"] += 1
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            line = {
                "type": "delete",
                "content": raw[1:],
                "old_line": old_line,
                "new_line": None,
            }
            current["deletions"] += 1
            old_line += 1
        elif raw.startswith("\\"):
            line = {
                "type": "meta",
                "content": raw,
                "old_line": None,
                "new_line": None,
            }
        else:
            content = raw[1:] if raw.startswith(" ") else raw
            line = {
                "type": "context",
                "content": content,
                "old_line": old_line,
                "new_line": new_line,
            }
            old_line += 1
            new_line += 1

        if current["_stored_lines"] < max_lines_per_file:
            current_hunk["lines"].append(line)
            current["_stored_lines"] += 1
        else:
            current["truncated"] = True

    if current:
        files.append(current)

    if len(files) > max_files:
        files = files[:max_files]
        if files:
            files[-1]["truncated"] = True

    for item in files:
        item["hunk_count"] = len(item.get("hunks") or [])
        item["preview_line_count"] = sum(
            len(hunk.get("lines") or [])
            for hunk in item.get("hunks") or []
        )
        item.pop("_stored_lines", None)

    return files


def synthesize_untracked_file(
    path: Path,
    *,
    display_path: str,
    max_lines: int = 400,
    max_bytes: int = 256 * 1024,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": display_path,
        "old_path": "/dev/null",
        "new_path": display_path,
        "status": "untracked",
        "binary": False,
        "additions": 0,
        "deletions": 0,
        "hunks": [],
        "truncated": False,
        "similarity": None,
        "hunk_count": 0,
        "preview_line_count": 0,
    }

    try:
        raw = path.read_bytes()
    except OSError:
        result["binary"] = True
        return result

    if b"\x00" in raw[:4096]:
        result["binary"] = True
        return result

    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        result["truncated"] = True

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        result["truncated"] = True

    hunk_lines = [
        {
            "type": "add",
            "content": line,
            "old_line": None,
            "new_line": index,
        }
        for index, line in enumerate(lines, start=1)
    ]
    result["additions"] = len(hunk_lines)
    result["hunks"] = [
        {
            "header": f"@@ -0,0 +1,{len(hunk_lines)} @@",
            "old_start": 0,
            "old_count": 0,
            "new_start": 1,
            "new_count": len(hunk_lines),
            "lines": hunk_lines,
        }
    ]
    result["hunk_count"] = 1
    result["preview_line_count"] = len(hunk_lines)
    return result
