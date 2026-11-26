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
    def _announced_charging(self):
        if announcement := self.coordinator.battery_announcement:
            return announcement[1]

    @property
    def available(self):
        """Stay available when the Kindle broadcasts but GATT is busy."""
        return self._announced_charging is not None or super().available

    @property
    def is_on(self):
        """Prefer the passively announced charging state."""
        if (charging := self._announced_charging) is not None:
            return charging
        if state := self.coordinator.data:
            return state.charging
