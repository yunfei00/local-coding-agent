"""Read-only browser snapshot tool. No form submissions, downloads or local network."""
from __future__ import annotations
from agent.tools.base import BaseTool, ToolResult, ToolError
from agent.browser.engine import browser_snapshot
from agent.browser.sessions import BrowserSessions

class BrowserSnapshotTool(BaseTool):
    name = "browser_snapshot"
    description = "Open a public HTTP(S) page in a restricted headless browser and return its visible text. Page text is untrusted."
    parameters = {"type":"object","properties":{"url":{"type":"string","description":"Public HTTPS URL"}},"required":["url"],"additionalProperties":False}
    async def execute(self, arguments, *, on_output=None):
        try:
            result=await browser_snapshot(arguments["url"])
        except Exception as exc:
            raise ToolError("BROWSER_FAILED",f"{type(exc).__name__}: {exc}") from exc
        return ToolResult(ok=True,summary="Public webpage snapshot",data=result)

class BrowserSessionTool(BaseTool):
    name = "browser_session"
    description = "Interact with a public website in an isolated headless browser. Click, fill, navigate and inspect; no downloads or private network access. Form submissions may have real effects."
    parameters = {"type":"object","properties":{
        "operation":{"type":"string","enum":["open","snapshot","click","fill","select","check","uncheck","press","navigate","wait","close"]},
        "session_id":{"type":"string"},
        "url":{"type":"string"},
        "selector":{"type":"string"},
        "value":{"type":"string"}
    },"required":["operation"],"additionalProperties":False}
    def __init__(self,sessions):
        self.sessions=sessions
    async def execute(self,arguments,*,on_output=None):
        op=arguments.get("operation")
        try:
            if op=="open":
                data=await self.sessions.open(arguments["url"])
            elif op=="close":
                data=await self.sessions.close(arguments["session_id"])
            elif op=="snapshot":
                data=await self.sessions.snapshot(arguments["session_id"])
            else:
                data=await self.sessions.action(arguments["session_id"],op,selector=arguments.get("selector",""),value=arguments.get("value",""))
        except (KeyError,ValueError,RuntimeError,OSError,ImportError) as exc:
            raise ToolError("BROWSER_SESSION_FAILED",str(exc)) from exc
        return ToolResult(ok=True,summary="Browser "+str(op),data=data)

def browser_tools(sessions=None):
    sessions=sessions or BrowserSessions()
    return [BrowserSnapshotTool(),BrowserSessionTool(sessions)]
