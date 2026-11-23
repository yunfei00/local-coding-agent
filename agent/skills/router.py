"""Conservative task-to-skill suggestions, with explicit provenance and no execution."""
from __future__ import annotations
from dataclasses import dataclass
import re
from agent.skills.manager import SkillManager

@dataclass(frozen=True)
class SkillMatch:
    name: str
    description: str
    score: int
    source: str

ALIASES = {
    "excel": ("excel", "xlsx", "spreadsheet", "工作簿", "电子表格", "表格", "数据分析"),
    "word": ("word", "docx", "document", "文档", "报告", "标书"),
    "powerpoint": ("powerpoint", "ppt", "pptx", "幻灯片", "演示文稿"),
    "browser": ("browser", "webpage", "website", "浏览器", "网页", "网站"),
}

def suggest_skills(manager: SkillManager, task: str, *, limit: int = 4) -> list[SkillMatch]:
    if not isinstance(task, str) or len(task) > 20000:
        raise ValueError("Invalid task")
    normalized = task.casefold()
    words = set(re.findall(r"[a-z0-9-]+", normalized))
    ranked = []
    for skill in manager.catalog():
        if not skill.enabled:
            continue
        score = 0
        for alias in ALIASES.get(skill.name, ()):
            if alias in words or (not alias.isascii() and alias in normalized):
                score += 10
        for token in re.findall(r"[a-z0-9-]+", skill.name + " " + skill.description.casefold()):
            if len(token) > 3 and token in words:
                score += 1
        if score:
            ranked.append(SkillMatch(skill.name, skill.description, score, skill.source))
    return sorted(ranked, key=lambda x: (-x.score, x.name))[:limit]
