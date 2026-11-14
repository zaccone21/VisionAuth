"""Runs a Python function as a Windows service, using the SCM API through ctypes.

The service binary is python.exe itself; the Service Control Manager starts
it with the script path, and the script calls run_as_service(), which hands
the process over to the SCM dispatcher. Stop and shutdown requests set the
event passed to the function.
"""

import ctypes
import logging
import threading
from collections.abc import Callable
from ctypes import wintypes

logger = logging.getLogger(__name__)

SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED = 1
SERVICE_START_PENDING = 2
SERVICE_STOP_PENDING = 3
SERVICE_RUNNING = 4
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004
SERVICE_CONTROL_STOP = 1
SERVICE_CONTROL_INTERROGATE = 4
SERVICE_CONTROL_SHUTDOWN = 5
NO_ERROR = 0
ERROR_CALL_NOT_IMPLEMENTED = 120


class SERVICE_STATUS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
    ]


SERVICE_MAIN_FUNCTION = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR))
HANDLER_FUNCTION_EX = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID)


class SERVICE_TABLE_ENTRY(ctypes.Structure):
    _fields_ = [("lpServiceName", wintypes.LPWSTR), ("lpServiceProc", SERVICE_MAIN_FUNCTION)]


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.RegisterServiceCtrlHandlerExW.restype = wintypes.HANDLE
_advapi32.RegisterServiceCtrlHandlerExW.argtypes = [wintypes.LPCWSTR, HANDLER_FUNCTION_EX, wintypes.LPVOID]
_advapi32.SetServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(SERVICE_STATUS)]
_advapi32.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(SERVICE_TABLE_ENTRY)]


def run_as_service(name: str, run: Callable[[threading.Event], None]) -> None:
    """Hands the process to the Service Control Manager and runs `run` as the service.

    Blocks until the service stops. Raises OSError when the process was not
    started by the SCM (e.g. launched from a console).
    """
    stop = threading.Event()
    status = SERVICE_STATUS(SERVICE_WIN32_OWN_PROCESS, SERVICE_START_PENDING, 0, NO_ERROR, 0, 0, 5000)
    state: dict[str, int] = {}

    def report(current_state: int, exit_code: int = NO_ERROR) -> None:
        status.dwCurrentState = current_state
        status.dwWin32ExitCode = exit_code
        status.dwControlsAccepted = (
            0 if current_state == SERVICE_START_PENDING else SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN
        )
        status.dwCheckPoint = 0 if current_state in (SERVICE_RUNNING, SERVICE_STOPPED) else status.dwCheckPoint + 1
        _advapi32.SetServiceStatus(state["handle"], ctypes.byref(status))

    def handler(control: int, event_type: int, event_data: int, context: int) -> int:
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            report(SERVICE_STOP_PENDING)
            stop.set()
            return NO_ERROR
        if control == SERVICE_CONTROL_INTERROGATE:
            return NO_ERROR
        return ERROR_CALL_NOT_IMPLEMENTED

    handler_callback = HANDLER_FUNCTION_EX(handler)

    def service_main(argc: int, argv: ctypes.POINTER(wintypes.LPWSTR)) -> None:
        state["handle"] = _advapi32.RegisterServiceCtrlHandlerExW(name, handler_callback, None)
        if not state["handle"]:
            logger.error("RegisterServiceCtrlHandlerExW failed: %d", ctypes.get_last_error())
            return
        report(SERVICE_RUNNING)
        exit_code = NO_ERROR
        try:
            run(stop)
        except Exception:
            logger.exception("Service function failed.")
            exit_code = 1
        report(SERVICE_STOPPED, exit_code)

    main_callback = SERVICE_MAIN_FUNCTION(service_main)
    table = (SERVICE_TABLE_ENTRY * 2)(SERVICE_TABLE_ENTRY(name, main_callback), SERVICE_TABLE_ENTRY(None, SERVICE_MAIN_FUNCTION()))
    if not _advapi32.StartServiceCtrlDispatcherW(table):
        raise ctypes.WinError(ctypes.get_last_error())
