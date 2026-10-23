"""Read-only Windows 10/11 session readiness; never unlock or switch desktops."""
import sys

from agent.tools.base import ToolError


def require_interactive_session():
    if sys.platform != 'win32':
        raise ToolError('DESKTOP_UNSUPPORTED', 'Windows desktop required')
    import ctypes as C
    from ctypes import wintypes as W

    # WTSINFOEXW.Level (DWORD), 4-byte padding for its 8-byte-aligned
    # WTSINFOEX_LEVEL union, then the first three WTSINFOEX_LEVEL1_W fields.
    class Prefix(C.Structure):
        _fields_ = [('level', W.DWORD), ('padding', W.DWORD),
                    ('session_id', W.DWORD), ('state', C.c_int), ('flags', W.LONG)]

    api = C.WinDLL('wtsapi32', use_last_error=True)
    api.WTSQuerySessionInformationW.argtypes = [W.HANDLE, W.DWORD, C.c_int, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)]
    api.WTSQuerySessionInformationW.restype = W.BOOL
    api.WTSFreeMemory.argtypes = [C.c_void_p]
    buffer, size = C.c_void_p(), W.DWORD()
    if not api.WTSQuerySessionInformationW(None, 0xffffffff, 25, C.byref(buffer), C.byref(size)):
        raise ToolError('DESKTOP_SESSION_UNAVAILABLE', 'Cannot verify current interactive session')
    try:
        if size.value < C.sizeof(Prefix):
            raise ToolError('DESKTOP_SESSION_UNAVAILABLE', 'Session state unavailable')
        info = C.cast(buffer, C.POINTER(Prefix)).contents
        if info.level != 1 or info.state != 0 or info.flags not in (0, 1):
            raise ToolError('DESKTOP_SESSION_UNAVAILABLE', 'Current session is not interactive')
        if info.flags == 0:
            raise ToolError('DESKTOP_SESSION_LOCKED', 'Windows session is locked; desktop input stopped')
    finally:
        api.WTSFreeMemory(buffer)
