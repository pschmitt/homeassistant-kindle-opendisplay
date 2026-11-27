"""Preview the last frame uploaded to the Kindle's panel."""

import io

from homeassistant.components.image import ImageEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from PIL import Image

from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add the screen preview for BLE entries."""
    if entry.runtime_data.ble:
        async_add_entities((KindleScreen(hass, entry.runtime_data, "screen"),))


def _upright(data, orientation):
    """Return a PNG of the frame, turning landscape frames upright."""
    landscape = orientation == "landscape"
    if not landscape and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data
    with Image.open(io.BytesIO(data)) as frame:
        # Landscape frames are stored rotated into the panel's portrait format.
        upright = frame.transpose(Image.Transpose.ROTATE_270) if landscape else frame
        output = io.BytesIO()
        upright.save(output, format="PNG")
    return output.getvalue()


class KindleScreen(KindleEntity, ImageEntity):
    """The frame most recently sent with kindle_inkwell.upload_image."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_content_type = "image/png"

    def __init__(self, hass, coordinator, key):
        KindleEntity.__init__(self, coordinator, key)
        ImageEntity.__init__(self, hass)
        self._shown = None
        self._image = None
        self._sync()

    def _sync(self):
        screen = self.coordinator.screen
        if screen is not None and screen is not self._shown:
            self._shown = screen
            self._image = None
            self._attr_image_last_updated = screen.updated

    @callback
    def _handle_coordinator_update(self):
        self._sync()
        super()._handle_coordinator_update()

    @property
    def available(self):
        """The preview stays available while the Kindle is offline."""
        return self.coordinator.screen is not None

    async def async_image(self):
        screen = self._shown
        if screen is None:
            return None
        if self._image is None:
            image = await self.hass.async_add_executor_job(
                _upright, screen.image, screen.orientation
            )
            if screen is not self._shown:
                return image
            self._image = image
        return self._image
