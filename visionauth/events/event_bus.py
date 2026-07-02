"""EventBus infrastructure module for VisionAuth.

Provides thread-safe decoupled communication between various pipeline stages.
"""

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Supported event types in the VisionAuth system."""

    FACE_DETECTED = "FACE_DETECTED"
    FACE_RECOGNIZED = "FACE_RECOGNIZED"
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILED = "AUTH_FAILED"
    UNLOCK_REQUESTED = "UNLOCK_REQUESTED"


class EventBus:
    """A thread-safe, synchronous EventBus for decoupled communication."""

    def __init__(self) -> None:
        """Initializes the EventBus."""
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def _resolve_event_name(self, event_type: EventType | str) -> str:
        """Helper to resolve EventType or raw string to a string event name."""
        if isinstance(event_type, EventType):
            return event_type.value
        return str(event_type)

    def subscribe(
        self, event_type: EventType | str, handler: Callable[[Any], None]
    ) -> None:
        """Subscribes a callable handler to an event type.

        Args:
            event_type: The event to subscribe to.
            handler: A callable that accepts the event payload.

        Raises:
            ValueError: If the handler is not callable.
        """
        if not callable(handler):
            raise ValueError("Handler must be callable.")

        event_name = self._resolve_event_name(event_type)
        with self._lock:
            if handler not in self._handlers[event_name]:
                self._handlers[event_name].append(handler)
                logger.debug(
                    "Subscribed handler %s to event %s",
                    handler.__name__ if hasattr(handler, "__name__") else str(handler),
                    event_name,
                )

    def unsubscribe(
        self, event_type: EventType | str, handler: Callable[[Any], None]
    ) -> None:
        """Unsubscribes a handler from an event type.

        Args:
            event_type: The event type.
            handler: The registered callable handler.
        """
        event_name = self._resolve_event_name(event_type)
        with self._lock:
            if handler in self._handlers[event_name]:
                self._handlers[event_name].remove(handler)
                logger.debug(
                    "Unsubscribed handler %s from event %s",
                    handler.__name__ if hasattr(handler, "__name__") else str(handler),
                    event_name,
                )
            else:
                logger.warning(
                    "Attempted to unsubscribe non-registered handler from event %s",
                    event_name,
                )

    def emit(self, event_type: EventType | str, payload: Any = None) -> None:
        """Synchronously dispatches the event and its payload to all registered handlers.

        Dispatches are executed outside the lock to prevent potential deadlocks
        from nested calls or slow handlers. Handlers run inside a try-except
        block to ensure a failure in one subscriber does not disrupt others.

        Args:
            event_type: The event type to emit.
            payload: Optional payload associated with the event.
        """
        event_name = self._resolve_event_name(event_type)
        logger.info("Emitting event: %s", event_name)

        # Take a snapshot under lock to remain thread-safe during callback execution
        with self._lock:
            handlers_to_call = list(self._handlers.get(event_name, []))

        for handler in handlers_to_call:
            try:
                handler(payload)
            except Exception as e:
                logger.exception(
                    "Error executing handler for event %s: %s", event_name, e
                )


if __name__ == "__main__":
    # Minimal example usage
    logging.basicConfig(level=logging.INFO)

    bus = EventBus()

    def handle_auth_success(payload: Any) -> None:
        print(f"[Consumer] Auth succeeded for user: {payload.get('user')}")

    # Subscribe
    bus.subscribe(EventType.AUTH_SUCCESS, handle_auth_success)

    # Emit
    bus.emit(EventType.AUTH_SUCCESS, {"user": "Joaquin"})

    # Unsubscribe
    bus.unsubscribe(EventType.AUTH_SUCCESS, handle_auth_success)
