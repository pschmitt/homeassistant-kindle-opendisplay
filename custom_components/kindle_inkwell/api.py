"""Client for the Kindle's restricted SSH command."""

import asyncio
from dataclasses import dataclass
import json


class KindleError(Exception):
    """The Kindle could not return a valid response."""


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
