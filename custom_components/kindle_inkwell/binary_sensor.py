"""Kindle charging state."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add the charging and external power sensors."""
    async_add_entities(
        (
            KindleCharging(entry.runtime_data, "charging"),
            KindlePluggedIn(entry.runtime_data, "plugged_in"),
        )
    )


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


class KindlePluggedIn(KindleEntity, BinarySensorEntity):
    """External power is connected."""

    _attr_device_class = BinarySensorDeviceClass.PLUG

    @property
    def available(self):
        """Stay available on the passive flag; older receivers may lack both."""
        if self.coordinator.power_announcement is not None:
            return True
        return super().available and self.is_on is not None

    @property
    def is_on(self):
        """Prefer the passively announced power state, which survives sleep."""
        if (plugged_in := self.coordinator.power_announcement) is not None:
            return plugged_in
        if state := self.coordinator.data:
            return state.plugged_in
