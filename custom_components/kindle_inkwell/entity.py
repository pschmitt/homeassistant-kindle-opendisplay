"""Common device and availability for Kindle entities."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import KindleCoordinator


class KindleEntity(CoordinatorEntity[KindleCoordinator]):
    """An entity provided by an Inkwell Kindle."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, key):
        """Set the unique ID, translation key and device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = coordinator.device_info

    @property
    def diagnostics(self):
        """Return the optional extended device readings."""
        if state := self.coordinator.data:
            return state.diagnostics

    @property
    def available(self):
        """An entity is available after a successful poll."""
        return super().available and self.coordinator.data is not None
