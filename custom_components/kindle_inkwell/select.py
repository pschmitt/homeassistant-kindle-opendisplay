"""Store the dashboard orientation preference in Home Assistant."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory

ORIENTATION = "orientation"
ORIENTATIONS = ("portrait", "landscape")


async def async_setup_entry(hass, entry, async_add_entities):
    """Add a locally stored orientation for the Kindle."""
    async_add_entities((KindleOrientation(entry),))


class KindleOrientation(SelectEntity):
    """A dashboard rendering hint independent of Kindle connectivity."""

    _attr_has_entity_name = True
    _attr_translation_key = ORIENTATION
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry):
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{ORIENTATION}"
        self._attr_device_info = entry.runtime_data.device_info
        self._attr_options = list(ORIENTATIONS)

    @property
    def current_option(self):
        value = self._entry.options.get(ORIENTATION)
        return value if value in ORIENTATIONS else "portrait"

    async def async_select_option(self, option):
        if option == self.current_option:
            return
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, ORIENTATION: option}
        )
        self.async_write_ha_state()
