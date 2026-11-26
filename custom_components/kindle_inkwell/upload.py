"""Serialize native OpenDisplay uploads with Kindle BLE controls."""

import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import client_for_device

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
        client = client_for_device(hass, call.data["device_id"])
        if client is not None:
            async with client.lock:
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
