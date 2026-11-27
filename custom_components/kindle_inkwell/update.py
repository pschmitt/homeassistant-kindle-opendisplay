"""Update the Kindle OpenDisplay receiver from a stable GitHub release."""

import asyncio
import re
from datetime import timedelta
from time import monotonic

from aiohttp import ClientError, ClientTimeout
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import KindleError, KindleLinkError, KindleTelemetryUnsupported

SCAN_INTERVAL = timedelta(minutes=1)
_POLL_SECONDS = 900
_RELEASE = "https://api.github.com/repos/pschmitt/homeassistant-kindle-opendisplay/releases/latest"
_ASSET = "kindle-opendisplay-armv7"
_MAX_SIZE = 16 * 1024 * 1024
_STATUS = 0x1C
_START = 0x1D
_CONFIRM = 0x1E


def _version(value):
    """Return a sortable release version with the same grammar as the receiver."""
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,9})(?:\.(?:0|[1-9][0-9]{0,9})){2}", value
    ):
        return None
    parts = tuple(map(int, value.split(".")))
    return parts if all(part <= 0xFFFFFFFF for part in parts) else None


def _release(document):
    """Select a stable release with an authenticated asset digest from GitHub."""
    if document.get("draft") or document.get("prerelease"):
        return None
    tag = document.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or not _version(tag[1:]):
        return None
    assets = document.get("assets", [])
    if not any(asset.get("name") == "SHA256SUMS" for asset in assets):
        return None
    numbers = _version(tag[1:])
    if any(number > 255 for number in numbers):
        return None
    for asset in assets:
        digest = asset.get("digest")
        size = asset.get("size")
        if (
            asset.get("name") == _ASSET
            and type(size) is int
            and 0 < size <= _MAX_SIZE
            and isinstance(digest, str)
            and re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
        ):
            return tag[1:], bytes(numbers)
    return None


async def async_setup_entry(hass, entry, async_add_entities):
    """Add a receiver update entity on BLE-backed Kindles."""
    coordinator = entry.runtime_data
    if coordinator.ble:
        async_add_entities([KindleReceiverUpdate(coordinator)])


class KindleReceiverUpdate(UpdateEntity):
    """Compare the receiver's live version with stable GitHub releases."""

    _attr_has_entity_name = True
    _attr_translation_key = "receiver_update"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_title = "Kindle OpenDisplay"
    _attr_available = False

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_receiver_update"
        self._attr_device_info = coordinator.device_info
        self._candidate = None
        self._installing = False
        self._next_poll = 0.0

    async def async_update(self):
        """Fetch availability and check the actual receiver version."""
        client = self.coordinator.client
        if self._installing or client is None or monotonic() < self._next_poll:
            return
        try:
            state = await client.receiver_update(_STATUS)
        except KindleTelemetryUnsupported:
            self._attr_available = False
            return
        except KindleError:
            return
        installed = state.get("version")
        if state.get("protocol") != 2 or _version(installed) is None:
            self._attr_available = False
            return
        self._next_poll = monotonic() + _POLL_SECONDS
        self._attr_installed_version = installed
        self._attr_available = True
        self._update_device_info(installed)
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(_RELEASE, timeout=ClientTimeout(total=12)) as reply:
                reply.raise_for_status()
                self._candidate = _release(await reply.json())
        except (ClientError, TimeoutError, ValueError, AttributeError, TypeError):
            return
        candidate = self._candidate
        self._attr_supported_features = (
            UpdateEntityFeature.INSTALL if candidate else UpdateEntityFeature(0)
        )
        self._attr_latest_version = max(
            installed, candidate[0] if candidate else installed, key=_version
        )
        self._attr_release_url = (
            f"https://github.com/pschmitt/homeassistant-kindle-opendisplay/releases/tag/v{candidate[0]}"
            if candidate
            else None
        )

    def _update_device_info(self, version):
        """Keep matching device records in sync with the authenticated release."""
        coordinator = self.coordinator
        entry = coordinator.config_entry
        registry = dr.async_get(self.hass)
        identifiers = coordinator.device_info["identifiers"]
        firmware = (
            coordinator.data.firmware if coordinator.data else None
        ) or entry.data.get("firmware")
        software = f"OpenDisplay {version}"
        if firmware:
            software = f"Kindle OS {firmware} · {software}"
        if hasattr(registry, "async_get_device_by_identifier"):
            kindle = registry.async_get_device_by_identifier(
                next(iter(identifiers)), entry.entry_id
            )
        else:
            kindle = registry.async_get_device(identifiers=identifiers)
        if kindle is not None and kindle.sw_version != software:
            registry.async_update_device(kindle.id, sw_version=software)

        address = coordinator.address
        if not address:
            return
        connection = (dr.CONNECTION_BLUETOOTH, address.upper())
        for native_entry in self.hass.config_entries.async_entries("opendisplay"):
            native_address = native_entry.unique_id
            if not native_address or native_address.upper() != address.upper():
                continue
            if hasattr(registry, "async_get_device_by_connection"):
                device = registry.async_get_device_by_connection(
                    connection, native_entry.entry_id
                )
            else:
                device = registry.async_get_device(connections={connection})
            if device is None or native_entry.entry_id not in device.config_entries:
                continue
            if kindle is not None and device.id == kindle.id:
                continue
            hardware = entry.data["model"]
            if (device.manufacturer, device.hw_version, device.sw_version) != (
                "Amazon",
                hardware,
                version,
            ):
                registry.async_update_device(
                    device.id,
                    manufacturer="Amazon",
                    hw_version=hardware,
                    sw_version=version,
                )
            break

    async def async_install(self, version, backup, **kwargs):
        """Stage the update and confirm it after authenticated BLE reconnect."""
        candidate = self._candidate
        client = self.coordinator.client
        if candidate is None or client is None or self._installing:
            raise HomeAssistantError("No Kindle receiver release can be installed")
        target, encoded_version = candidate
        if version not in (None, target) or backup:
            raise HomeAssistantError("Only the latest receiver release is supported")
        self._installing = True
        try:
            try:
                response = await client.receiver_update(_START, encoded_version)
            except KindleLinkError:
                # Keep polling only if the request reached the receiver.
                try:
                    status = await client.receiver_update(_STATUS)
                except KindleLinkError:
                    status = {}
                if not (status.get("busy") is True or status.get("version") == target):
                    raise
                response = None
            if response is not None and response.get("accepted") is not True:
                raise HomeAssistantError(
                    f"Kindle declined the update: {response.get('error', 'unknown error')}"
                )
            async with asyncio.timeout(280):
                while True:
                    await asyncio.sleep(5)
                    try:
                        status = await client.receiver_update(_STATUS)
                        if status.get("failed") is True:
                            raise HomeAssistantError(
                                "Kindle could not verify the release download"
                            )
                        if status.get("version") != target:
                            continue
                        if status.get("trial") is True:
                            reply = await client.receiver_update(
                                _CONFIRM, encoded_version
                            )
                            if reply.get("confirmed") is not True:
                                raise HomeAssistantError(
                                    "Kindle did not confirm the new receiver"
                                )
                        self._attr_installed_version = target
                        self._update_device_info(target)
                        break
                    except KindleLinkError:
                        continue
        except TimeoutError as err:
            raise HomeAssistantError(
                "Kindle did not confirm the new receiver before the update timed out"
            ) from err
        except KindleError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            self._installing = False
            self._next_poll = 0.0
