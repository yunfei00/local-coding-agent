"""Project-scoped P3 verification tool; produces a Chinese report."""
from __future__ import annotations
import asyncio
from agent.tools.base import BaseTool,ToolResult,ToolError
from agent.verification.pipeline import verify_deliverables,write_report
from agent.verification.repair import repair_and_verify

class DeliverableVerifyTool(BaseTool):
    name="deliverable_verify"
    description="Verify Office deliverables by opening files and checking expected sheet names, cell values, text, and minimum item counts. Optionally create a Chinese Markdown acceptance report. Structural/content checks only."
    parameters={"type":"object","properties":{
        "spec":{"type":"object","description":"files: [{path,expect:{sheets,cells,contains,min_items}}]"},
        "report_path":{"type":"string","description":"New workspace-relative Markdown report filename (optional)"},
        "repair":{"type":"boolean","description":"Explicitly repair expected Excel cells or reconstruct missing files from full create spec"},
        "max_rounds":{"type":"integer","minimum":0,"maximum":3}
    },"required":["spec"],"additionalProperties":False}
    def __init__(self,workspace):
        self.workspace=workspace
    async def execute(self,arguments,*,on_output=None):
        spec=arguments.get("spec")
        if not isinstance(spec,dict):
            raise ToolError("VERIFY_SPEC","Verification spec must be an object")
        try:
            if arguments.get("repair"):
                result=await asyncio.to_thread(repair_and_verify,self.workspace.root,spec,max_rounds=arguments.get("max_rounds",2))
                return ToolResult(ok=result["ok"],summary="自动修复并复验",data=result)
            if arguments.get("report_path"):
                output=self.workspace.resolve(arguments["report_path"])
                result=await asyncio.to_thread(write_report,self.workspace.root,spec,str(output.relative_to(self.workspace.root)))
                return ToolResult(ok=result["verification"]["ok"],summary="中文交付验收报告",data=result,changed_paths=[self.workspace.relative(output)])
            result=await asyncio.to_thread(verify_deliverables,self.workspace.root,spec)
            return ToolResult(ok=result["ok"],summary="交付内容自动验收",data=result)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            raise ToolError("VERIFY_FAILED",str(exc)) from exc

def verification_tools(workspace):
    return [DeliverableVerifyTool(workspace)]
