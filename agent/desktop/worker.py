"""One request per isolated Windows UIA worker. Never print UI exception details."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import json
import os
import re
import sys
import time
import secrets
import traceback

from agent.core.diagnostics import redact_text

SECRET = re.compile(r'password|passwd|token|secret|api.?key|credential|密码|口令|密钥', re.I)
RISK = re.compile(r'delete|remove|publish|deploy|send|submit|purchase|pay|install|uninstall|format|shutdown|close|exit|quit|save|overwrite|restart|reset|删除|支付|发送|发布|提交|安装|确认|关闭|退出|保存|覆盖|重启|重置', re.I)


class DesktopError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def fail(code, message):
    raise DesktopError(code, message)


def initialize():
    global gui, api, security, process, Desktop, user
    import win32gui as gui
    import win32api as api
    import win32security as security
    import win32process as process
    # Must precede pywinauto imports and all coordinate queries.
    user = C.WinDLL('user32', use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
    user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    user.GetDpiForWindow.argtypes = [W.HWND]
    user.GetDpiForWindow.restype = W.UINT
    from pywinauto import Desktop
    user.OpenInputDesktop.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    user.OpenInputDesktop.restype = W.HANDLE
    handle = user.OpenInputDesktop(0, False, 1)
    if not handle:
        fail('DESKTOP_SESSION_UNAVAILABLE', 'Desktop is locked, secure, or unavailable; unlock the current user session')
    user.GetUserObjectInformationW.argtypes = [W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD)]
    name, needed = C.create_unicode_buffer(256), W.DWORD()
    try:
        if not user.GetUserObjectInformationW(handle, 2, name, C.sizeof(name), C.byref(needed)) or name.value.casefold() != 'default':
            fail('DESKTOP_SECURE_DESKTOP', 'Only the current Default desktop is supported; UAC and lock screens are forbidden')
    finally:
        user.CloseDesktop.argtypes = [W.HANDLE]
        user.CloseDesktop(handle)


def process_identity(pid):
    session = W.DWORD()
    kernel = C.WinDLL('kernel32', use_last_error=True)
    if not kernel.ProcessIdToSessionId(pid, C.byref(session)) or session.value == 0:
        fail('DESKTOP_SESSION_DENIED', 'Only the current interactive user session is permitted')
    current_session = W.DWORD()
    kernel.ProcessIdToSessionId(os.getpid(), C.byref(current_session))
    if session.value != current_session.value:
        fail('DESKTOP_SESSION_DENIED', 'Cross-session desktop operations are forbidden')
    handle = api.OpenProcess(0x1000, False, pid)
    try:
        token = security.OpenProcessToken(handle, 8)
        own = security.OpenProcessToken(api.GetCurrentProcess(), 8)
        try:
            if security.GetTokenInformation(token, 1)[0] != security.GetTokenInformation(own, 1)[0]:
                fail('DESKTOP_USER_DENIED', 'The window belongs to another user')
            target_level = security.GetTokenInformation(token, 25)[0]
            own_level = security.GetTokenInformation(own, 25)[0]
            if target_level.GetSubAuthority(target_level.GetSubAuthorityCount()-1) > own_level.GetSubAuthority(own_level.GetSubAuthorityCount()-1):
                fail('DESKTOP_ELEVATION_DENIED', 'Elevated/UAC targets are not supported')
        finally:
            token.Close(); own.Close()
        created = str(process.GetProcessTimes(handle)['CreationTime'])
        return {'pid':pid, 'created':created, 'session':session.value}
    finally:
        handle.Close()


def identity(hwnd):
    if not gui.IsWindow(hwnd) or gui.GetAncestor(hwnd, 2) != hwnd:
        fail('DESKTOP_WINDOW_STALE', 'The top-level window no longer exists')
    pid = process.GetWindowThreadProcessId(hwnd)[1]
    info = process_identity(pid)
    user.GetPropW.argtypes = [W.HWND,W.LPCWSTR]
    user.GetPropW.restype = W.HANDLE
    user.SetPropW.argtypes = [W.HWND,W.LPCWSTR,W.HANDLE]
    key = 'LocalCodingAgent.M3.WindowGeneration.v1'
    generation = user.GetPropW(hwnd,key)
    if not generation:
        generation = secrets.randbits(31) or 1
        if not user.SetPropW(hwnd,key,W.HANDLE(generation)):
            fail('DESKTOP_WINDOW_IDENTITY_DENIED','Cannot bind window generation without bypassing Windows permissions')
    return {**info, 'hwnd':hwnd, 'class':gui.GetClassName(hwnd), 'generation':int(generation)}


def check(binding):
    if not binding or identity(binding['hwnd']) != binding:
        fail('DESKTOP_WINDOW_STALE', 'Window identity changed; enumerate and authorize it again')
    return binding['hwnd']


def root(binding):
    return Desktop(backend='uia').window(handle=check(binding)).wrapper_object()


def geometry(hwnd):
    rect=gui.GetClientRect(hwnd)
    return {'client_origin':list(gui.ClientToScreen(hwnd,(0,0))), 'client_size':[rect[2],rect[3]], 'dpi':user.GetDpiForWindow(hwnd)}


def capture_window(hwnd):
    """Print only this window's client DC in the same physical DPI context.

    Pillow ImageGrab switches to the target's DPI awareness for sizing; that
    mixes logical and physical rectangles for DPI-unaware applications.
    """
    import win32ui
    from PIL import Image
    physical=tuple(geometry(hwnd)['client_size'])
    if min(physical)<=0 or physical[0]*physical[1]>32_000_000:
        fail('DESKTOP_CAPTURE_SIZE','Physical client capture exceeds the supported size')
    user.GetWindowDpiAwarenessContext.argtypes=[W.HWND]
    user.GetWindowDpiAwarenessContext.restype=W.HANDLE
    user.SetThreadDpiAwarenessContext.argtypes=[W.HANDLE]
    user.SetThreadDpiAwarenessContext.restype=W.HANDLE
    previous=user.SetThreadDpiAwarenessContext(user.GetWindowDpiAwarenessContext(hwnd))
    if not previous:
        fail('DESKTOP_CAPTURE_DPI','Cannot establish the target DPI capture context')
    try:
        rect=gui.GetClientRect(hwnd)
        width,height=rect[2],rect[3]
        image=_print_client(hwnd,width,height)
    finally:
        user.SetThreadDpiAwarenessContext(previous)
    # GDI-unaware targets paint logical pixels. Explicitly normalize their native
    # client size to the physical UIA coordinate system before masking, never
    # paint into a larger bitmap and mistake black padding for redaction.
    return image.resize(physical,Image.Resampling.NEAREST) if image.size!=physical else image


def _print_client(hwnd,width,height):
    import win32ui
    from PIL import Image
    if width<=0 or height<=0 or width*height>32_000_000:
        fail('DESKTOP_CAPTURE_SIZE','Client capture is empty or exceeds 32 million pixels')
    handle=gui.GetDC(hwnd)
    source=win32ui.CreateDCFromHandle(handle)
    memory=source.CreateCompatibleDC()
    bitmap=win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(source,width,height)
        memory.SelectObject(bitmap)
        user.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT]
        user.PrintWindow.restype=W.BOOL
        if not user.PrintWindow(hwnd,memory.GetSafeHdc(),3):
            fail('DESKTOP_CAPTURE_UNAVAILABLE','Windows PrintWindow could not capture this client; no screen fallback')
        return Image.frombytes('RGB',(width,height),bitmap.GetBitmapBits(True),'raw','BGRX',0,1)
    finally:
        memory.DeleteDC()
        source.DeleteDC()
        gui.ReleaseDC(hwnd,handle)
        gui.DeleteObject(bitmap.GetHandle())


def sensitive(control):
    info = control.element_info
    return bool(info.element.CurrentIsPassword or SECRET.search(str(info.name) + ' ' + str(info.automation_id)))


def controls(window):
    queue = [(window, 0)]
    result = []
    truncated = False
    while queue and len(result) < 200:
        control, depth = queue.pop(0)
        result.append(control)
        children = control.children()
        if depth < 8:
            remaining = max(0,200-len(result)-len(queue))
            truncated |= len(children)>remaining
            queue.extend((child, depth+1) for child in children[:remaining])
        elif children:
            truncated = True
    return result, bool(queue) or truncated


def describe(control):
    info = control.element_info
    hidden = sensitive(control)
    editable = info.control_type in ('Edit', 'Document')
    rect = control.rectangle()
    return {'name':'[redacted]' if hidden or editable else redact_text(str(info.name))[:200],
            'automation_id':str(info.automation_id)[:160], 'control_type':info.control_type,
            'runtime_id':list(info.runtime_id), 'enabled':bool(control.is_enabled()), 'visible':bool(control.is_visible()),
            'sensitive':hidden, 'bounds':[rect.left, rect.top, rect.right, rect.bottom]}


def find(window, selector):
    if not isinstance(selector, dict) or not selector or set(selector)-{'name','automation_id','control_type','runtime_id'}:
        fail('DESKTOP_SELECTOR_REQUIRED', 'Provide an exact selector from desktop_inspect')
    matches = []
    items, truncated = controls(window)
    if truncated:
        fail('DESKTOP_TREE_LIMIT', 'Control tree is incomplete at the bounded depth/node limit; exact uniqueness cannot be verified')
    for control in items:
        info = control.element_info
        attrs = {'name':str(info.name), 'automation_id':str(info.automation_id), 'control_type':info.control_type, 'runtime_id':list(info.runtime_id)}
        if all(attrs[k] == v for k,v in selector.items()):
            matches.append(control)
    if len(matches) != 1:
        fail('DESKTOP_SELECTOR_AMBIGUOUS' if matches else 'DESKTOP_CONTROL_NOT_FOUND', 'Selector must match exactly one live control; inspect again')
    return matches[0]


def focus(binding, control=None):
    hwnd = check(binding)
    if gui.IsIconic(hwnd):
        gui.ShowWindow(hwnd, 9)
    window = root(binding)
    window.set_focus()
    if control is not None:
        control.set_focus()
    for _ in range(15):
        active=gui.GetForegroundWindow()
        if active and gui.IsWindow(active) and gui.GetAncestor(active,2)==hwnd:
            return
        check(binding)
        time.sleep(.02)
    fail('DESKTOP_FOCUS_FAILED', 'Windows did not grant focus; no input was sent')


def input_batch(events):
    # One SendInput batch contains all down/up events: no held keys across cancellation.
    class Mouse(C.Structure):
        _fields_ = [('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',C.c_size_t)]
    class Keyboard(C.Structure):
        _fields_ = [('wVk',W.WORD),('wScan',W.WORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',C.c_size_t)]
    class Union(C.Union):
        _fields_ = [('mi',Mouse),('ki',Keyboard)]
    class Input(C.Structure):
        _anonymous_ = ('u',)
        _fields_ = [('type',W.DWORD),('u',Union)]
    values = []
    for kind, value, flags in events:
        item = Input(type=kind)
        if kind == 1:
            item.ki = Keyboard(wVk=value, dwFlags=flags)
        else:
            item.mi = Mouse(mouseData=value & 0xffffffff, dwFlags=flags)
        values.append(item)
    batch = (Input*len(values))(*values)
    user.SendInput.argtypes = [W.UINT,C.POINTER(Input),C.c_int]
    if user.SendInput(len(values), batch, C.sizeof(Input)) != len(values):
        fail('DESKTOP_INPUT_DENIED', 'Windows blocked input; no privilege bypass was attempted')


def risk_check(control, arguments):
    if sensitive(control):
        fail('DESKTOP_SENSITIVE_CONTROL', 'Password, token and credential controls cannot be read or operated')
    if (RISK.search(str(control.element_info.name)) or not str(control.element_info.name).strip()) and not arguments.get('confirm_risk'):
        fail('DESKTOP_RISK_APPROVAL_REQUIRED', 'This target is high-risk or unclassified; request confirm_risk=true for fresh user approval')


def execute(request):
    initialize()
    op, a = request['operation'], request['arguments']
    binding = request.get('binding')
    if op == 'desktop_list_windows':
        windows = []
        def visit(hwnd, _):
            if len(windows) >= 200 or not gui.IsWindowVisible(hwnd) or not gui.GetWindowText(hwnd):
                return
            try:
                ident = identity(hwnd)
                if a.get('pid') and ident['pid'] != a['pid']:
                    return
                title=gui.GetWindowText(hwnd)
                windows.append({'identity':ident, 'pid':ident['pid'], 'title':'[redacted title]' if SECRET.search(title) else redact_text(title)[:200], 'bounds':list(gui.GetWindowRect(hwnd)), 'dpi':user.GetDpiForWindow(hwnd)})
            except Exception:
                return
        gui.EnumWindows(visit, None)
        return {'windows':windows}
    hwnd = check(binding)
    window = root(binding)
    if op == 'desktop_inspect':
        items, truncated = controls(window)
        return {'controls':[describe(c) for c in items], 'truncated':truncated, 'coordinate_space':'physical screen pixels', **geometry(hwnd)}
    if op == 'desktop_screenshot':
        from PIL import Image, ImageDraw
        if gui.IsIconic(hwnd):
            fail('DESKTOP_WINDOW_MINIMIZED', 'Restore/focus the window before capturing')
        items, truncated = controls(window)
        if truncated:
            fail('DESKTOP_REDACTION_INCOMPLETE', 'Control tree exceeds the safety bound; screenshot not saved')
        image = capture_window(hwnd)
        left, top, right, bottom = gui.GetWindowRect(hwnd)
        client = geometry(hwnd)
        # Pillow window capture may be client-only. Never guess offsets: that
        # can leave password pixels visible while masking the wrong rectangle.
        if image.size == tuple(client['client_size']):
            left,top=client['client_origin']
        elif image.size != (right-left,bottom-top):
            fail('DESKTOP_CAPTURE_GEOMETRY_UNKNOWN','Capture bounds do not match client/window physical bounds; no image saved')
        scale_x, scale_y = 1,1
        draw = ImageDraw.Draw(image)
        redactions = 0
        for control in items:
            if sensitive(control) or control.element_info.control_type == 'Edit':
                r = control.rectangle()
                box=(max(0,r.left-left-4),max(0,r.top-top-4),min(image.width,r.right-left+4),min(image.height,r.bottom-top+4))
                if box[2]>box[0] and box[3]>box[1]:
                    draw.rectangle(box,fill='black')
                    redactions += 1
        if all(lo == hi for lo,hi in image.getextrema()):
            fail('DESKTOP_CAPTURE_EMPTY', 'Window capture is blank; GPU/protected/minimized content may not support capture')
        origin = [left,top]
        if a.get('scope') == 'screen':
            x, y = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
            w, h = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
            canvas = Image.new('RGB', (w,h), 'black')
            canvas.paste(image, (left-x,top-y))
            image, origin = canvas, [x,y]
        image.save(request['artifact_path'], format='PNG')
        return {'width':image.width,'height':image.height,'origin':origin, **geometry(hwnd), 'pixel_to_screen_scale':[1/scale_x,1/scale_y],'redacted_controls':redactions,'scope':a.get('scope','window'), 'screen_policy':'only authorized window pixels; remaining desktop masked'}
    if op == 'desktop_focus_window':
        focus(binding)
        return {'focused':True}
    if op == 'desktop_wait':
        seconds = a.get('seconds', 5)
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not 0 <= seconds <= 30:
            fail('DESKTOP_INVALID_ARGUMENT', 'Wait seconds must be 0..30')
        deadline, state = time.monotonic()+seconds, a.get('state','exists')
        while True:
            try:
                control = find(root(binding), a.get('selector'))
                matched = {'exists':True,'enabled':control.is_enabled(),'disabled':not control.is_enabled(),'visible':control.is_visible(),'hidden':not control.is_visible(),'name':not sensitive(control) and control.element_info.control_type not in ('Edit','Document') and control.element_info.name == a.get('expected')}.get(state)
            except DesktopError as exc:
                if exc.code != 'DESKTOP_CONTROL_NOT_FOUND':
                    raise
                matched = state == 'hidden'
            if matched:
                return {'matched':True,'state':state}
            if time.monotonic() >= deadline:
                fail('DESKTOP_WAIT_TIMEOUT', 'Requested control state did not occur before the deadline')
            time.sleep(.05)
    if op == 'desktop_click' and a.get('method','uia') == 'coordinate':
        current=geometry(hwnd)
        expected=request.get('expected_geometry')
        if not expected or any(current[k]!=expected[k] for k in ('client_size','dpi')):
            fail('DESKTOP_GEOMETRY_CHANGED','Inspect/capture the window after resize or DPI change before coordinate fallback')
        if not a.get('confirm_risk'):
            fail('DESKTOP_RISK_APPROVAL_REQUIRED', 'Coordinate fallback requires fresh confirm_risk approval')
        x,y = a.get('x'),a.get('y')
        rect = gui.GetClientRect(hwnd)
        if not isinstance(x,int) or not isinstance(y,int) or not 0 <= x < rect[2] or not 0 <= y < rect[3]:
            fail('DESKTOP_COORDINATES_INVALID','Coordinates must be current window client physical pixels')
        focus(binding)
        point = gui.ClientToScreen(hwnd, (x,y))
        if gui.GetAncestor(gui.WindowFromPoint(point),2) != hwnd:
            fail('DESKTOP_WINDOW_OCCLUDED', 'Another window covers the target point; no click sent')
        risk_check(Desktop(backend='uia').from_point(*point), a)
        api.SetCursorPos(point)
        check(binding)
        input_batch([(0,0,2),(0,0,4)])
        return {'method':'coordinate','clicked':True}
    control = find(window, a.get('selector')) if a.get('selector') else window
    if sensitive(control):
        fail('DESKTOP_SENSITIVE_CONTROL','Sensitive controls cannot be operated')
    if not control.is_enabled() or not control.is_visible():
        fail('DESKTOP_CONTROL_UNAVAILABLE','Target must be visible and enabled')
    if op == 'desktop_click':
        risk_check(control,a)
        # No automatic coordinate fallback: the model must request separate consent.
        try:
            control.iface_invoke.Invoke()
        except Exception:
            fail('DESKTOP_UIA_PATTERN_UNAVAILABLE','InvokePattern unavailable; inspect or request coordinate fallback with approval')
        return {'method':'uia_invoke','clicked':True}
    if op == 'desktop_type_text':
        text = a.get('text')
        if not isinstance(text,str) or len(text)>4000 or SECRET.search(text) or re.search(r'\b(?:sk-|ghp_|github_pat_|eyJ)[A-Za-z0-9_-]{12,}',text):
            fail('DESKTOP_SENSITIVE_INPUT','Use ordinary non-secret text only; input was not logged or entered')
        if control.element_info.control_type != 'Edit':
            fail('DESKTOP_EDIT_REQUIRED','Select a non-sensitive editable control by UIA')
        try:
            control.iface_value.SetValue(text)
            verified = control.iface_value.CurrentValue == text
        except Exception:
            fail('DESKTOP_UIA_PATTERN_UNAVAILABLE','ValuePattern unavailable; no blind typing fallback')
        if not verified:
            fail('DESKTOP_VALUE_MISMATCH','The control did not retain the requested ordinary text; no value was logged')
        return {'entered':True,'characters':len(text),'value_verified':True,'input_logged':False}
    if op == 'desktop_keypress':
        keys = a.get('keys','').upper().split('+')
        names = {'CTRL':17,'ALT':18,'SHIFT':16,'TAB':9,'ENTER':13,'ESC':27,'ESCAPE':27,'SPACE':32,'BACKSPACE':8,'DELETE':46,'HOME':36,'END':35,'UP':38,'DOWN':40,'LEFT':37,'RIGHT':39,'PAGEUP':33,'PAGEDOWN':34}
        names.update({chr(k):k for k in range(65,91)})
        names.update({'F'+str(k):111+k for k in range(1,13)})
        if not 1 <= len(keys) <= 4 or any(k not in names for k in keys) or len(set(keys)) != len(keys) or keys[-1] in ('CTRL','ALT','SHIFT') or any(k not in ('CTRL','ALT','SHIFT') for k in keys[:-1]):
            fail('DESKTOP_KEYS_INVALID','Use one named key or modifier chord; no key scripts or held keys')
        if '+'.join(keys) in ('CTRL+ALT+DELETE','CTRL+SHIFT+ESC','CTRL+SHIFT+ESCAPE','ALT+TAB','ALT+ESC'):
            fail('DESKTOP_KEYS_FORBIDDEN','System/session switching shortcuts are outside the authorized window scope')
        if a.get('keys','').upper() not in ('CTRL+A','TAB','SHIFT+TAB','ESC','ESCAPE','UP','DOWN','LEFT','RIGHT','HOME','END','PAGEUP','PAGEDOWN') and not a.get('confirm_risk'):
            fail('DESKTOP_RISK_APPROVAL_REQUIRED','This shortcut requires fresh confirm_risk approval')
        focus(binding, control)
        # Refuse input if the actual focused control is sensitive.
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo
        from pywinauto.controls.uiawrapper import UIAWrapper
        focused = UIAWrapper(UIAElementInfo(IUIA().iuia.GetFocusedElement()))
        if sensitive(focused):
            fail('DESKTOP_SENSITIVE_CONTROL','Focused control is sensitive; no key sent')
        if gui.GetForegroundWindow()!=hwnd:
            fail('DESKTOP_FOCUS_FAILED','Focus changed before input; no key sent')
        input_batch([(1,names[k],0) for k in keys] + [(1,names[k],2) for k in reversed(keys)])
        return {'pressed':a['keys']}
    if op == 'desktop_scroll':
        direction, amount = a.get('direction','down'),a.get('amount',1)
        if direction not in ('up','down','left','right') or isinstance(amount,bool) or not isinstance(amount,int) or not 1 <= amount <= 10:
            fail('DESKTOP_INVALID_ARGUMENT','Invalid scroll direction/amount')
        try:
            pattern = control.iface_scroll
        except Exception:
            pattern = None
        if pattern:
            for _ in range(amount):
                check(binding)
                pattern.Scroll(1 if direction=='left' else 4 if direction=='right' else 2, 1 if direction=='up' else 4 if direction=='down' else 2)
            return {'method':'uia_scroll','scrolled':True}
        if not a.get('confirm_risk'):
            fail('DESKTOP_RISK_APPROVAL_REQUIRED','Wheel fallback requires fresh confirm_risk approval')
        focus(binding,control)
        rect = control.rectangle()
        point = (int((rect.left+rect.right)/2),int((rect.top+rect.bottom)/2))
        if gui.GetAncestor(gui.WindowFromPoint(point),2) != hwnd:
            fail('DESKTOP_WINDOW_OCCLUDED','Scroll target is occluded')
        api.SetCursorPos(point)
        input_batch([(0,120*amount*(1 if direction in ('up','right') else -1),0x1000 if direction in ('left','right') else 0x800)])
        return {'method':'wheel','scrolled':True}
    fail('DESKTOP_UNKNOWN_OPERATION','Unknown desktop operation')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        request = json.loads(sys.stdin.buffer.read(65536))
        result = {'ok':True,'data':execute(request)}
    except DesktopError as exc:
        result = {'ok':False,'code':exc.code,'message':exc.message}
    except Exception as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        number = getattr(exc,'winerror',None) or (exc.args[0] if exc.args and isinstance(exc.args[0],int) else None)
        result = {'ok':False,'code':'DESKTOP_API_FAILED','message':f'Windows/UIA operation failed ({type(exc).__name__}; native_code={number}; {frame.name}:{frame.lineno}); inspect current window state and retry within limits'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
