"""Bounded, deterministic repair of expected Office deliverables.

Only explicit expected values are repaired; arbitrary scripts and model-generated
commands are never executed. Changes are confined to workspace files.
"""
from __future__ import annotations
from pathlib import Path
from agent.office.engine import create_excel,create_word,create_ppt
from agent.office.edit import edit_excel,edit_word,edit_ppt
from agent.verification.pipeline import verify_deliverables

def repair_and_verify(root: str|Path, spec: dict, *, max_rounds: int=2) -> dict:
    root=Path(root).resolve(strict=True)
    if not isinstance(max_rounds,int) or not 0<=max_rounds<=3:
        raise ValueError("max_rounds must be 0-3")
    initial=verify_deliverables(root,spec)
    history=[{"round":0,"verification":initial}]
    if initial["ok"] or max_rounds==0:
        return {"ok":initial["ok"],"rounds":0,"history":history,"verification":initial}
    for round_no in range(1,max_rounds+1):
        repaired=[]
        for entry,check in zip(spec["files"],history[-1]["verification"]["checks"]):
            if check["ok"]:
                continue
            path=(root/entry["path"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Repair path escapes workspace")
            expected=entry.get("expect",{})
            suffix=path.suffix.lower()
            if not path.exists():
                # Never create a fabricated report; only explicit complete source
                # specifications can be used to reconstruct missing deliverables.
                create=entry.get("create")
                if not isinstance(create,dict):
                    continue
                if suffix==".xlsx":
                    create_excel(path,create["sheets"])
                elif suffix==".docx":
                    create_word(path,create["title"],create["sections"])
                elif suffix==".pptx":
                    create_ppt(path,create["slides"])
                else:
                    continue
                repaired.append(entry["path"])
            elif suffix==".xlsx" and expected.get("cells"):
                sheets={}
                for cell in expected["cells"]:
                    sheet=sheets.setdefault(cell["sheet"],{"cells":{}})
                    sheet["cells"][cell["address"]]=cell["value"]
                edit_excel(path,{"sheets":sheets})
                repaired.append(entry["path"])
            # Word and PPT textual mismatch cannot be repaired without an
            # unambiguous source mapping; fail rather than hallucinate content.
        verification=verify_deliverables(root,spec)
        history.append({"round":round_no,"repaired":repaired,"verification":verification})
        if verification["ok"] or not repaired:
            break
    final=history[-1]["verification"]
    return {"ok":final["ok"],"rounds":len(history)-1,"history":history,"verification":final}
