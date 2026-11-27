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
    """Add battery, Wi-Fi and connection diagnostics."""
    coordinator = entry.runtime_data
    entities = [
        KindleBattery(coordinator, "battery"),
        KindleNetwork(coordinator, "ssid"),
        KindleNetwork(coordinator, "bssid"),
        KindleNetwork(coordinator, "ip_address"),
        KindleSignal(coordinator, "signal"),
        KindleContact(coordinator, "last_telemetry_poll"),
    ]
    if coordinator.ble:
        entities.append(KindleContact(coordinator, "last_battery_broadcast"))
    async_add_entities(entities)


class KindleBattery(KindleEntity, SensorEntity):
    """Actual capacity from the Kindle battery driver."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def available(self):
        """Stay available when the Kindle broadcasts but GATT is busy."""
        return self.coordinator.battery_announcement is not None or super().available

    @property
    def native_value(self):
        """Prefer the passively announced capacity."""
        if announcement := self.coordinator.battery_announcement:
            return announcement[0]
        if state := self.coordinator.data:
            return state.battery

    @property
    def extra_state_attributes(self):
        """Expose the driver charging status."""
        state = self.coordinator.data
        if announcement := self.coordinator.battery_announcement:
            charging = announcement[1]
            attributes = {"source": "bthome"}
            if charging is not None:
                attributes["charging"] = charging
            elif state is not None:
                attributes["charging"] = state.charging
            if state is not None and state.charging == attributes.get("charging"):
                attributes["status"] = state.battery_status
            return attributes
        if state is not None:
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
        """Return the reported network value."""
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


class KindleContact(KindleEntity, SensorEntity):
    """The most recent confirmed contact through one transport."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, key):
        """Select the contact timestamp."""
        super().__init__(coordinator, key)
        self.key = key

    @property
    def available(self):
        """Keep the timestamp visible when the Kindle is unreachable."""
        return self.native_value is not None

    @property
    def native_value(self):
        """Return the most recent observed contact."""
        return getattr(self.coordinator, self.key)
