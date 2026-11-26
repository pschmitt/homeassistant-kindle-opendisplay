"""Authenticated Kindle controls alongside the OpenDisplay GATT service."""

import asyncio
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

from bumble.att import ATT_INSUFFICIENT_AUTHORIZATION_ERROR, ATT_Error
from bumble.core import UUID
from bumble.gatt import Characteristic, CharacteristicValue, Service
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path("/mnt/us/linux")
UUIDS = [UUID(f"884cc76{index}-ea3a-4b7b-a8bd-114c4e5342ae") for index in range(4)]
CONTEXT = b"kindle-control-v1\0"
LOG = logging.getLogger(__name__)


async def command(*args, action=""):
    process = await asyncio.create_subprocess_exec(
        *args,
        env={**os.environ, "SSH_ORIGINAL_COMMAND": action},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(8):
            stdout, _ = await process.communicate()
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        raise
    if process.returncode:
        raise OSError(f"{args[0]} returned {process.returncode}")
    return stdout.decode().strip()


async def telemetry():
    light, battery, info, ssh = await asyncio.gather(
        *(
            command("/opt/opendisplay/frontlight", action=action)
            for action in ("status", "battery", "info")
        ),
        command("/usr/local/bin/ssh-wifi", "status"),
    )
    charge, device = json.loads(battery), json.loads(info)
    wifi_enabled = not (ROOT / "wifi.off").exists()
    return [
        light == "ON",
        charge["capacity"],
        charge["charging"],
        charge["status"],
        device["wifi"] if wifi_enabled else "off",
        device["rssi_dbm"] if wifi_enabled else None,
        device["device_type"],
        device["kindle_firmware"],
        device["kindle_build"],
        device["kernel_release"],
        device["alpine_version"],
        wifi_enabled,
        ssh == "on",
        device.get("ssid") if wifi_enabled else None,
        device.get("bssid") if wifi_enabled else None,
    ]


async def perform(opcode):
    if opcode in (1, 2):
        await command(
            "/opt/opendisplay/frontlight", action="off" if opcode == 1 else "on"
        )
    elif opcode in (3, 4):
        enabled = opcode == 4
        marker = ROOT / "wifi.off"
        result = await command(
            "/sbin/wpa_cli", "-i", "wlan0", "reassociate" if enabled else "disconnect"
        )
        if result != "OK":
            raise OSError("Wi-Fi command was rejected")
        if enabled:
            marker.unlink(missing_ok=True)
        else:
            marker.touch()
    elif opcode in (5, 6):
        enabled = opcode == 6
        marker = ROOT / "ssh-wifi"
        await command("/usr/local/bin/ssh-wifi", "start" if enabled else "stop")
        if enabled:
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
    elif opcode != 0:
        raise ValueError("Unknown Kindle command")
    return await telemetry()


async def reboot(stock):
    """Select the next boot using Inkwell's flags and invoke the host reboot."""
    await asyncio.sleep(5)
    once = ROOT / "STOCK_ONCE"
    previous = once.exists()
    try:
        if stock:
            once.touch()
        else:
            once.unlink(missing_ok=True)
        os.sync()
        await command("/usr/local/bin/kindle", "/sbin/reboot")
    except (OSError, TimeoutError):
        if previous:
            once.touch()
        else:
            once.unlink(missing_ok=True)
        os.sync()
        LOG.exception("Kindle reboot failed")


def add_kindle_service(device, key):
    """Install the optional shared-key service on a Bumble peripheral."""
    if len(key) != 32:
        raise ValueError("Kindle BLE key must be 32 bytes")
    challenges = {}
    responses = {}
    pending_reboot = None
    cipher = AESGCM(hmac.digest(key, b"kindle-control response encryption", "sha256"))

    def challenge(connection):
        nonce = secrets.token_bytes(16)
        challenges[connection] = (nonce, time.monotonic() + 30)
        responses.pop(connection, None)
        return nonce

    async def request(connection, packet):
        nonlocal pending_reboot
        current = challenges.pop(connection, None)
        if current is None or len(packet) != 17:
            raise ATT_Error(ATT_INSUFFICIENT_AUTHORIZATION_ERROR)
        nonce, expires = current
        header = CONTEXT + nonce + packet[:1]
        expected = hmac.digest(key, b"request\0" + header, "sha256")[:16]
        if time.monotonic() > expires or not hmac.compare_digest(expected, packet[1:]):
            raise ATT_Error(ATT_INSUFFICIENT_AUTHORIZATION_ERROR)
        try:
            opcode = packet[0] & 0x7F
            if opcode in (7, 8):
                if not packet[0] & 0x80 or not (ROOT / "BOOT_OWN").is_file():
                    raise ValueError("Inkwell boot selection is unavailable")
                state = await telemetry()
                if pending_reboot is not None and not pending_reboot.done():
                    raise ValueError("Kindle reboot is already scheduled")
                pending_reboot = asyncio.create_task(reboot(stock=opcode == 8))
            else:
                state = await perform(opcode)
        except (OSError, TimeoutError, ValueError, KeyError):
            LOG.exception("Kindle BLE control request failed")
            state = None
        encrypted = bool(packet[0] & 0x80)
        # Legacy clients never receive network identifiers in plaintext.
        if state is not None and not encrypted:
            state = state[:13]
        data = json.dumps(state, separators=(",", ":")).encode()
        if encrypted:
            responses[connection] = cipher.encrypt(nonce[:12], data, header)
        else:
            responses[connection] = (
                hmac.digest(key, b"response\0" + header + data, "sha256")[:16] + data
            )

    def response(connection):
        if connection not in responses:
            raise ATT_Error(ATT_INSUFFICIENT_AUTHORIZATION_ERROR)
        return responses[connection]

    @device.on(device.EVENT_CONNECTION)
    def connected(connection):
        @connection.on(connection.EVENT_DISCONNECTION)
        def disconnected(_reason):
            challenges.pop(connection, None)
            responses.pop(connection, None)

    read, write = Characteristic.Properties.READ, Characteristic.Properties.WRITE
    device.add_services(
        [
            Service(
                UUIDS[0],
                [
                    Characteristic(
                        UUIDS[1],
                        read,
                        Characteristic.READABLE,
                        CharacteristicValue(read=challenge),
                    ),
                    Characteristic(
                        UUIDS[2],
                        write,
                        Characteristic.WRITEABLE,
                        CharacteristicValue(write=request),
                    ),
                    Characteristic(
                        UUIDS[3],
                        read,
                        Characteristic.READABLE,
                        CharacteristicValue(read=response),
                    ),
                ],
            )
        ]
    )
