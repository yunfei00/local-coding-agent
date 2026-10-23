"""Read-only, explicit-title validation of the real product Windows capture path."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Direct script execution starts sys.path in scripts/validation, including in a
# clean uv environment where this dependency-only project is not installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.desktop.runtime import DesktopRuntime


async def run(args):
    runtime=DesktopRuntime(); owner='explicit-window-capture-validation'
    try:
        listed=await runtime.execute('desktop_list_windows',{},owner=owner,authorized=args.authorized)
        windows=[w for w in listed.data['windows'] if w['title']==args.title]
        if len(windows)!=1: raise ValueError('Exact authorized window must be unique; no capture performed')
        if args.focus:
            await runtime.execute('desktop_focus_window',{'window_id':windows[0]['window_id']},owner=owner,authorized=args.authorized)
        result=await runtime.execute('desktop_screenshot',{'window_id':windows[0]['window_id']},owner=owner,authorized=args.authorized)
        report={'real_windows_api':True,'upload':False,**result.data}
        target=Path('validation-reports')/args.report
        if target.name!=args.report or target.suffix!='.json': raise ValueError('Use a JSON report filename')
        target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        await runtime.close_owner(owner)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--title',required=True)
    parser.add_argument('--authorized',action='store_true',help='Explicit consent to capture only the named window, locally')
    parser.add_argument('--focus',action='store_true',help='Explicitly focus this authorized window before capture')
    parser.add_argument('--report',default='controlled-window-capture.json')
    asyncio.run(run(parser.parse_args()))
