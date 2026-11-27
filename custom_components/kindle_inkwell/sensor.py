"""Kindle battery and diagnostic sensors."""

from datetime import UTC, datetime

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

# Voltage and current arrive in micro-units, and charge arrives in µAh.
_DIAGNOSTICS = {
    "cpu_temperature": (SensorDeviceClass.TEMPERATURE, "°C", 1),
    "battery_temperature": (SensorDeviceClass.TEMPERATURE, "°C", 1),
    "battery_voltage": (SensorDeviceClass.VOLTAGE, "V", 1_000_000),
    "battery_current": (SensorDeviceClass.CURRENT, "mA", 1_000),
    "battery_average_current": (SensorDeviceClass.CURRENT, "mA", 1_000),
    "battery_charge": (None, "mAh", 1_000),
    "battery_full_charge": (None, "mAh", 1_000),
    "battery_design_charge": (None, "mAh", 1_000),
    "battery_cycles": (None, None, 1),
    "battery_health": (None, None, 1),
    "uptime": (SensorDeviceClass.DURATION, "s", 1),
    "suspend_time": (SensorDeviceClass.DURATION, "s", 1),
    "last_wake": (SensorDeviceClass.TIMESTAMP, None, 1),
    "last_suspend_duration": (SensorDeviceClass.DURATION, "s", 1),
}


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
        entities.extend(KindleDiagnostic(coordinator, key) for key in _DIAGNOSTICS)
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


class KindleDiagnostic(KindleEntity, SensorEntity):
    """A driver reading or a timestamp from the device's sleep scheduler."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self.key = key
        self._attr_device_class, self._attr_native_unit_of_measurement, self.scale = (
            _DIAGNOSTICS[key]
        )

    @property
    def available(self):
        return super().available and self.diagnostics is not None

    @property
    def native_value(self):
        if (data := self.diagnostics) is None:
            return None
        if self.key in ("last_wake", "last_suspend_duration"):
            if (wake := data.wake) is None:
                return None
            return (
                datetime.fromtimestamp(wake[0], UTC)
                if self.key == "last_wake"
                else wake[1]
            )
        value = getattr(data, self.key)
        return value / self.scale if self.scale != 1 and value is not None else value
