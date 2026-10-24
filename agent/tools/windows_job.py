"""Own command descendants with a Windows kill-on-close Job Object."""
from __future__ import annotations

import ctypes
import asyncio
from ctypes import wintypes
import os
import time


class WindowsJob:
    def __init__(self, pid: int):
        self.handle = None
        self.last_cleanup = {}
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
            if not process or not kernel.AssignProcessToJobObject(handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle, self.kernel = handle, kernel
        except BaseException:
            kernel.CloseHandle(handle)
            raise
        finally:
            if process:
                kernel.CloseHandle(process)

    def resume(self, pid: int) -> None:
        """Resume a CREATE_SUSPENDED child only after it belongs to this Job."""
        if not self.handle:
            return
        kernel = self.kernel
        class ThreadEntry(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                        ("tid", wintypes.DWORD), ("pid", wintypes.DWORD),
                        ("priority", wintypes.LONG), ("delta", wintypes.LONG), ("flags", wintypes.DWORD)]
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Thread32First.argtypes = kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenThread.restype = wintypes.HANDLE
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD
        snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
        if snapshot in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        resumed = False
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            more = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.pid == pid:
                    thread = kernel.OpenThread(2, False, entry.tid)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        resumed = True
                    finally:
                        kernel.CloseHandle(thread)
                more = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        if not resumed:
            raise OSError("Suspended process has no resumable thread")

    def contains(self, pid: int) -> bool:
        if not self.handle:
            return False
        kernel = self.kernel
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        process = kernel.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            member = wintypes.BOOL()
            return bool(kernel.IsProcessInJob(process, self.handle, ctypes.byref(member)) and member.value)
        finally:
            kernel.CloseHandle(process)

    def terminate(self) -> None:
        if self.handle:
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())

    def _close_owned_windows(self, handles) -> int:
        """Ask only this Job's visible windows to close before forced teardown.

        No titles, controls or input are read. Retained process handles and a
        fresh Job membership check prevent using a reused PID as authority.
        This is part of stopping an owned process, not a general desktop tool.
        """
        user = ctypes.WinDLL('user32',use_last_error=True)
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user.IsWindowVisible.argtypes=[wintypes.HWND]
        user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        owned=dict(handles)
        requested=0
        @callback_type
        def visit(hwnd, _):
            nonlocal requested
            pid=wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            handle=owned.get(pid.value)
            if handle and user.IsWindowVisible(hwnd) and self.kernel.WaitForSingleObject(handle,0)==258:
                member=wintypes.BOOL()
                if self.kernel.IsProcessInJob(handle,self.handle,ctypes.byref(member)) and member.value:
                    requested += bool(user.PostMessageW(hwnd,0x0010,0,0))  # WM_CLOSE
            return True
        user.EnumWindows(visit,0)
        return requested

    def terminate_and_wait_sync(self, timeout=30) -> None:
        """Wait for the owned process handles, not merely a queued kill signal.

        Job termination is asynchronous. Chromium descendants can still hold
        profile files after the original shell has exited. Snapshot only this
        Job, retain kernel handles across termination, and never follow a reused
        PID into an unrelated process.
        """
        if not self.handle:
            return
        kernel = self.kernel
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        capacity = 4096
        buffer = ctypes.create_string_buffer(8 + capacity * ctypes.sizeof(ctypes.c_size_t))
        if not kernel.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), None):
            self.terminate()
            raise ctypes.WinError(ctypes.get_last_error())
        count = ctypes.c_uint32.from_buffer(buffer,4).value
        if count > capacity:
            self.terminate()
            raise OSError('Owned process inventory exceeded bounded cleanup capacity')
        handles = []
        started = time.monotonic()
        try:
            for index in range(count):
                pid = ctypes.c_size_t.from_buffer(buffer,8 + index*ctypes.sizeof(ctypes.c_size_t)).value
                handle = kernel.OpenProcess(0x101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
                if not handle:
                    if ctypes.get_last_error() == 87:  # Already exited and removed.
                        continue
                    raise ctypes.WinError(ctypes.get_last_error())
                member = wintypes.BOOL()
                if not kernel.IsProcessInJob(handle,self.handle,ctypes.byref(member)):
                    kernel.CloseHandle(handle)
                    raise ctypes.WinError(ctypes.get_last_error())
                if member.value:
                    handles.append((pid,handle))
                else:
                    kernel.CloseHandle(handle)  # PID was reused outside this Job.
            graceful_started=time.monotonic()
            close_requests=self._close_owned_windows(handles) if handles else 0
            if close_requests:
                graceful_deadline=time.monotonic()+3
                while any(kernel.WaitForSingleObject(handle,0)==258 for _,handle in handles):
                    if time.monotonic() >= graceful_deadline:
                        break
                    time.sleep(.02)
            graceful={'graceful_window_close_requests':close_requests,
                      'graceful_wait_seconds':round(time.monotonic()-graceful_started,3)}
            self.terminate()
            # All subsequent waits use retained process handles. Release the
            # kill-on-close Job now as well: keeping it until after confirmation
            # leaves the fallback kill action behind the very wait it protects.
            self.close()
            deadline = time.monotonic()+timeout
            while True:
                states = [kernel.WaitForSingleObject(handle,0) for _,handle in handles]
                if any(state not in (0,258) for state in states):
                    raise ctypes.WinError(ctypes.get_last_error())
                if 258 not in states:
                    self.last_cleanup={**graceful,'confirmed_exit':True,'owned_process_count':len(handles),
                                       'elapsed_seconds':round(time.monotonic()-started,3),'timeout_seconds':timeout}
                    break
                if time.monotonic() >= deadline:
                    pending = [pid for (pid,_),state in zip(handles,states) if state==258]
                    self.last_cleanup={**graceful,'confirmed_exit':False,'owned_process_count':len(handles),
                                       'elapsed_seconds':round(time.monotonic()-started,3),'timeout_seconds':timeout,
                                       'pending_owned_pids':pending[:16]}
                    raise TimeoutError(f'Owned process tree did not finish terminating before cleanup deadline; pending owned PIDs={pending[:16]}')
                time.sleep(.02)
        finally:
            for _,handle in handles:
                kernel.CloseHandle(handle)

    async def terminate_and_wait(self, timeout=30) -> None:
        # Cancellation must not close the Job while its confirmation thread is
        # still using retained kernel handles. The wait itself is bounded.
        waiter = asyncio.create_task(asyncio.to_thread(self.terminate_and_wait_sync, timeout))
        cancelled = False
        while not waiter.done():
            try:
                await asyncio.shield(waiter)
            except asyncio.CancelledError:
                cancelled = True
        waiter.result()
        if cancelled:
            raise asyncio.CancelledError

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
