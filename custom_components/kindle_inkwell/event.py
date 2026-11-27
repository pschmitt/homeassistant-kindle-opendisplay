"""Expose confirmed timed-suspend resumes."""

from datetime import UTC, datetime
from typing import ClassVar

from homeassistant.components.event import EventEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add the power event for BLE entries."""
    if entry.runtime_data.ble:
        async_add_entities((KindleWake(entry.runtime_data, "wake"),))


class KindleWake(KindleEntity, EventEntity):
    """Emit a wake after the scheduler reports a new completed suspend."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_event_types: ClassVar[list[str]] = ["wake"]

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self._observed = False
        self._last_wake = None
        self._observe()

    def _observe(self):
        data = self.diagnostics
        if data is None:
            return
        wake = data.wake
        if self._observed and wake is not None and wake != self._last_wake:
            self._trigger_event(
                "wake",
                {
                    "woke_at": datetime.fromtimestamp(wake[0], UTC).isoformat(),
                    "suspended_seconds": wake[1],
                },
            )
        self._observed = True
        self._last_wake = wake

    @callback
    def _handle_coordinator_update(self):
        self._observe()
        super()._handle_coordinator_update()

    @property
    def available(self):
        return super().available and self.diagnostics is not None
