"""Expose Inkwell Kindle telemetry and controls in Home Assistant."""

from homeassistant.const import Platform

from .coordinator import KindleCoordinator
from .execute import setup_execute
from .upload import setup_upload

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.BUTTON)


async def async_setup(hass, config):
    """Expose the serialized OpenDisplay upload action."""
    setup_upload(hass)
    setup_execute(hass)
    return True


async def async_setup_entry(hass, entry):
    """Register entities and start the network probe in the background."""
    coordinator = entry.runtime_data = KindleCoordinator(hass, entry)
    coordinator.async_listen_for_battery(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), "kindle_inkwell_refresh"
    )
    return True


async def async_unload_entry(hass, entry):
    """Unload the platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
