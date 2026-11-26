"""Kindle charging state."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add the charging sensor."""
    async_add_entities((KindleCharging(entry.runtime_data, "charging"),))


class KindleCharging(KindleEntity, BinarySensorEntity):
    """The battery is charging."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self):
        """Return the driver charging state."""
        if state := self.coordinator.data:
            return state.charging
