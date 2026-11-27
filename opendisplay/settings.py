"""Device-local OpenDisplay configuration."""

import argparse
import json
import pwd
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

CONFIG_NAME = "config.toml"


@dataclass(frozen=True)
class Settings:
    opendisplay: bool = True
    battery_advertising: bool = True
    stay_awake_on_external_power: bool = True
    cpu_latency_us: int = 0
    commands_enabled: bool = False
    command_user: str = "nobody"
    autostart: bool = True
    controls: bool = True
    sleep_after_seconds: int = 0
    sleep_for_seconds: int = 300


DEFAULT_SETTINGS = Settings()


def load_settings(directory):
    """Load TOML, with legacy files as a fallback for unconverted installations."""
    path = directory / CONFIG_NAME
    try:
        config = tomllib.loads(path.read_text())
    except FileNotFoundError:
        try:
            latency = int((directory / "cpu-latency-us").read_text())
        except (OSError, ValueError):
            latency = 0
        return Settings(
            cpu_latency_us=latency if latency in (0, 50) else 0,
            commands_enabled=(directory / "allow-ble-command").is_file(),
        )

    if config.keys() - {
        "autostart",
        "controls",
        "opendisplay",
        "battery_advertising",
        "stay_awake_on_external_power",
        "cpu_latency_us",
        "commands",
        "sleep_after_seconds",
        "sleep_for_seconds",
    }:
        raise ValueError("Unknown OpenDisplay settings")
    sleep_after = config.get("sleep_after_seconds", 0)
    sleep_for = config.get("sleep_for_seconds", 300)
    if type(sleep_after) is not int or not (
        sleep_after == 0 or 30 <= sleep_after <= 86400
    ):
        raise ValueError("sleep_after_seconds must be 0 or between 30 and 86400")
    if type(sleep_for) is not int or not 15 <= sleep_for <= 86400:
        raise ValueError("sleep_for_seconds must be between 15 and 86400")
    commands = config.get("commands", {})
    if not isinstance(commands, dict) or commands.keys() - {"enabled", "user"}:
        raise ValueError("Expected a commands table with enabled and user settings")
    autostart = config.get("autostart", True)
    controls = config.get("controls", True)
    display = config.get("opendisplay", True)
    battery = config.get("battery_advertising", True)
    awake = config.get("stay_awake_on_external_power", True)
    enabled = commands.get("enabled", False)
    latency = config.get("cpu_latency_us", 0)
    user = commands.get("user", "nobody")
    if any(
        type(value) is not bool
        for value in (autostart, controls, display, battery, enabled, awake)
    ):
        raise ValueError("OpenDisplay feature settings must be true or false")
    if type(latency) is not int or latency not in (0, 50):
        raise ValueError("cpu_latency_us must be 0 or 50")
    if not isinstance(user, str) or not user:
        raise ValueError("commands.user must be a local username")
    if enabled:
        try:
            account = pwd.getpwnam(user)
        except KeyError as err:
            raise ValueError("commands.user does not exist on the Kindle") from err
        if account.pw_uid == 0 or account.pw_gid == 0:
            raise ValueError("BLE commands require a non-root user and group")
    return Settings(
        opendisplay=display,
        battery_advertising=battery,
        stay_awake_on_external_power=awake,
        cpu_latency_us=latency,
        commands_enabled=enabled,
        command_user=user,
        autostart=autostart,
        controls=controls,
        sleep_after_seconds=sleep_after,
        sleep_for_seconds=sleep_for,
    )


def install_settings(directory, latency=None):
    """Migrate old settings, preserving an existing TOML file on upgrades."""
    path = directory / CONFIG_NAME
    current = load_settings(directory)
    if path.exists() and latency is None:
        return
    idle_limit = current.cpu_latency_us if latency is None else latency
    sleep_prefix = (
        "# "
        if (current.sleep_after_seconds, current.sleep_for_seconds) == (0, 300)
        else ""
    )
    text = (
        "# Reload the receiver after editing this file.\n"
        f"autostart = {str(current.autostart).lower()}\n"
        f"controls = {str(current.controls).lower()}\n"
        f"opendisplay = {str(current.opendisplay).lower()}\n"
        f"battery_advertising = {str(current.battery_advertising).lower()}\n"
        f"stay_awake_on_external_power = {str(current.stay_awake_on_external_power).lower()}\n"
        f"cpu_latency_us = {idle_limit}\n"
        f"{sleep_prefix}sleep_after_seconds = {current.sleep_after_seconds}\n"
        f"{sleep_prefix}sleep_for_seconds = {current.sleep_for_seconds}\n\n"
        "[commands]\n"
        f"enabled = {str(current.commands_enabled).lower()}\n"
        f"user = {json.dumps(current.command_user)}\n"
    )
    with NamedTemporaryFile("w", dir=directory, delete=False) as file:
        staged = Path(file.name)
        try:
            file.write(text)
            file.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "feature", choices=("autostart", "opendisplay", "stay_awake_on_external_power")
    )
    args = parser.parse_args()
    try:
        enabled = getattr(load_settings(Path(__file__).resolve().parent), args.feature)
    except (OSError, ValueError) as err:
        print(f"Invalid OpenDisplay configuration: {err}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if enabled else 1)
