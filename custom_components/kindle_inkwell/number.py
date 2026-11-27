"""Set the Kindle frontlight level."""

from dataclasses import replace

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.exceptions import HomeAssistantError

from .api import KindleError
from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add a frontlight slider for BLE entries."""
    if entry.runtime_data.ble:
        async_add_entities(
            (KindleFrontlightLevel(entry.runtime_data, "frontlight_level"),)
        )


class KindleFrontlightLevel(KindleEntity, NumberEntity):
    """A percentage from zero (off) to the actual driver maximum."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        data = self.diagnostics
        if data and data.frontlight_maximum and data.frontlight_level is not None:
            return round(100 * data.frontlight_level / data.frontlight_maximum)
        return None

    async def async_set_native_value(self, value):
        state = self.coordinator.data
        data = self.diagnostics
        if state is None or data is None or not data.frontlight_maximum:
            raise HomeAssistantError("Kindle brightness is unavailable")
        level = round(value * data.frontlight_maximum / 100)
        try:
            await self.coordinator.client.set_frontlight_level(level)
        except KindleError as err:
            raise HomeAssistantError("Could not confirm the Kindle brightness") from err
        latest = self.coordinator.data or state
        self.coordinator.async_set_updated_data(
            replace(
                latest,
                frontlight=level > 0,
                diagnostics=replace(latest.diagnostics or data, frontlight_level=level),
            )
        )
