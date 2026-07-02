"""Events module for VisionAuth.

Exposes the core EventBus and system EventType.
"""

from visionauth.events.event_bus import EventBus, EventType

__all__ = ["EventBus", "EventType"]
