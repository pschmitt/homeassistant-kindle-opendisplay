"""Kindle battery and diagnostic sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)

from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add battery, Wi-Fi and RSSI."""
    async_add_entities(
        (
            KindleBattery(entry.runtime_data, "battery"),
            KindleNetwork(entry.runtime_data, "ssid"),
            KindleNetwork(entry.runtime_data, "bssid"),
            KindleSignal(entry.runtime_data, "signal"),
        )
    )


class KindleBattery(KindleEntity, SensorEntity):
    """Actual capacity from the Kindle battery driver."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        """Return the measured capacity."""
        if state := self.coordinator.data:
            return state.battery

    @property
    def extra_state_attributes(self):
        """Expose the driver charging status."""
        if state := self.coordinator.data:
            return {"charging": state.charging, "status": state.battery_status}


class KindleNetwork(KindleEntity, SensorEntity):
    """Associated network and firmware metadata."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key):
        """Select the associated network field."""
        super().__init__(coordinator, key)
        self.key = key

    @property
    def native_value(self):
        """Return the SSID or BSSID."""
        if state := self.coordinator.data:
            return getattr(state, self.key)

    @property
    def extra_state_attributes(self):
        """Return the hardware and software versions."""
        if self.key == "ssid" and (state := self.coordinator.data):
            return {
                "device_type": state.model,
                "rssi_dbm": state.rssi,
                "kindle_firmware": state.firmware,
                "kindle_build": state.build,
                "kernel_release": state.kernel,
                "alpine_version": state.alpine,
            }


class KindleSignal(KindleEntity, SensorEntity):
    """Wi-Fi signal strength."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    @property
    def native_value(self):
        """Return RSSI in dBm."""
        if state := self.coordinator.data:
            return state.rssi
