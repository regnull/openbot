"""Stopping everything a run_shell command started, on Windows.

Windows has no process groups to signal, and ``taskkill /T`` is not enough under Git Bash: MSYS starts
a background job (``sleep 5 &``) by fork + exec, the forked process exits once the program runs, and
the program's parent pid then names a dead process, so the tree walk never reaches it. A job object
holds every descendant however it was started, and terminating the job ends them all.
"""
import ctypes
import functools
from ctypes import wintypes

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class WindowsJob:
    """A job object holding one process and, from then on, everything it starts."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    @classmethod
    def attach(cls, pid: int) -> "WindowsJob | None":
        """Put the process in a new job, or return None if Windows refuses (then fall back to taskkill).

        Children the process starts before this call are not in the job. It runs right after the spawn,
        in practice before Git Bash's launcher has started the actual shell.
        """
        k32 = _kernel32()
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        proc = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        ok = bool(proc) and bool(k32.AssignProcessToJobObject(job, proc))
        if proc:
            k32.CloseHandle(proc)
        if not ok:
            k32.CloseHandle(job)
            return None
        return cls(job)

    def terminate(self) -> None:
        _kernel32().TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Drop the handle. Without KILL_ON_JOB_CLOSE this leaves anything still running alone, like a
        background process outliving its shell on macOS and Linux."""
        _kernel32().CloseHandle(self._handle)


@functools.cache
def _kernel32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    return k32
