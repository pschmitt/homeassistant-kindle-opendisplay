"""Expose Inkwell Kindle telemetry and frontlight in Home Assistant."""

from homeassistant.const import Platform

from .coordinator import KindleCoordinator
from .dashboard import setup_dashboard

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH)


async def async_setup(hass, config):
    """Register dashboard actions."""
    setup_dashboard(hass)
    return True


async def async_setup_entry(hass, entry):
    """Register entities and start the network probe in the background."""
    coordinator = entry.runtime_data = KindleCoordinator(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), "kindle_inkwell_refresh"
    )
    return True


async def async_unload_entry(hass, entry):
    """Unload the platforms."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
