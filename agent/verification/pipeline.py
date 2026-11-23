"""P3 autonomous deliverable validation with bounded, evidence-backed checks.

Verification does not invent visual/layout or live-browser evidence.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime,timezone
from agent.verification.office import verify_office
from agent.office.engine import inspect_excel,inspect_word,inspect_ppt

def verify_deliverables(root: str|Path, spec: dict) -> dict:
    root=Path(root).resolve(strict=True)
    files=spec.get("files",[])
    if not isinstance(files,list) or not 1<=len(files)<=30:
        raise ValueError("files must contain 1-30 entries")
    checks=[]
    for entry in files:
        if not isinstance(entry,dict) or not isinstance(entry.get("path"),str):
            raise ValueError("Each file requires a path")
        path=(root/entry["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Verification path escapes workspace")
        base=verify_office(path)
        expected=entry.get("expect",{})
        if not isinstance(expected,dict):
            raise ValueError("expect must be an object")
        assertions=[]
        if base["ok"]:
            reader={".xlsx":inspect_excel,".docx":inspect_word,".pptx":inspect_ppt}[path.suffix.lower()]
            data=reader(path)
            if path.suffix.lower()==".xlsx":
                sheets=data["sheets"]
                actual_names=[s["name"] for s in sheets]
                for name in expected.get("sheets",[]):
                    assertions.append({"check":"sheet:"+str(name),"ok":name in actual_names})
                for cell in expected.get("cells",[]):
                    name=cell["sheet"]
                    from openpyxl import load_workbook
                    book=load_workbook(path,read_only=True,data_only=False)
                    try:
                        actual=book[name][cell["address"]].value if name in book else None
                    finally:
                        book.close()
                    assertions.append({"check":"cell:"+name+"!"+cell["address"],"ok":actual==cell["value"],"actual":str(actual)[:200]})
            else:
                text="\n".join(data["paragraphs"]+[str(t) for t in data["tables"]]) if path.suffix.lower()==".docx" else "\n".join(" ".join(slide) for slide in data["slides"])
                for phrase in expected.get("contains",[]):
                    assertions.append({"check":"contains:"+str(phrase)[:80],"ok":str(phrase) in text})
            if "min_items" in expected:
                assertions.append({"check":"min_items","ok":base["items"]>=int(expected["min_items"])})
        ok=bool(base["ok"]) and all(a["ok"] for a in assertions)
        checks.append({"path":entry["path"],"ok":ok,"structural":base,"assertions":assertions})
    passed=sum(x["ok"] for x in checks)
    return {"ok":passed==len(checks),"passed":passed,"total":len(checks),
            "checks":checks,"level":"structural-and-content",
            "generated_at":datetime.now(timezone.utc).isoformat(),
            "limitations":["No visual layout certification","No browser upload evidence unless separately supplied"]}

def write_report(root: str|Path, spec: dict, report_path: str) -> dict:
    root=Path(root).resolve(strict=True)
    target=(root/report_path).resolve()
    if not target.is_relative_to(root) or target.suffix.lower()!=".md" or target.exists():
        raise ValueError("Report must be a new Markdown file inside the workspace")
    result=verify_deliverables(root,spec)
    lines=["# 自动化交付验收报告","",f"结果：{'通过' if result['ok'] else '未通过'}",
           f"文件通过：{result['passed']}/{result['total']}","",
           "说明：结构及内容校验不等于视觉排版验收。",""]
    for item in result["checks"]:
        lines.extend([f"## {item['path']} — {'通过' if item['ok'] else '失败'}",
                      f"- 结构：{json.dumps(item['structural'],ensure_ascii=False)}"])
        lines.extend(f"- {'通过' if a['ok'] else '失败'}：{a['check']}" for a in item["assertions"])
        lines.append("")
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open("x",encoding="utf-8") as output:
        output.write("\n".join(lines))
    return {"verification":result,"report":str(target)}
