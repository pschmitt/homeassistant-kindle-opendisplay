"""Set up authenticated Bluetooth control of a Kindle."""

import re
from pathlib import Path

import voluptuous as vol
from homeassistant import config_entries

from .api import KindleBleClient, KindleError, read_key
from .const import CONF_BLUETOOTH_ADDRESS, CONF_BLUETOOTH_KEY_FILE, DOMAIN


class KindleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Validate a Kindle before creating or updating an entry."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Set up a Kindle over Bluetooth."""
        return await self._async_configure("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        """Move an existing entry to Bluetooth without replacing its entities."""
        return await self._async_configure(
            "reconfigure", user_input, self._get_reconfigure_entry()
        )

    async def _async_configure(self, step, user_input, entry=None):
        defaults = entry.data if entry else {}
        schema = vol.Schema(
            {
                vol.Required(CONF_BLUETOOTH_ADDRESS): str,
                vol.Required(
                    CONF_BLUETOOTH_KEY_FILE, default="/config/.ssh/kindle_ble.key"
                ): str,
            }
        )
        errors = {}
        if user_input is not None:
            address = user_input[CONF_BLUETOOTH_ADDRESS].strip().upper()
            path = Path(user_input[CONF_BLUETOOTH_KEY_FILE].strip())
            if (
                not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address)
                or entry is not None
                and defaults.get(CONF_BLUETOOTH_ADDRESS) not in ("", None, address)
            ):
                errors[CONF_BLUETOOTH_ADDRESS] = "invalid_address"
            else:
                try:
                    key = await self.hass.async_add_executor_job(read_key, path)
                except (OSError, ValueError):
                    errors[CONF_BLUETOOTH_KEY_FILE] = "invalid_key"
                else:
                    try:
                        state = await KindleBleClient(self.hass, address, key).read()
                    except KindleError:
                        errors["base"] = "cannot_connect"
                    else:
                        data = {
                            CONF_BLUETOOTH_ADDRESS: address,
                            CONF_BLUETOOTH_KEY_FILE: str(path),
                            "model": state.model,
                            "firmware": state.firmware,
                        }
                        if entry is not None:
                            return self.async_update_reload_and_abort(entry, data=data)
                        await self.async_set_unique_id(address)
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(title=state.model, data=data)
        return self.async_show_form(
            step_id=step,
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or defaults
            ),
            errors=errors,
        )
