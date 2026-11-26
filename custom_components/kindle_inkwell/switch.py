"""Kindle frontlight, Wi-Fi and Wi-Fi SSH switches."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .api import KindleError
from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add the switches supported by the configured transport."""
    coordinator = entry.runtime_data
    keys = (
        ("frontlight", "wifi_enabled", "ssh_enabled")
        if coordinator.ble
        else ("frontlight",)
    )
    async_add_entities(KindleSwitch(coordinator, key) for key in keys)


class KindleSwitch(KindleEntity, SwitchEntity):
    """A readable and writable Kindle mode."""

    def __init__(self, coordinator, key):
        """Record the control's state field."""
        super().__init__(coordinator, key)
        self.key = key

    @property
    def is_on(self):
        """Return the measured state."""
        if state := self.coordinator.data:
            return getattr(state, self.key)

    async def async_turn_on(self, **kwargs):
        """Enable this control."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs):
        """Disable this control."""
        await self._async_set(False)

    async def _async_set(self, enabled):
        if self.coordinator.client is None:
            raise HomeAssistantError("Kindle connection is not ready")
        try:
            if self.coordinator.ble:
                result = await self.coordinator.client.set_enabled(
                    self.key.removesuffix("_enabled"), enabled
                )
                self.coordinator.async_set_updated_data(result)
            else:
                await self.coordinator.client.set_frontlight(enabled)
                await self.coordinator.async_refresh()
        except KindleError as err:
            raise HomeAssistantError(
                translation_domain="kindle_inkwell",
                translation_key="control_failed",
            ) from err
