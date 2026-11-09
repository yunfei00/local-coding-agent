"""Create a cohesive Excel/Word/PowerPoint deliverable set with rollback on failure."""
from __future__ import annotations
from pathlib import Path
from agent.office import engine
from agent.verification.office import verify_office

def create_bundle(root: str | Path, name: str, spec: dict) -> dict:
    if not isinstance(name,str) or not name or len(name)>80 or not all(c.isalnum() or c in "-_" for c in name):
        raise ValueError("Invalid bundle name")
    root=Path(root).resolve(strict=True)
    outputs={
        "excel":root/(name+".xlsx"),
        "word":root/(name+".docx"),
        "ppt":root/(name+".pptx"),
    }
    if any(p.exists() for p in outputs.values()):
        raise FileExistsError("Bundle output already exists")
    created=[]
    try:
        engine.create_excel(outputs["excel"],spec["excel"]["sheets"])
        created.append(outputs["excel"])
        engine.create_word(outputs["word"],spec["word"]["title"],spec["word"]["sections"])
        created.append(outputs["word"])
        engine.create_ppt(outputs["ppt"],spec["ppt"]["slides"])
        created.append(outputs["ppt"])
        checks={kind:verify_office(path) for kind,path in outputs.items()}
        if not all(check["ok"] for check in checks.values()):
            raise RuntimeError("Bundle verification failed")
        return {"files":{kind:str(path) for kind,path in outputs.items()},"verification":checks}
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
