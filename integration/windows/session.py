"""Windows session state, read from the Terminal Services API."""

import ctypes
from ctypes import wintypes

WTS_CURRENT_SERVER_HANDLE = None
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0


def session_locked() -> bool | None:
    """Whether the current Windows session is locked.

    Unlike checking the input desktop, this is True from the moment the lock
    screen appears, not only once the password prompt is shown.

    Returns:
        True if locked, False if unlocked, None if Windows does not report it.
    """
    wtsapi32 = ctypes.WinDLL("wtsapi32")
    buffer = ctypes.POINTER(wintypes.DWORD)()
    size = wintypes.DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTS_SESSION_INFO_EX, ctypes.byref(buffer), ctypes.byref(size)
    ):
        return None
    try:
        # WTSINFOEXW is a DWORD Level and then a union that holds LARGE_INTEGERs, so
        # it starts 8-byte aligned: SessionId, SessionState and SessionFlags are DWORDs 2-4
        level, flags = buffer[0], ctypes.cast(buffer, ctypes.POINTER(wintypes.LONG))[4]
        if level != 1 or flags not in (0, 1):
            return None
        return flags == WTS_SESSIONSTATE_LOCK
    finally:
        wtsapi32.WTSFreeMemory(buffer)
