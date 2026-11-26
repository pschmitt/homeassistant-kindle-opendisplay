"""Set up a Kindle with a restricted SSH connection."""

from pathlib import PurePosixPath
import re

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
import voluptuous as vol

from .api import KindleClient, KindleError
from .const import CONF_BLUETOOTH_ADDRESS, CONF_SSH_CONFIG, DOMAIN

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_SSH_CONFIG, default="/config/.ssh/opendisplay_config"): str,
        vol.Optional(CONF_BLUETOOTH_ADDRESS): str,
    }
)


class KindleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Validate the device before creating an entry."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Configure a Kindle."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            ssh_config = user_input[CONF_SSH_CONFIG].strip()
            address = user_input.get(CONF_BLUETOOTH_ADDRESS, "").strip().upper()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", host):
                errors[CONF_HOST] = "invalid_host"
            if not PurePosixPath(ssh_config).is_absolute():
                errors[CONF_SSH_CONFIG] = "invalid_path"
            if address and not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_BLUETOOTH_ADDRESS] = "invalid_address"
            if not errors:
                await self.async_set_unique_id(address or host.lower())
                self._abort_if_unique_id_configured()
                try:
                    state = await KindleClient(ssh_config, host).read()
                except KindleError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=state.model,
                        data={
                            CONF_HOST: host,
                            CONF_SSH_CONFIG: ssh_config,
                            CONF_BLUETOOTH_ADDRESS: address,
                            "model": state.model,
                            "firmware": state.firmware,
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input),
            errors=errors,
        )
