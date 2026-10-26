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


def acknowledge_edit(read_value, verify_focus, expected, *, timeout=3, stage='prefix'):
    """Require two observed values; a slow successful probe is still evidence.

    The outer worker deadline bounds slow UIA RPCs. Never send/replay input here,
    and never include actual text in a failure message.
    """
    deadline=time.monotonic()+timeout
    matched=0
    while True:
        verify_focus()
        observed=read_value()
        matched=matched+1 if observed==expected else 0
        # Check the successful observation before the polling deadline. UIA RPCs
        # can finish late under load; two matching reads must not be reported as
        # a value mismatch just because the second RPC crossed that deadline.
        if matched>=2:
            return
        if time.monotonic()>=deadline:
            fail('DESKTOP_VALUE_MISMATCH',
                f'Edit acknowledgement failed: stage={stage}, expected_length={len(expected)}, '
                f'observed_length={len(observed)}, matching_reads={matched}; no text logged or input replayed')
        time.sleep(.03)


def require_session():
    from agent.desktop.session import require_interactive_session
    try:
        require_interactive_session()
    except Exception as exc:
        fail(getattr(exc, 'code', 'DESKTOP_SESSION_UNAVAILABLE'), 'Windows interactive session is locked or unavailable; no desktop action performed')


def initialize():
    global gui, api, security, process, Desktop, user
    require_session()
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
    require_session()
    if not binding or identity(binding['hwnd']) != binding:
        fail('DESKTOP_WINDOW_STALE', 'Window identity changed; enumerate and authorize it again')
    return binding['hwnd']


def root(binding):
    return Desktop(backend='uia').window(handle=check(binding)).wrapper_object()


def geometry(hwnd):
    rect=gui.GetClientRect(hwnd)
    return {'client_origin':list(gui.ClientToScreen(hwnd,(0,0))), 'client_size':[rect[2],rect[3]], 'dpi':user.GetDpiForWindow(hwnd)}



def _capture_looks_blank(image):
    """Detect near-black compositor placeholders, not just identical RGB pixels."""
    from PIL import ImageStat
    if image.width == 0 or image.height == 0:
        return True
    sample = image.convert("RGB")
    sample.thumbnail((128, 128))
    # Most pixels from a failed PrintWindow capture are nearly black.
    histogram = sample.convert("L").histogram()
    visible = sum(histogram[24:])
    return visible < max(1, int(sample.width * sample.height * 0.005))


def _capture_visible_client_only(hwnd):
    """Conservative foreground-only fallback for modern compositor windows.

    ImageGrab reads *screen* pixels, so it is permitted only when the authorized
    window is foreground, entirely on-screen, and no higher z-order top-level
    window overlaps its client. Otherwise refuse instead of leaking another app.
    """
    from PIL import ImageGrab
    if gui.GetForegroundWindow() != hwnd or gui.IsIconic(hwnd):
        fail('DESKTOP_CAPTURE_FOREGROUND_REQUIRED',
             'Bring the authorized window to the foreground before screenshot retry')
    info = geometry(hwnd)
    x, y = info['client_origin']
    w, h = info['client_size']
    if min(w, h) <= 0:
        fail('DESKTOP_CAPTURE_SIZE', 'Client capture has no visible area')
    desktop = (user.GetSystemMetrics(76), user.GetSystemMetrics(77),
               user.GetSystemMetrics(78), user.GetSystemMetrics(79))
    if x < desktop[0] or y < desktop[1] or x+w > desktop[0]+desktop[2] or y+h > desktop[1]+desktop[3]:
        fail('DESKTOP_CAPTURE_OCCLUDED', 'Authorized client must be fully visible on screen')
    blocked = False
    blocking_class = 'unknown'
    def visit(other, unused):
        nonlocal blocked, blocking_class
        if other == hwnd:
            return False
        if not gui.IsWindowVisible(other) or gui.IsIconic(other):
            return True
        l, t, r, b = gui.GetWindowRect(other)
        if max(l, x) < min(r, x+w) and max(t, y) < min(b, y+h):
            blocked = True
            blocking_class = gui.GetClassName(other) if hasattr(gui,'GetClassName') else 'unknown'
            return False
        return True
    gui.EnumWindows(visit, None)
    if blocked:
        fail('DESKTOP_CAPTURE_OCCLUDED',
             'Another visible window (' + blocking_class + ') overlaps the authorized client; no screen pixels captured')
    image = ImageGrab.grab(bbox=(x, y, x+w, y+h), all_screens=True).convert('RGB')
    if image.size != (w, h) or _capture_looks_blank(image):
        fail('DESKTOP_CAPTURE_EMPTY', 'Screen fallback did not capture usable window pixels')
    return image


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
    image = image.resize(physical,Image.Resampling.NEAREST) if image.size!=physical else image
    if _capture_looks_blank(image):
        # PrintWindow can report success while returning a near-black bitmap
        # for modern Windows Notepad/Chromium composition surfaces.
        image = _capture_visible_client_only(hwnd)
        image.info['capture_method'] = 'foreground_visible_client'
        return image
    image.info['capture_method'] = 'PrintWindow_client'
    return image


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
    queue = [(window, 0, None)]
    result = []
    parents = {}
    truncated = False
    while queue and len(result) < 200:
        control, depth, parent_id = queue.pop(0)
        result.append(control)
        control_id=tuple(control.element_info.runtime_id)
        parents[control_id]=parent_id
        children = control.children()
        if depth < 8:
            remaining = max(0,200-len(result)-len(queue))
            truncated |= len(children)>remaining
            queue.extend((child, depth+1, list(control_id)) for child in children[:remaining])
        elif children:
            truncated = True
    return result, bool(queue) or truncated, parents


def private_editor(control):
    kind = control.element_info.control_type
    if kind == 'Edit':
        return True
    if kind != 'Document':
        return False
    # Chromium's root Document is a page, not an editable field. Masking it
    # hides the entire app. Editable Document controls expose Value/TextEdit,
    # while modern Notepad RichEdit is explicitly protected as well.
    if 'richedit' in str(control.element_info.class_name).lower():
        return True
    try:
        return not bool(control.iface_value.CurrentIsReadOnly)
    except Exception:
        try:
            from comtypes.gen.UIAutomationClient import UIA_IsTextEditPatternAvailablePropertyId
            return bool(control.element_info.element.GetCurrentPropertyValue(UIA_IsTextEditPatternAvailablePropertyId))
        except Exception:
            return False


def describe(control, parent_id=None):
    info = control.element_info
    hidden = sensitive(control)
    editable = info.control_type in ('Edit', 'Document')
    rect = control.rectangle()
    return {'name':'[redacted]' if hidden or editable else redact_text(str(info.name))[:200],
            'automation_id':str(info.automation_id)[:160], 'control_type':info.control_type,
            'runtime_id':list(info.runtime_id), 'parent_runtime_id':parent_id, 'enabled':bool(control.is_enabled()), 'visible':bool(control.is_visible()),
            'sensitive':hidden, 'bounds':[rect.left, rect.top, rect.right, rect.bottom]}


def find(window, selector):
    if not isinstance(selector, dict) or not selector or set(selector)-{'name','automation_id','control_type','runtime_id'}:
        fail('DESKTOP_SELECTOR_REQUIRED', 'Provide an exact selector from desktop_inspect')
    matches = []
    items, truncated, _ = controls(window)
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
    # UIA SetFocus only changes keyboard focus and need not activate a window.
    # Ask Windows normally; never synthesize keys or alter foreground policy.
    try:
        gui.SetForegroundWindow(hwnd)
    except Exception:
        pass  # The authoritative foreground check below remains fail-closed.
    window = root(binding)
    active=gui.GetForegroundWindow()
    # Do not asynchronously focus the Chromium document when its window is
    # already active, just before requesting focus on the exact child Edit.
    if not gui.GetClassName(hwnd).startswith('Chrome_WidgetWin') or not active or gui.GetAncestor(active,2)!=hwnd:
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
    require_session()
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
            item.ki = Keyboard(wVk=0 if flags & 4 else value,
                               wScan=value if flags & 4 else 0, dwFlags=flags)
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
            if len(windows) >= 200 or not gui.IsWindowVisible(hwnd):
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
        items, truncated, parents = controls(window)
        return {'controls':[describe(c,parents.get(tuple(c.element_info.runtime_id))) for c in items], 'truncated':truncated, 'coordinate_space':'physical screen pixels', **geometry(hwnd)}
    if op == 'desktop_screenshot':
        from PIL import Image, ImageDraw
        if gui.IsIconic(hwnd):
            fail('DESKTOP_WINDOW_MINIMIZED', 'Restore/focus the window before capturing')
        items, truncated, _ = controls(window)
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
        # Validate original capture *before* privacy masking. A Notepad editor may
        # cover the entire client and must not be mistaken for a failed capture
        # after its text contents have been concealed.
        if _capture_looks_blank(image):
            fail('DESKTOP_CAPTURE_EMPTY', 'Window capture is blank before redaction')
        redactions = 0
        redacted_area = 0
        for control in items:
            secret = sensitive(control)
            editable = private_editor(control)
            if secret or editable:
                r = control.rectangle()
                box=(max(0,r.left-left-4),max(0,r.top-top-4),min(image.width,r.right-left+4),min(image.height,r.bottom-top+4))
                if box[2]>box[0] and box[3]>box[1]:
                    # Password/secret controls remain black. Ordinary text
                    # editors receive an opaque, light neutral placeholder:
                    # preserving the editor's location but never its contents.
                    draw.rectangle(box,fill='black' if secret else (246,246,246))
                    if not secret and box[2]-box[0] >= 110 and box[3]-box[1] >= 18:
                        draw.text((box[0]+8,box[1]+5), 'EDIT CONTENT REDACTED', fill=(64,64,64))
                    redactions += 1
                    redacted_area += (box[2]-box[0])*(box[3]-box[1])
        origin = [left,top]
        if a.get('scope') == 'screen':
            x, y = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
            w, h = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
            canvas = Image.new('RGB', (w,h), 'black')
            canvas.paste(image, (left-x,top-y))
            image, origin = canvas, [x,y]
        image.save(request['artifact_path'], format='PNG')
        return {'capture_method':image.info.get('capture_method','unknown'),'raw_capture_valid':True,'width':image.width,'height':image.height,'origin':origin, **geometry(hwnd), 'pixel_to_screen_scale':[1/scale_x,1/scale_y],'redacted_controls':redactions,'redacted_area_fraction':min(1.0,round(redacted_area/max(1,image.width*image.height),4)),'redaction_policy':'text editors concealed with light placeholder; sensitive controls black','scope':a.get('scope','window'), 'screen_policy':'only authorized window pixels; remaining desktop masked'}
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
            # A model sometimes selects a Tkinter frame/window rather than
            # the child Entry. Report bounded structural hints, never names,
            # text, selectors or identifiers of unrelated controls.
            actual_type = str(control.element_info.control_type)[:40]
            try:
                candidates, incomplete, _ = controls(window)
                available = sum(1 for candidate in candidates
                    if candidate.element_info.control_type == 'Edit'
                    and not sensitive(candidate)
                    and candidate.is_enabled() and candidate.is_visible())
                hint = ('UIA tree truncated; inspect the window again'
                    if incomplete else
                    f'{available} visible non-sensitive Edit candidate(s) in this window')
            except Exception:
                hint = 'Editable control inventory unavailable'
            fail('DESKTOP_EDIT_REQUIRED',
                f'Selected UIA control type is {actual_type}, not Edit; {hint}. '
                'Inspect again and select an exact Edit runtime_id or automation_id. '
                'No input was entered.')
        try:
            value_pattern=control.iface_value
            if value_pattern.CurrentIsReadOnly:
                fail('DESKTOP_CONTROL_UNAVAILABLE','Selected Edit is read-only; no input sent')
        except DesktopError:
            raise
        except Exception:
            fail('DESKTOP_UIA_PATTERN_UNAVAILABLE','ValuePattern unavailable; no blind typing fallback')
        chromium=gui.GetClassName(hwnd).startswith('Chrome_WidgetWin')
        if chromium:
            # Chromium SetValue can bypass React's input event and be reverted.
            # This is an explicit Edit input path, never a fallback on an
            # unknown control. Verify focus and identity before one balanced
            # Unicode SendInput batch; neither clipboard nor key scripts used.
            from pywinauto.uia_defines import IUIA
            focus(binding,control)
            focused_exact=False
            for _ in range(40):
                check(binding)
                focused=IUIA().iuia.GetFocusedElement()
                if tuple(focused.GetRuntimeId())==tuple(control.element_info.runtime_id):
                    focused_exact=True
                    break
                time.sleep(.02)
            if not focused_exact or sensitive(control):
                fail('DESKTOP_FOCUS_FAILED','Exact Edit did not receive focus; no input sent')
            check(binding)
            if gui.GetForegroundWindow()!=hwnd:
                fail('DESKTOP_FOCUS_FAILED','Window lost focus; no input sent')
            if len(text)*.06+3 > a.get('timeout_seconds',15):
                fail('DESKTOP_INPUT_LIMIT','Ordinary text requires a larger explicit timeout_seconds (maximum 60); no input sent')
            def verify_edit_focus():
                check(binding)
                focused=IUIA().iuia.GetFocusedElement()
                if gui.GetForegroundWindow()!=hwnd or tuple(focused.GetRuntimeId())!=tuple(control.element_info.runtime_id):
                    fail('DESKTOP_FOCUS_FAILED','Edit lost focus while awaiting input acknowledgement; no further characters sent')
            input_batch([(1,17,0),(1,65,0),(1,65,2),(1,17,2),(1,8,0),(1,8,2)])
            acknowledge_edit(lambda:value_pattern.CurrentValue,verify_edit_focus,'',timeout=2,stage='clear')
            # A fixed pacing sleep still drops characters when Chromium/React
            # is busy. Require the actual Edit to acknowledge each prefix before
            # sending the next character. Each character is sent exactly once;
            # no clipboard, held modifiers or replay of partially applied input.
            time.sleep(.05)
            prefix=''
            for character in text:
                check(binding)
                focused=IUIA().iuia.GetFocusedElement()
                if gui.GetForegroundWindow()!=hwnd or tuple(focused.GetRuntimeId())!=tuple(control.element_info.runtime_id):
                    fail('DESKTOP_FOCUS_FAILED','Edit lost focus during input; no further characters sent')
                encoded=character.encode('utf-16-le')
                units=[int.from_bytes(encoded[i:i+2],'little') for i in range(0,len(encoded),2)]
                input_batch([event for unit in units for event in ((1,unit,4),(1,unit,6))])
                prefix+=character
                acknowledge_edit(lambda:value_pattern.CurrentValue,verify_edit_focus,prefix)
        else:
            try:
                value_pattern.SetValue(text)
            except Exception:
                fail('DESKTOP_UIA_PATTERN_UNAVAILABLE','ValuePattern unavailable; no blind typing fallback')
        verified=False
        stable_reads=0
        observed_length=0
        deadline=time.monotonic()+(3 if chromium else .5)
        while time.monotonic()<deadline:
            check(binding)
            retained=value_pattern.CurrentValue
            observed_length=len(retained)
            stable_reads=stable_reads+1 if retained==text else 0
            if stable_reads>=(2 if chromium else 1):
                verified=True
                break
            time.sleep(.05)
        if not verified:
            fail('DESKTOP_VALUE_MISMATCH',f'Edit value did not stabilize: requested {len(text)} characters, observed {observed_length}; no text logged or input replayed')
        return {'entered':True,'characters':len(text),'value_verified':True,'input_logged':False,
                'acknowledgement':'each_prefix' if chromium else 'complete_value',
                'method':'uia_edit_unicode_input' if chromium else 'uia_value'}
    if op == 'desktop_keypress':
        keys = a.get('keys','').upper().split('+')
        names = {'CTRL':17,'ALT':18,'SHIFT':16,'TAB':9,'ENTER':13,'ESC':27,'ESCAPE':27,'SPACE':32,'BACKSPACE':8,'DELETE':46,'HOME':36,'END':35,'UP':38,'DOWN':40,'LEFT':37,'RIGHT':39,'PAGEUP':33,'PAGEDOWN':34}
        names.update({chr(k):k for k in range(65,91)})
        names.update({'F'+str(k):111+k for k in range(1,13)})
        if not 1 <= len(keys) <= 4 or any(k not in names for k in keys) or len(set(keys)) != len(keys) or keys[-1] in ('CTRL','ALT','SHIFT') or any(k not in ('CTRL','ALT','SHIFT') for k in keys[:-1]):
            fail('DESKTOP_KEYS_INVALID','Use one named key or modifier chord; no key scripts or held keys')
        if ('ALT' in keys and keys[-1] in ('TAB','ESC','ESCAPE')) or ('CTRL' in keys and keys[-1] in ('ESC','ESCAPE')) or ('CTRL' in keys and 'ALT' in keys and keys[-1]=='DELETE'):
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
