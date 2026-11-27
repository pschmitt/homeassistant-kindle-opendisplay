"""Serialize native OpenDisplay uploads with Kindle BLE controls."""

import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components import media_source
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import coordinator_for_device
from .select import ORIENTATION, ORIENTATIONS

_LOGGER = logging.getLogger(__name__)
MAX_SCREEN_BYTES = 4 * 1024 * 1024

SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("image"): dict,
        vol.Optional("dither_mode"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


async def _read_media(hass, image):
    """Read a local media item, or return None for remote or oversized media."""
    media_id = image.get("media_content_id")
    if not isinstance(media_id, str) or not media_source.is_media_source_id(media_id):
        return None
    resolved = await media_source.async_resolve_media(hass, media_id, None)
    path = getattr(resolved, "path", None)
    if path is None:
        return None

    def read():
        with Path(path).open("rb") as file:
            data = file.read(MAX_SCREEN_BYTES + 1)
        return data if len(data) <= MAX_SCREEN_BYTES else None

    return await hass.async_add_executor_job(read)


def setup_upload(hass):
    """Register the generic OpenDisplay image action."""

    async def upload_image(call):
        coordinator = coordinator_for_device(hass, call.data["device_id"])
        client = coordinator.client if coordinator else None
        if client is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="upload_connection_unavailable",
            )
        async with client.lock:
            await hass.services.async_call(
                "opendisplay",
                "upload_image",
                dict(call.data),
                blocking=True,
                context=call.context,
            )
        # The preview is best effort; the upload itself already succeeded.
        try:
            image = await _read_media(hass, call.data["image"])
        except (HomeAssistantError, OSError) as err:
            _LOGGER.debug("Cannot keep the uploaded Kindle frame: %s", err)
            return
        if image is not None:
            orientation = coordinator.config_entry.options.get(ORIENTATION)
            coordinator.async_set_screen(
                image, orientation if orientation in ORIENTATIONS else "portrait"
            )

    hass.services.async_register(DOMAIN, "upload_image", upload_image, schema=SCHEMA)
