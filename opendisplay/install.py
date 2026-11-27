#!/usr/bin/env python3
"""Install the OpenDisplay receiver after installing Inkwell on a PW4."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from provision import provision
from settings import install_settings

SOURCE = Path(__file__).resolve().parent
TARGET = Path("/opt/opendisplay")
INIT = Path("/sbin/own-init")
BOOT = Path("/mnt/us/linux")
PREVIOUS_HOOK = """# Start OpenDisplay after Inkwell rearms its boot marker.
if [ -d /sys/class/power_supply/bd71827_bat ] && [ -f /opt/opendisplay/autostart ] && [ -x /opt/opendisplay/start ]; then
    (
        sleep 25
        exec /opt/opendisplay/start
    ) </dev/null >>/var/log/opendisplay.log 2>&1 &
    printf '%s\\n' "$!" >/run/opendisplay.pid
fi

"""
HOOK = """# Let OpenDisplay own the panel before starting Inkwell Home.
if [ -d /sys/class/power_supply/bd71827_bat ] && [ -f /opt/opendisplay/autostart ] && [ -x /opt/opendisplay/start ] &&
    python3 /opt/opendisplay/settings.py autostart; then
    if python3 /opt/opendisplay/settings.py opendisplay; then
        (
            sleep 25
            exec /opt/opendisplay/start --boot-exclusive
        ) </dev/null >>/var/log/opendisplay.log 2>&1 &
        receiver_pid=$!
        printf '%s\\n' "$receiver_pid" >/run/opendisplay.pid
        (
            sleep 45
            if { kill -0 "$receiver_pid" 2>/dev/null && [ -d /run/opendisplay-mode.lock ]; } || pidof home >/dev/null; then
                if [ -f "$U/BOOT_OWN.trying" ]; then
                    mv "$U/BOOT_OWN.trying" "$U/BOOT_OWN" && sync
                fi
            fi
        ) &
        wait "$receiver_pid"
        rm -f /run/opendisplay.pid
    fi
    if ! python3 /opt/opendisplay/settings.py opendisplay; then
        (
            sleep 25
            exec /opt/opendisplay/start
        ) </dev/null >>/var/log/opendisplay.log 2>&1 &
        printf '%s\\n' "$!" >/run/opendisplay.pid
    fi
fi

"""


def patch_init(init):
    """Insert the same start hook in the installer and image build."""
    if HOOK in init:
        return init
    legacy_hook = PREVIOUS_HOOK.replace(
        "after Inkwell rearms its boot marker",
        "after home has passed Inkwell's boot re-arm checkpoint",
    ).replace("[ -d /sys/class/power_supply/bd71827_bat ] && ", "")
    init = init.replace(PREVIOUS_HOOK, "").replace(legacy_hook, "")
    if "/opt/opendisplay/autostart" in init:
        raise ValueError(
            "This Inkwell init script has an unrecognized OpenDisplay hook."
        )
    if init.count("\ncrashes=0\n") != 1:
        raise ValueError(
            "This Inkwell init script lacks the expected boot hook location."
        )
    return init.replace("\ncrashes=0\n", f"\n{HOOK}crashes=0\n")


def install(cpu_latency_us=None, receiver_binary=None):
    """Install the receiver, its configuration and its boot hook."""
    if (
        os.geteuid() != 0
        or not INIT.is_file()
        or not (BOOT / "boot.sh").is_file()
        or not Path("/dev/ttymxc2").exists()
        or not Path("/sys/bus/platform/devices/2034000.serial").is_dir()
    ):
        raise SystemExit("Run this as root on the Inkwell Kindle Paperwhite 4.")
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("This installer requires Inkwell with Python 3.14.")
    init = INIT.read_text()
    try:
        patched_init = patch_init(init)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    installed_binary = TARGET / "kindle-opendisplay"
    if receiver_binary is None and not (
        installed_binary.is_file() and os.access(installed_binary, os.X_OK)
    ):
        raise SystemExit("Supply the Rust ARMv7 binary with --receiver-binary.")

    TARGET.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".install-", dir=TARGET) as directory:
        stage = Path(directory)
        if receiver_binary is not None:
            binary = stage / installed_binary.name
            shutil.copyfile(receiver_binary, binary)
            binary.chmod(0o755)
            subprocess.run([binary, "--version"], check=True)
        files = (
            "settings.py",
            "provision.py",
            "launch.py",
            "sleep_cycle.py",
            "frontlight",
            "start",
        )
        for name in files:
            shutil.copy2(SOURCE / name, stage / name)
        if receiver_binary is not None:
            binary.replace(installed_binary)
        for name in files:
            (stage / name).replace(TARGET / name)

    config, key = provision(TARGET)

    if init != patched_init:
        backup = INIT.with_suffix(".pre-opendisplay")
        if not backup.exists():
            shutil.copy2(INIT, backup)
        with TemporaryDirectory(prefix=".opendisplay-", dir=INIT.parent) as directory:
            staged_init = Path(directory) / INIT.name
            staged_init.write_text(patched_init)
            shutil.copymode(INIT, staged_init)
            subprocess.run(["/bin/sh", "-n", staged_init], check=True)
            staged_init.replace(INIT)
    install_settings(TARGET, cpu_latency_us)
    (TARGET / "autostart").touch()
    print(
        f"OpenDisplay installed for the next Inkwell boot ({json.loads(config.read_text())['address']})."
    )
    print(f"Copy {key} securely to Home Assistant to configure Kindle controls.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cpu-latency-us",
        type=int,
        choices=(0, 50),
        help="Set the receiver's CPU idle latency limit. Omit to retain the installed setting.",
    )
    parser.add_argument(
        "--receiver-binary",
        type=Path,
        help="Path to the Rust ARMv7 receiver. Required if no receiver is installed.",
    )
    args = parser.parse_args()
    install(args.cpu_latency_us, args.receiver_binary)
