"""Unit tests for the EventBus implementation."""

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from visionauth.events.event_bus import EventBus, EventType


def test_subscribe_and_emit() -> None:
    """Tests basic subscription and event emission."""
    bus = EventBus()
    handler = MagicMock()

    bus.subscribe(EventType.FACE_DETECTED, handler)
    bus.emit(EventType.FACE_DETECTED, {"x": 10, "y": 20})

    handler.assert_called_once_with({"x": 10, "y": 20})


def test_emit_string_event() -> None:
    """Tests subscribing and emitting using string values."""
    bus = EventBus()
    handler = MagicMock()

    bus.subscribe("AUTH_SUCCESS", handler)
    bus.emit(EventType.AUTH_SUCCESS, "user_ok")

    handler.assert_called_once_with("user_ok")


def test_unsubscribe() -> None:
    """Tests that unsubscribed handlers are no longer called."""
    bus = EventBus()
    handler = MagicMock()

    bus.subscribe(EventType.AUTH_FAILED, handler)
    bus.unsubscribe(EventType.AUTH_FAILED, handler)
    bus.emit(EventType.AUTH_FAILED, "failed_reason")

    handler.assert_not_called()


def test_unsubscribe_non_registered() -> None:
    """Tests unsubscribing a handler that is not registered does not crash."""
    bus = EventBus()
    handler = MagicMock()

    # Should log warning but not raise error
    bus.unsubscribe(EventType.AUTH_FAILED, handler)


def test_multiple_subscribers() -> None:
    """Tests multiple handlers subscribing to the same event."""
    bus = EventBus()
    handler1 = MagicMock()
    handler2 = MagicMock()

    bus.subscribe(EventType.UNLOCK_REQUESTED, handler1)
    bus.subscribe(EventType.UNLOCK_REQUESTED, handler2)
    bus.emit(EventType.UNLOCK_REQUESTED, True)

    handler1.assert_called_once_with(True)
    handler2.assert_called_once_with(True)


def test_handler_exception_isolation() -> None:
    """Tests that a crashing handler does not prevent other handlers from executing."""
    bus = EventBus()

    def bad_handler(payload: Any) -> None:
        raise RuntimeError("Something went wrong!")

    good_handler = MagicMock()

    bus.subscribe(EventType.AUTH_SUCCESS, bad_handler)
    bus.subscribe(EventType.AUTH_SUCCESS, good_handler)

    # This should log an exception but execute good_handler successfully
    bus.emit(EventType.AUTH_SUCCESS, "test_payload")

    good_handler.assert_called_once_with("test_payload")


def test_subscribe_non_callable() -> None:
    """Tests that subscribing a non-callable raises ValueError."""
    bus = EventBus()
    with pytest.raises(ValueError, match="Handler must be callable"):
        bus.subscribe(EventType.FACE_DETECTED, "not_a_callable")  # type: ignore


def test_thread_safety_stress() -> None:
    """Stress test for basic thread-safety in subscriptions and emissions."""
    bus = EventBus()
    event_type = EventType.FACE_RECOGNIZED

    results: list[int] = []

    def producer() -> None:
        for i in range(100):
            bus.emit(event_type, i)
            time.sleep(0.001)

    def consumer(payload: int) -> None:
        results.append(payload)

    # Spawn thread to subscribe
    bus.subscribe(event_type, consumer)

    thread_p = threading.Thread(target=producer)
    thread_p.start()

    # Do some concurrent subscription changes from main thread
    for _ in range(50):

        def dummy(x: Any) -> None:
            pass

        bus.subscribe(event_type, dummy)
        bus.unsubscribe(event_type, dummy)
        time.sleep(0.002)

    thread_p.join()

    assert len(results) == 100
