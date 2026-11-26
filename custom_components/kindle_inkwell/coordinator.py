"""Poll Kindle telemetry in one update shared by all entities."""

from datetime import timedelta
import logging

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KindleClient, KindleError, KindleState
from .const import CONF_BLUETOOTH_ADDRESS, CONF_SSH_CONFIG, DOMAIN


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
        self.client = KindleClient(entry.data[CONF_SSH_CONFIG], entry.data[CONF_HOST])
        address = entry.data[CONF_BLUETOOTH_ADDRESS]
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections={(CONNECTION_BLUETOOTH, address)} if address else set(),
            name=entry.title,
            manufacturer="Amazon",
            model=entry.data["model"],
            sw_version=entry.data["firmware"],
        )

    async def _async_update_data(self) -> KindleState:
        try:
            return await self.client.read()
        except KindleError as err:
            raise UpdateFailed(str(err)) from err
