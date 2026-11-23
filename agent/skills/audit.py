"""Static, non-executing security review for third-party Agent Skills."""
from __future__ import annotations
from pathlib import Path
import re
from agent.skills.manager import SkillManager

SUSPICIOUS = {
    "remote-shell": re.compile(r"(curl|wget|iwr|Invoke-WebRequest).{0,160}(\||iex|Invoke-Expression|bash|sh)",re.I),
    "destructive-command": re.compile(r"\b(rm\s+-rf|Remove-Item\s+.*-Recurse|format\s+[a-z]:|del\s+/s)\b",re.I),
    "credential-access": re.compile(r"(\.ssh[/\\]|\.aws[/\\]|id_rsa|credential[s]?\.json|\.env\b)",re.I),
    "elevated-execution": re.compile(r"\b(sudo|runas|Start-Process\s+.*-Verb\s+RunAs)\b",re.I),
}
SCRIPT_SUFFIXES = {".py",".sh",".ps1",".bat",".cmd",".js",".ts",".exe",".dll"}

def audit_skill(manager: SkillManager, name: str) -> dict:
    skill=manager.resolve(name)
    if skill is None:
        raise ValueError("Skill unavailable or disabled")
    issues=[]
    total=0
    for file in sorted(skill.directory.rglob("*")):
        if file.is_symlink():
            issues.append({"file":str(file.relative_to(skill.directory)),"risk":"symlink"})
            continue
        if not file.is_file():
            continue
        total+=1
        rel=file.relative_to(skill.directory).as_posix()
        if file.suffix.lower() in SCRIPT_SUFFIXES:
            issues.append({"file":rel,"risk":"executable-content"})
        if file.stat().st_size > 1024*1024:
            issues.append({"file":rel,"risk":"large-file"})
            continue
        if file.suffix.lower() not in {".md",".txt",".json",".yaml",".yml",".py",".sh",".ps1",".bat",".cmd",".js",".ts"}:
            continue
        data=file.read_text(encoding="utf-8",errors="replace")
        for risk, pattern in SUSPICIOUS.items():
            if pattern.search(data):
                issues.append({"file":rel,"risk":risk})
    return {"name":name,"files":total,"issues":issues,"requires_review":bool(issues),"executed":False}
