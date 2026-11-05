"""只读资源门禁；不调整系统配置，不终止其他进程。"""
import ctypes
import sys
from agent.tools.base import ToolError

MIB=1024*1024

def memory_snapshot():
    if sys.platform!='win32':
        return {'supported':False,'method':'Windows GlobalMemoryStatusEx'}
    class Status(ctypes.Structure):
        _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32),*[(name,ctypes.c_uint64) for name in ('total','available','commit_limit','commit_available','virtual_total','virtual_available','extended')]]
    state=Status();state.length=ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise ToolError('DESKTOP_RESOURCE_UNKNOWN','无法读取系统内存；未启动桌面 worker。')
    return {'supported':True,'available_bytes':state.available,'commit_available_bytes':state.commit_available,
            'commit_limit_bytes':state.commit_limit,'method':'Windows GlobalMemoryStatusEx'}

def require_resources(snapshot=None,*,minimum_available=512*MIB,minimum_commit=512*MIB):
    state=memory_snapshot() if snapshot is None else snapshot
    if state.get('supported') and (state['available_bytes']<minimum_available or state['commit_available_bytes']<minimum_commit):
        raise ToolError('BLOCKED_RESOURCE','内存或系统提交余量不足；未启动桌面操作，请在资源恢复后继续。')
    return state
