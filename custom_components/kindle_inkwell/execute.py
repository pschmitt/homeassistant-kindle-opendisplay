"""Expose opt-in command execution to Home Assistant administrators."""

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api import KindleError
from .const import DOMAIN
from .coordinator import client_for_device


def setup_execute(hass):
    """Register the command action and its response contract."""

    async def execute_command(call):
        client = client_for_device(hass, call.data["device_id"])
        if client is None:
            raise HomeAssistantError("The selected Kindle has no ready BLE connection")
        try:
            return await client.execute(call.data["command"])
        except KindleError as err:
            raise HomeAssistantError(str(err)) from err

    async_register_admin_service(
        hass,
        DOMAIN,
        "execute_command",
        execute_command,
        schema=vol.Schema(
            {vol.Required("device_id"): cv.string, vol.Required("command"): cv.string}
        ),
        supports_response=SupportsResponse.ONLY,
    )
