"""Client for the Kindle's restricted SSH command."""

import asyncio
import base64
import hmac
import json
import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)


def read_key(path):
    """Load a dedicated 32-byte key without exposing it in Home Assistant."""
    if not path.is_absolute():
        raise ValueError("Key path must be absolute")
    key = bytes.fromhex(path.read_text())
    if len(key) != 32:
        raise ValueError("Expected a 32-byte key")
    return key


class KindleError(Exception):
    """The Kindle could not return a valid response."""


class KindleTelemetryUnsupported(KindleError):
    """The receiver did not accept the extended telemetry request."""


class KindleLinkError(KindleError):
    """A transient Bluetooth connection failure."""


@dataclass(frozen=True)
class KindleState:
    """The latest reported device state."""

    frontlight: bool
    battery: int
    charging: bool
    battery_status: str
    wifi: str
    rssi: int | None
    model: str
    firmware: str | None
    build: str | None
    kernel: str | None
    alpine: str | None
    wifi_enabled: bool | None = None
    ssh_enabled: bool | None = None
    ssid: str | None = None
    bssid: str | None = None
    ip_address: str | None = None
    plugged_in: bool | None = None
    prevent_sleep: bool | None = None


@dataclass(frozen=True)
class KindleClient:
    """Use a dedicated OpenSSH config with a pinned host key."""

    ssh_config: str
    host: str

    async def _command(self, command: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                "ssh",
                "-F",
                self.ssh_config,
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=5",
                "--",
                self.host,
                command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as err:
            raise KindleError("Could not start SSH") from err
        try:
            async with asyncio.timeout(12):
                output, _ = await process.communicate()
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            raise
        if process.returncode != 0:
            raise KindleError(f"Kindle did not accept {command}")
        try:
            return output.decode().strip()
        except UnicodeDecodeError as err:
            raise KindleError("Kindle returned invalid text") from err

    async def read(self) -> KindleState:
        """Read current values without changing the Kindle."""
        try:
            async with asyncio.TaskGroup() as tasks:
                light = tasks.create_task(self._command("status"))
                battery = tasks.create_task(self._command("battery"))
                info = tasks.create_task(self._command("info"))
        except* (KindleError, TimeoutError) as err:
            raise KindleError("Kindle is unreachable or did not respond") from err

        try:
            charge = json.loads(battery.result())
            device = json.loads(info.result())
            capacity = charge["capacity"]
            if (
                light.result() not in {"ON", "OFF"}
                or type(capacity) is not int
                or not 0 <= capacity <= 100
            ):
                raise ValueError("Invalid frontlight or battery status")
            if type(charge["charging"]) is not bool:
                raise ValueError("Invalid charging status")
            return KindleState(
                light.result() == "ON",
                capacity,
                charge["charging"],
                charge["status"],
                device["wifi"],
                device.get("rssi_dbm"),
                device["device_type"],
                device.get("kindle_firmware"),
                device.get("kindle_build"),
                device.get("kernel_release"),
                device.get("alpine_version"),
                ip_address=device.get("ip_address"),
                plugged_in=charge.get("plugged_in"),
            )
        except (ValueError, KeyError, TypeError, AttributeError) as err:
            raise KindleError("Kindle returned invalid telemetry") from err

    async def set_frontlight(self, enabled: bool) -> None:
        """Set the frontlight through the restricted endpoint."""
        try:
            await self._command("on" if enabled else "off")
        except TimeoutError as err:
            raise KindleError("Kindle did not respond") from err


_CHALLENGE = "884cc761-ea3a-4b7b-a8bd-114c4e5342ae"
_REQUEST = "884cc762-ea3a-4b7b-a8bd-114c4e5342ae"
_RESPONSE = "884cc763-ea3a-4b7b-a8bd-114c4e5342ae"
_OPERATIONS = {
    "frontlight": (1, 2),
    "wifi": (3, 4),
    "ssh": (5, 6),
    "prevent_sleep": (10, 11),
}
_TELEMETRY_FIELDS = {0xF0: 18, 0xE0: 17, 0xC0: 16, 0x80: 15}


class KindleBleClient:
    """Send authenticated requests through a Home Assistant Bluetooth adapter."""

    def __init__(self, hass, address, key):
        """Hold the device identity and already loaded key."""
        self.hass = hass
        self.address = address
        self.key = key
        self.lock = asyncio.Lock()
        self._telemetry_flags = None

    async def read(self):
        """Negotiate the latest supported telemetry layout once."""
        async with self.lock:
            if self._telemetry_flags is not None:
                return await self._exchange(0, flags=self._telemetry_flags)
            for flags in _TELEMETRY_FIELDS:
                try:
                    state = await self._exchange(0, flags=flags)
                except KindleTelemetryUnsupported:
                    continue
                self._telemetry_flags = flags
                return state
            raise KindleTelemetryUnsupported(
                "The Kindle reported no supported telemetry"
            )

    async def set_enabled(self, control, enabled):
        """Apply a switch change and return authenticated telemetry."""
        opcode = _OPERATIONS[control][enabled]
        async with self.lock:
            flags = self._telemetry_flags or 0x80
            if control == "prevent_sleep" and flags != 0xF0:
                raise KindleTelemetryUnsupported("The receiver has no sleep override")
            field = {"wifi": "wifi_enabled", "ssh": "ssh_enabled"}.get(
                control, control
            )
            for attempt in range(2):
                try:
                    state = await self._exchange(opcode, flags=flags)
                except KindleLinkError as err:
                    await asyncio.sleep(2)
                    try:
                        state = await self._exchange(0, flags=flags)
                    except KindleLinkError:
                        if attempt == 1:
                            raise err
                        continue
                    if getattr(state, field) is not enabled and attempt == 0:
                        continue
                if getattr(state, field) is not enabled:
                    raise KindleError("Kindle telemetry did not confirm the switch state")
                return state

    async def reboot(self, *, stock):
        """Request a single reboot and await authenticated acknowledgement."""
        async with self.lock:
            await self._exchange(8 if stock else 7)

    async def execute(self, command):
        """Run an opt-in command without automatic retries."""
        payload = command.encode()
        if not 1 <= len(payload) <= 160 or not command.strip() or "\0" in command:
            raise KindleError("Command must be 1 to 160 UTF-8 bytes")
        async with self.lock:
            return await self._exchange(9, command=payload)

    async def _exchange(self, opcode, *, flags=0x80, command=None):
        from bleak.exc import BleakError
        from bleak_retry_connector import (
            BleakClientWithServiceCache,
            establish_connection,
        )
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from homeassistant.components.bluetooth import async_ble_device_from_address

        device = async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise KindleLinkError("No active Bluetooth connection path to the Kindle")
        client = None
        stage = "connect"
        try:
            async with asyncio.timeout(50):
                for attempt in range(2):
                    stage = "connect"
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        device,
                        "Kindle Inkwell",
                        max_attempts=1,
                        use_services_cache=attempt == 0,
                    )
                    stage = "read challenge"
                    try:
                        if client.services.get_characteristic(_CHALLENGE) is None:
                            raise KindleError("Kindle control service is missing")
                        nonce = await client.read_gatt_char(_CHALLENGE)
                        if len(nonce) != 16:
                            raise KindleError("Invalid Kindle challenge")
                    except (BleakError, KindleError):
                        if attempt == 1:
                            raise
                        await client.clear_cache()
                        await self._disconnect(client)
                        client = None
                    else:
                        break
                operation = bytes((opcode | flags,))
                header = b"kindle-control-v1\0" + nonce + operation
                if command is None:
                    payload = hmac.digest(
                        self.key, b"request\0" + header, "sha256"
                    )[:16]
                else:
                    request_cipher = AESGCM(
                        hmac.digest(
                            self.key,
                            b"kindle-control command request encryption",
                            "sha256",
                        )
                    )
                    payload = request_cipher.encrypt(nonce[:12], command, header)
                stage = "write request"
                await client.write_gatt_char(
                    _REQUEST, operation + payload, response=True
                )
                stage = "read response"
                raw = await client.read_gatt_char(_RESPONSE)
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.debug(
                "Kindle BLE exchange failed at %s: %s", stage, type(err).__name__
            )
            raise KindleLinkError(f"Kindle BLE exchange failed at {stage}") from err
        finally:
            if client is not None:
                await self._disconnect(client)

        cipher = AESGCM(
            hmac.digest(self.key, b"kindle-control response encryption", "sha256")
        )
        try:
            data = cipher.decrypt(nonce[:12], raw, header)
        except InvalidTag as err:
            raise KindleError("Kindle BLE response authentication failed") from err
        try:
            fields = json.loads(data)
            if command is not None:
                if fields.get("error") == "disabled":
                    raise KindleError("BLE command execution is disabled on the Kindle")
                if "error" in fields:
                    raise KindleError("The Kindle rejected the BLE command")
                for stream in ("stdout", "stderr"):
                    fields[stream] = base64.b64decode(
                        fields[stream], validate=True
                    ).decode("utf-8", errors="replace")
                return fields
            if fields is None and flags != 0x80 and opcode == 0:
                raise KindleTelemetryUnsupported("Extended telemetry is unavailable")
            if not isinstance(fields, list) or len(fields) != _TELEMETRY_FIELDS[flags]:
                raise ValueError
            if any(
                value is not None and type(value) is not bool for value in fields[16:]
            ):
                raise ValueError
            return KindleState(*fields)
        except (ValueError, TypeError, KeyError, AttributeError) as err:
            raise KindleError(
                "Kindle reported a failed command or invalid telemetry"
            ) from err

    @staticmethod
    async def _disconnect(client):
        """Bound connection cleanup independently of the response."""
        from bleak.exc import BleakError

        try:
            async with asyncio.timeout(3):
                await client.disconnect()
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.debug("Kindle BLE disconnect failed: %s", type(err).__name__)
