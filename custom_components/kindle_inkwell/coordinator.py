"""Poll Kindle telemetry in one update shared by all entities."""

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KindleBleClient, KindleClient, KindleError, KindleState, read_key
from .const import (
    CONF_BLUETOOTH_ADDRESS,
    CONF_BLUETOOTH_KEY_FILE,
    CONF_SSH_CONFIG,
    DOMAIN,
)


class KindleCoordinator(DataUpdateCoordinator[KindleState]):
    """The Kindle's connection and last complete state."""

    def __init__(self, hass, entry):
        """Set up polling without opening a connection."""
        super().__init__(
            hass,
            logging.getLogger(__name__),
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
            always_update=False,
        )
        self.ble = CONF_BLUETOOTH_KEY_FILE in entry.data
        self.client = None
        address = entry.data[CONF_BLUETOOTH_ADDRESS]
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections={(CONNECTION_BLUETOOTH, address)} if address else set(),
            name=entry.title,
            manufacturer="Amazon",
            model=entry.data["model"],
            sw_version=entry.data["firmware"],
        )

    async def _async_init_client(self):
        data = self.config_entry.data
        if self.ble:
            try:
                key = await self.hass.async_add_executor_job(
                    read_key, Path(data[CONF_BLUETOOTH_KEY_FILE])
                )
            except (OSError, ValueError) as err:
                raise UpdateFailed("Could not read the Kindle BLE key file") from err
            self.client = KindleBleClient(self.hass, data[CONF_BLUETOOTH_ADDRESS], key)
        else:
            self.client = KindleClient(data[CONF_SSH_CONFIG], data[CONF_HOST])

    async def _async_update_data(self) -> KindleState:
        if self.client is None:
            await self._async_init_client()
        try:
            return await self.client.read()
        except KindleError as err:
            raise UpdateFailed(str(err)) from err
