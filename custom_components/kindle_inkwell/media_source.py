"""Expose generated dashboard images to OpenDisplay without a public URL."""

from homeassistant.components.media_source import MediaImage, MediaSource, Unresolvable

from .const import DOMAIN
from .dashboard import IMAGES


async def async_get_media_source(hass):
    """Return the integration's in-memory image source."""
    return KindleMediaSource(hass)


class KindleMediaSource(MediaSource):
    """Resolve a pending dashboard image."""

    def __init__(self, hass):
        """Hold the application reference."""
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_get_media_image(self, item):
        """Return the exact bytes of an image awaiting upload."""
        if image := self.hass.data.get(IMAGES, {}).get(item.identifier):
            return MediaImage(image, "image/png")
        raise Unresolvable("Kindle dashboard image is no longer available")
