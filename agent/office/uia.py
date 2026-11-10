"""Conservative Windows Office UI Automation discovery; no implicit clicks."""
from __future__ import annotations
import sys

def list_office_windows() -> dict:
    if sys.platform != "win32":
        return {"available":False,"windows":[],"reason":"UIA requires Windows"}
    try:
        from pywinauto import Desktop
    except ImportError:
        return {"available":False,"windows":[],"reason":"pywinauto not installed"}
    result=[]
    for window in Desktop(backend="uia").windows():
        try:
            title=window.window_text()
            class_name=window.class_name()
            if class_name in {"XLMAIN","OpusApp","PPTFrameClass"} and title:
                result.append({"title":title[:256],"class_name":class_name,"handle":int(window.handle)})
        except Exception:
            continue
    return {"available":True,"windows":result,"read_only":True}
