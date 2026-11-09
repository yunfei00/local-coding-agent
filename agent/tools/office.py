"""Office operations through ToolRegistry, confined to the current workspace."""
from __future__ import annotations
import asyncio
import json
from agent.tools.base import BaseTool, ToolResult, ToolError
from agent.office import engine
from agent.verification.office import verify_office

class OfficeTool(BaseTool):
    name = "office_document"
    description = "Read, create or structurally verify XLSX, DOCX or PPTX files in the workspace. Writes are not automatically approved."
    parameters = {"type":"object","properties":{
        "operation":{"type":"string","enum":["inspect","create","verify"]},
        "path":{"type":"string"},
        "kind":{"type":"string","enum":["excel","word","ppt"]},
        "spec":{"type":"object","description":"Excel: sheets map; Word: title and sections; PPT: slides"}
    },"required":["operation","path"],"additionalProperties":False}
    def __init__(self, workspace):
        self.workspace=workspace
    async def execute(self, arguments, *, on_output=None):
        op=arguments.get("operation")
        if op not in {"inspect","create","verify"}:
            raise ToolError("OFFICE_OPERATION_INVALID","Unsupported operation")
        try:
            path=self.workspace.resolve(arguments["path"])
            if op=="verify":
                return ToolResult(ok=True,summary="Office structural verification",data=await asyncio.to_thread(verify_office,path))
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
        except (KeyError,TypeError,ValueError,ImportError,OSError) as exc:
            raise ToolError("OFFICE_FAILED",f"{type(exc).__name__}: {exc}") from exc

def office_tools(workspace):
    return [OfficeTool(workspace)]
