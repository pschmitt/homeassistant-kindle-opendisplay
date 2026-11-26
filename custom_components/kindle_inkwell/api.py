"""Client for the Kindle's restricted SSH command."""

import asyncio
import hmac
import json
from dataclasses import dataclass


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
_OPERATIONS = {"frontlight": (1, 2), "wifi": (3, 4), "ssh": (5, 6)}


class KindleBleClient:
    """Send authenticated requests through a Home Assistant Bluetooth adapter."""

    def __init__(self, hass, address, key):
        """Hold the device identity and already loaded key."""
        self.hass = hass
        self.address = address
        self.key = key
        self.lock = asyncio.Lock()

    async def read(self):
        """Return current telemetry."""
        async with self.lock:
            return await self._exchange(0)

    async def set_enabled(self, control, enabled):
        """Apply a switch change and return authenticated telemetry."""
        opcode = _OPERATIONS[control][enabled]
        async with self.lock:
            try:
                return await self._exchange(opcode)
            except KindleLinkError:
                await asyncio.sleep(2)
                return await self._exchange(opcode)

    async def _exchange(self, opcode):
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
        try:
            async with asyncio.timeout(50):
                for attempt in range(2):
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        device,
                        "Kindle Inkwell",
                        max_attempts=1,
                        use_services_cache=attempt == 0,
                    )
                    if client.services.get_characteristic(_CHALLENGE) is not None:
                        break
                    try:
                        if attempt == 1:
                            raise KindleError("Kindle control service is missing")
                        await client.clear_cache()
                    finally:
                        await client.disconnect()
                try:
                    nonce = await client.read_gatt_char(_CHALLENGE)
                    if len(nonce) != 16:
                        raise KindleError("Invalid Kindle challenge")
                    operation = bytes((opcode | 0x80,))
                    header = b"kindle-control-v1\0" + nonce + operation
                    proof = hmac.digest(self.key, b"request\0" + header, "sha256")[:16]
                    await client.write_gatt_char(
                        _REQUEST, operation + proof, response=True
                    )
                    raw = await client.read_gatt_char(_RESPONSE)
                finally:
                    await client.disconnect()
        except (BleakError, TimeoutError, OSError) as err:
            raise KindleLinkError("Kindle BLE connection or command failed") from err

        cipher = AESGCM(
            hmac.digest(self.key, b"kindle-control response encryption", "sha256")
        )
        try:
            data = cipher.decrypt(nonce[:12], raw, header)
        except InvalidTag as err:
            raise KindleError("Kindle BLE response authentication failed") from err
        try:
            fields = json.loads(data)
            if not isinstance(fields, list) or len(fields) != 15:
                raise ValueError
            return KindleState(*fields)
        except (ValueError, TypeError) as err:
            raise KindleError(
                "Kindle reported a failed command or invalid telemetry"
            ) from err
