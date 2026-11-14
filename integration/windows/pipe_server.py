"""Named pipe the sign-in screen component asks whether the owner was verified.

Protocol: the client connects, writes one line ("STATUS") and reads one line
back: "MATCH <user>" when a verification was taken, otherwise "STATE <phase>"
(starting, searching, face, unrecognized, verified or idle) for the sign-in
screen to show. One request per connection.

By default only SYSTEM may open the pipe: LogonUI, which hosts the credential
provider, runs as SYSTEM. FILE_FLAG_FIRST_PIPE_INSTANCE makes creation fail
if another process already owns the name, so nobody can stand in for the
service. The credential provider also checks that the server runs as SYSTEM.
"""

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

logger = logging.getLogger(__name__)

PIPE_NAME = r"\\.\pipe\VisionAuth"
SYSTEM_ONLY_SDDL = "D:P(A;;GA;;;SY)"

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
ERROR_PIPE_CONNECTED = 535
ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_BUSY = 231
SDDL_REVISION_1 = 1
BUFFER_SIZE = 512
GENERIC_READ_WRITE = 0x80000000 | 0x40000000
OPEN_EXISTING = 3


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

_kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
_kernel32.CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES),
]
_kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
_kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
_kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
_kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG),
]


class PipeServer:
    """Answers STATUS requests on the VisionAuth pipe from a background thread."""

    def __init__(
        self,
        handle_request: Callable[[str], str],
        pipe_name: str = PIPE_NAME,
        sddl: str = SYSTEM_ONLY_SDDL,
    ) -> None:
        """Initializes the server.

        Args:
            handle_request: Maps a request line to a response line.
            pipe_name: Full pipe path.
            sddl: Who may connect. Defaults to SYSTEM only.
        """
        self.handle_request = handle_request
        self.pipe_name = pipe_name
        self.sddl = sddl
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, name="VisionAuthPipe", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        # Unblock ConnectNamedPipe; fails harmlessly if the DACL keeps us out
        handle = _kernel32.CreateFileW(self.pipe_name, GENERIC_READ_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if handle != INVALID_HANDLE_VALUE:
            _kernel32.CloseHandle(handle)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _security_attributes(self) -> tuple[SECURITY_ATTRIBUTES, wintypes.LPVOID]:
        descriptor = wintypes.LPVOID()
        if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            self.sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
        return attributes, descriptor

    def _serve(self) -> None:
        attributes, descriptor = self._security_attributes()
        try:
            while not self._stopping.is_set():
                pipe = _kernel32.CreateNamedPipeW(
                    self.pipe_name,
                    PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                    1,
                    BUFFER_SIZE,
                    BUFFER_SIZE,
                    0,
                    ctypes.byref(attributes),
                )
                if pipe == INVALID_HANDLE_VALUE:
                    logger.error("Could not create the pipe (error %d); retrying.", ctypes.get_last_error())
                    self._stopping.wait(2.0)
                    continue
                try:
                    connected = _kernel32.ConnectNamedPipe(pipe, None) or ctypes.get_last_error() == ERROR_PIPE_CONNECTED
                    if connected and not self._stopping.is_set():
                        self._answer(pipe)
                finally:
                    _kernel32.DisconnectNamedPipe(pipe)
                    _kernel32.CloseHandle(pipe)
        finally:
            _kernel32.LocalFree(descriptor)

    def _answer(self, pipe: int) -> None:
        buffer = ctypes.create_string_buffer(BUFFER_SIZE)
        read = wintypes.DWORD()
        if not _kernel32.ReadFile(pipe, buffer, BUFFER_SIZE - 1, ctypes.byref(read), None):
            return
        request = buffer.raw[: read.value].decode("utf-8", errors="replace").strip()
        try:
            response = self.handle_request(request)
        except Exception:
            logger.exception("Pipe request handler failed.")
            response = "NONE"
        data = (response + "\n").encode("utf-8")
        written = wintypes.DWORD()
        _kernel32.WriteFile(pipe, data, len(data), ctypes.byref(written), None)
        _kernel32.FlushFileBuffers(pipe)


def _open(pipe_name: str, timeout: float) -> int | None:
    """Opens the pipe, waiting while the single instance is busy or being recreated."""
    deadline = time.monotonic() + timeout
    while True:
        handle = _kernel32.CreateFileW(pipe_name, GENERIC_READ_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if handle != INVALID_HANDLE_VALUE:
            return handle
        error = ctypes.get_last_error()
        remaining = deadline - time.monotonic()
        if error not in (ERROR_PIPE_BUSY, ERROR_FILE_NOT_FOUND) or remaining <= 0:
            return None
        if error == ERROR_PIPE_BUSY:
            _kernel32.WaitNamedPipeW(pipe_name, max(1, int(remaining * 1000)))
        else:
            time.sleep(0.02)


def request(line: str, pipe_name: str = PIPE_NAME, timeout: float = 1.0) -> str | None:
    """Sends one request line and returns the response, or None if the pipe is unavailable."""
    handle = _open(pipe_name, timeout)
    if handle is None:
        return None
    try:
        data = (line + "\n").encode("utf-8")
        written = wintypes.DWORD()
        if not _kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None):
            return None
        buffer = ctypes.create_string_buffer(BUFFER_SIZE)
        read = wintypes.DWORD()
        if not _kernel32.ReadFile(handle, buffer, BUFFER_SIZE - 1, ctypes.byref(read), None):
            return None
        return buffer.raw[: read.value].decode("utf-8", errors="replace").strip()
    finally:
        _kernel32.CloseHandle(handle)
