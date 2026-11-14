"""Tests for the VisionAuth named pipe, against a real pipe."""

import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Named pipes are Windows only")

EVERYONE_SDDL = "D:P(A;;GA;;;WD)"


def _pipe_name() -> str:
    return rf"\\.\pipe\VisionAuthTest-{uuid.uuid4().hex}"


def _wait_until_listening(name: str) -> None:
    import time

    from integration.windows.pipe_server import request

    for _ in range(100):
        if request("PING", name, timeout=0.05) is not None:
            return
        time.sleep(0.02)
    raise AssertionError("pipe server did not start")


def test_answers_each_request_with_the_handler_response() -> None:
    from integration.windows.pipe_server import PipeServer, request

    name = _pipe_name()
    answers = iter(["MATCH owner", "NONE"])
    server = PipeServer(lambda line: next(answers) if line == "STATUS" else "PONG", pipe_name=name, sddl=EVERYONE_SDDL)
    server.start()
    try:
        _wait_until_listening(name)
        assert request("STATUS", name) == "MATCH owner"
        assert request("STATUS", name) == "NONE"
    finally:
        server.stop()


def test_system_only_pipe_rejects_a_normal_user() -> None:
    from integration.windows.pipe_server import PipeServer, request

    name = _pipe_name()
    server = PipeServer(lambda line: "MATCH owner", pipe_name=name)
    server.start()
    try:
        import time

        time.sleep(0.2)
        assert request("STATUS", name, timeout=0.3) is None
    finally:
        server.stop()


def test_second_server_cannot_take_over_the_name() -> None:
    from integration.windows.pipe_server import PipeServer, request

    name = _pipe_name()
    first = PipeServer(lambda line: "FIRST", pipe_name=name, sddl=EVERYONE_SDDL)
    first.start()
    try:
        _wait_until_listening(name)
        impostor = PipeServer(lambda line: "IMPOSTOR", pipe_name=name, sddl=EVERYONE_SDDL)
        impostor.start()
        try:
            for _ in range(5):
                assert request("STATUS", name) == "FIRST"
        finally:
            impostor._stopping.set()
    finally:
        first.stop()
