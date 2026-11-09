"""Explicit CLI entrypoint; uses existing run_command permission checks."""
import argparse
import json
from pathlib import Path
from agent.skills.manager import SkillManager
from agent.office import engine
from agent.verification.office import verify_office

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("skills-list")
    for action in ("skills-enable", "skills-disable", "skills-uninstall"):
        p = sub.add_parser(action); p.add_argument("name")
    p = sub.add_parser("skills-install"); p.add_argument("source")
    p = sub.add_parser("inspect"); p.add_argument("path")
    p = sub.add_parser("verify"); p.add_argument("path")
    p = sub.add_parser("create"); p.add_argument("kind", choices=["excel","word","ppt"]); p.add_argument("spec"); p.add_argument("output")
    p = sub.add_parser("export-pdf"); p.add_argument("source"); p.add_argument("output")
    args = parser.parse_args()
    root = Path(args.workspace).resolve()
    manager = SkillManager(root)
    def confined(value):
        p = (root / value).resolve()
        if not p.is_relative_to(root):
            raise ValueError("Path outside workspace")
        return p
    if args.command == "skills-list":
        result = [vars(x) for x in manager.catalog()]
    elif args.command == "skills-enable":
        manager.set_enabled(args.name, True); result = {"enabled": args.name}
    elif args.command == "skills-disable":
        manager.set_enabled(args.name, False); result = {"disabled": args.name}
    elif args.command == "skills-install":
        result = {"installed": manager.install_local(confined(args.source))}
    elif args.command == "skills-uninstall":
        manager.uninstall_project(args.name); result = {"uninstalled": args.name}
    elif args.command == "inspect":
        path = confined(args.path)
        reader = {".xlsx": engine.inspect_excel, ".docx": engine.inspect_word, ".pptx": engine.inspect_ppt}[path.suffix.lower()]
        result = reader(path)
    elif args.command == "verify":
        result = verify_office(confined(args.path))
    elif args.command == "create":
        spec = json.loads(confined(args.spec).read_text(encoding="utf-8"))
        path = confined(args.output)
        if args.kind == "excel": result = engine.create_excel(path, spec["sheets"])
        elif args.kind == "word": result = engine.create_word(path, spec["title"], spec["sections"])
        else: result = engine.create_ppt(path, spec["slides"])
    else:
        result = engine.office_com_export_pdf(confined(args.source), confined(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
