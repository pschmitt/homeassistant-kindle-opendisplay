"""Reboot a Kindle via its authenticated BLE receiver."""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .api import KindleError
from .entity import KindleEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add boot options for a Kindle using BLE."""
    coordinator = entry.runtime_data
    if coordinator.ble:
        async_add_entities(
            (
                KindleRebootButton(coordinator, "reboot_inkwell", stock=False),
                KindleRebootButton(coordinator, "reboot_kindle_os", stock=True),
            )
        )


class KindleRebootButton(KindleEntity, ButtonEntity):
    """Request a restart into the selected Kindle environment."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, key, *, stock):
        """Choose the next operating environment."""
        super().__init__(coordinator, key)
        self._stock = stock

    async def async_press(self):
        """Send one restart request."""
        try:
            await self.coordinator.client.reboot(stock=self._stock)
        except KindleError as err:
            raise HomeAssistantError(
                translation_domain="kindle_inkwell",
                translation_key="control_failed",
            ) from err
