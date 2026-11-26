"""Kindle frontlight control."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .api import KindleError
from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add the frontlight switch."""
    async_add_entities((KindleFrontlight(entry.runtime_data, "frontlight"),))


class KindleFrontlight(KindleEntity, SwitchEntity):
    """A switch for the Kindle's display light."""

    @property
    def is_on(self):
        """Return the measured state."""
        if state := self.coordinator.data:
            return state.frontlight

    async def async_turn_on(self, **kwargs):
        """Restore the previous brightness."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs):
        """Turn off the frontlight."""
        await self._async_set(False)

    async def _async_set(self, enabled):
        try:
            await self.coordinator.client.set_frontlight(enabled)
        except KindleError as err:
            raise HomeAssistantError(
                translation_domain="kindle_inkwell",
                translation_key="frontlight_failed",
            ) from err
        await self.coordinator.async_refresh()
