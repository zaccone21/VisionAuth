"""Tests for the parts of the unlock daemon that do not need Windows sessions."""

import pytest

from integration.windows import unlock_daemon
from integration.windows.unlock_daemon import console_waiting, status_reply
from tests.services.test_unlock_service import SUCCESS, make_service
from visionauth.auth.auth_service import AuthResult


def test_status_reply_greets_the_face_by_name() -> None:
    service, _ = make_service([True], [AuthResult(success=True, reason="success", confidence=0.8, user="José María")])
    service.step()
    reply = status_reply(service)
    assert reply == "MATCH José María"
    reply.encode("utf-8")


def test_status_reply_reports_phase() -> None:
    service, _ = make_service([False], [SUCCESS])
    service.step()
    assert status_reply(service) == "STATE idle"


@pytest.mark.parametrize(
    "user, locked, account, waiting",
    [
        (None, False, "joaqu", True),
        (None, False, None, False),
        ("JOAQU", True, "joaqu", True),
        ("otro", True, "joaqu", False),
        ("joaqu", False, "joaqu", False),
    ],
)
def test_console_waiting(monkeypatch, user, locked, account, waiting) -> None:
    monkeypatch.setattr(unlock_daemon, "console_session_id", lambda: 1)
    monkeypatch.setattr(unlock_daemon, "session_user", lambda session: user)
    monkeypatch.setattr(unlock_daemon, "session_locked", lambda session: locked)
    assert console_waiting(account) is waiting
