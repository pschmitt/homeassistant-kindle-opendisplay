"""Poll Kindle telemetry in one update shared by all entities."""

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    async_register_callback,
    async_track_unavailable,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import utcnow

from .api import KindleBleClient, KindleClient, KindleError, KindleState, read_key
from .const import (
    CONF_BLUETOOTH_ADDRESS,
    CONF_BLUETOOTH_KEY_FILE,
    CONF_SSH_CONFIG,
    DOMAIN,
)

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"


def parse_battery_announcement(data):
    """Decode the unencrypted BTHome fields emitted by this receiver."""
    if len(data) not in (3, 5) or data[:2] != b"\x40\x01" or data[2] > 100:
        return None
    charging = None
    if len(data) == 5:
        if data[3] != 0x16 or data[4] not in (0, 1):
            return None
        charging = bool(data[4])
    return data[2], charging


def client_for_device(hass, device_id):
    """Find the BLE client for a Kindle or its linked OpenDisplay device."""
    device = dr.async_get(hass).async_get(device_id)
    if not device:
        return None
    addresses = {
        address.upper()
        for connection, address in device.connections
        if connection == dr.CONNECTION_BLUETOOTH
    }
    for entry in hass.config_entries.async_entries(DOMAIN):
        address = entry.data.get(CONF_BLUETOOTH_ADDRESS)
        if address and address.upper() in addresses:
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator and coordinator.ble and coordinator.client:
                return coordinator.client
    return None


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
        )
        self.ble = CONF_BLUETOOTH_KEY_FILE in entry.data
        self.client = None
        self.battery_announcement = None
        self.last_battery_broadcast = None
        self.last_telemetry_poll = None
        self.address = address = entry.data[CONF_BLUETOOTH_ADDRESS]
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            connections={(CONNECTION_BLUETOOTH, address)} if address else set(),
            name=entry.title,
            manufacturer="Amazon",
            model=entry.data["model"],
            sw_version=entry.data["firmware"],
        )

    @callback
    def async_listen_for_battery(self, entry):
        """Listen for this Kindle's passive battery readings."""
        if self.ble and self.address:
            entry.async_on_unload(
                async_register_callback(
                    self.hass,
                    self._async_battery_advertisement,
                    {"address": self.address},
                    BluetoothScanningMode.PASSIVE,
                )
            )
            entry.async_on_unload(
                async_track_unavailable(
                    self.hass,
                    self._async_battery_unavailable,
                    self.address,
                    connectable=False,
                )
            )

    @callback
    def _async_battery_advertisement(self, info, _change):
        announcement = parse_battery_announcement(
            info.service_data.get(BTHOME_UUID, b"")
        )
        changed = announcement != self.battery_announcement
        self.battery_announcement = announcement
        if announcement is not None:
            now = utcnow()
            if (
                self.last_battery_broadcast is None
                or now - self.last_battery_broadcast >= timedelta(minutes=1)
            ):
                self.last_battery_broadcast = now
                changed = True
        if changed:
            self.async_update_listeners()

    @callback
    def _async_battery_unavailable(self, _info):
        if self.battery_announcement is not None:
            self.battery_announcement = None
            self.async_update_listeners()

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
            state = await self.client.read()
        except KindleError as err:
            raise UpdateFailed(str(err)) from err
        self.last_telemetry_poll = utcnow()
        return state
