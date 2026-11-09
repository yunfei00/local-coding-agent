"""Office operations through ToolRegistry, confined to the current workspace."""
from __future__ import annotations
import asyncio
import json
from agent.tools.base import BaseTool, ToolResult, ToolError
from agent.office import engine
from agent.office.edit import edit_excel, edit_word, edit_ppt
from agent.office.windows import detect_office, export_pdf
from agent.office.bundle import create_bundle
from agent.office.uia import list_office_windows
from agent.verification.office import verify_office

class OfficeTool(BaseTool):
    name = "office_document"
    description = "Inspect, create, edit or structurally verify XLSX, DOCX and PPTX files in the workspace. Editing existing files is destructive; user permissions still apply."
    parameters = {"type":"object","properties":{
        "operation":{"type":"string","enum":["inspect","create","edit","verify","detect","export_pdf","bundle","uia_list"]},
        "path":{"type":"string"},
        "kind":{"type":"string","enum":["excel","word","ppt"]},
        "target":{"type":"string","description":"PDF destination for export_pdf"},
        "name":{"type":"string","description":"Bundle base filename"},
        "spec":{"type":"object","description":"Excel: sheets map; Word: title and sections; PPT: slides"}
    },"required":["operation","path"],"additionalProperties":False}
    def __init__(self, workspace):
        self.workspace=workspace
    async def execute(self, arguments, *, on_output=None):
        op=arguments.get("operation")
        if op not in {"inspect","create","edit","verify","detect","export_pdf","bundle","uia_list"}:
            raise ToolError("OFFICE_OPERATION_INVALID","Unsupported operation")
        try:
            if op=="uia_list":
                return ToolResult(ok=True,summary="Office UIA window discovery",data=await asyncio.to_thread(list_office_windows))
            if op=="detect":
                return ToolResult(ok=True,summary="Windows Office installation probe",data=await asyncio.to_thread(detect_office))
            path=self.workspace.resolve(arguments["path"])
            if op=="bundle":
                spec=arguments.get("spec")
                if not isinstance(spec,dict):
                    raise ToolError("OFFICE_SPEC","Missing bundle spec")
                result=await asyncio.to_thread(create_bundle,path,str(arguments["name"]),spec)
                return ToolResult(ok=True,summary="Excel Word PPT bundle created and verified",data=result,changed_paths=[self.workspace.relative(x) for x in result["files"].values()])
            if op=="export_pdf":
                target=self.workspace.resolve(arguments["target"])
                result=await asyncio.to_thread(export_pdf,path,target)
                return ToolResult(ok=True,summary="Office PDF export verified",data=result,changed_paths=[self.workspace.relative(target)])
            if op=="edit":
                spec=arguments.get("spec")
                if not isinstance(spec,dict):
                    raise ToolError("OFFICE_SPEC","Missing structured edit spec")
                editors={".xlsx":edit_excel,".docx":edit_word,".pptx":edit_ppt}
                editor=editors.get(path.suffix.lower())
                if editor is None:
                    raise ToolError("OFFICE_FORMAT","Unsupported file type")
                output=await asyncio.to_thread(editor,path,spec)
                check=await asyncio.to_thread(verify_office,path)
                return ToolResult(ok=check["ok"],summary="Office document edited and verified",data={"result":output,"verification":check},changed_paths=[self.workspace.relative(path)])
            if op=="verify":
                check=await asyncio.to_thread(verify_office,path)
                return ToolResult(ok=check["ok"],summary="Office structural verification",data=check)
            if op=="inspect":
                readers={".xlsx":engine.inspect_excel,".docx":engine.inspect_word,".pptx":engine.inspect_ppt}
                reader=readers.get(path.suffix.lower())
                if reader is None:
                    raise ToolError("OFFICE_FORMAT","Unsupported file type")
                result=await asyncio.to_thread(reader,path)
                return ToolResult(ok=True,summary="Office document inspected",data=result)
            kind=arguments.get("kind")
            spec=arguments.get("spec")
            if not isinstance(spec,dict):
                raise ToolError("OFFICE_SPEC","Missing structured spec")
            if path.exists():
                raise ToolError("OFFICE_EXISTS","Refusing to overwrite existing document")
            if kind=="excel":
                output=await asyncio.to_thread(engine.create_excel,path,spec["sheets"])
            elif kind=="word":
                output=await asyncio.to_thread(engine.create_word,path,spec["title"],spec["sections"])
            elif kind=="ppt":
                output=await asyncio.to_thread(engine.create_ppt,path,spec["slides"])
            else:
                raise ToolError("OFFICE_KIND","Unsupported document kind")
            check=await asyncio.to_thread(verify_office,path)
            return ToolResult(ok=check["ok"],summary="Office document created and structurally checked",data={"verification":check},changed_paths=[self.workspace.relative(path)])
        except (KeyError,TypeError,ValueError,ImportError,OSError,engine.OfficeError) as exc:
            raise ToolError("OFFICE_FAILED",f"{type(exc).__name__}: {exc}") from exc

def office_tools(workspace):
    return [OfficeTool(workspace)]
