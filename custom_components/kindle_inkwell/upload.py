"""Serialize native OpenDisplay uploads with Kindle BLE controls."""

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import CONF_BLUETOOTH_ADDRESS, DOMAIN

SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("image"): dict,
        vol.Optional("dither_mode"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


def setup_upload(hass):
    """Register the generic OpenDisplay image action."""

    async def upload_image(call):
        device = dr.async_get(hass).async_get(call.data["device_id"])
        addresses = (
            {
                address.upper()
                for connection, address in device.connections
                if connection == dr.CONNECTION_BLUETOOTH
            }
            if device
            else set()
        )
        for entry in hass.config_entries.async_entries(DOMAIN):
            address = entry.data.get(CONF_BLUETOOTH_ADDRESS)
            if not address or address.upper() not in addresses:
                continue
            coordinator = getattr(entry, "runtime_data", None)
            if coordinator and coordinator.ble and coordinator.client:
                async with coordinator.client.lock:
                    await hass.services.async_call(
                        "opendisplay",
                        "upload_image",
                        dict(call.data),
                        blocking=True,
                        context=call.context,
                    )
                return
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="upload_connection_unavailable",
        )

    hass.services.async_register(DOMAIN, "upload_image", upload_image, schema=SCHEMA)
