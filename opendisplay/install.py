#!/usr/bin/env python3
"""Install the OpenDisplay receiver after installing Inkwell on a PW4."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import venv
from pathlib import Path
from tempfile import TemporaryDirectory

from provision import provision
from settings import install_settings

SOURCE = Path(__file__).resolve().parent
TARGET = Path("/opt/opendisplay")
INIT = Path("/sbin/own-init")
BOOT = Path("/mnt/us/linux")
HOOK = """# Start OpenDisplay after Inkwell rearms its boot marker.
if [ -d /sys/class/power_supply/bd71827_bat ] && [ -f /opt/opendisplay/autostart ] && [ -x /opt/opendisplay/start ]; then
    (
        sleep 25
        exec /opt/opendisplay/start
    ) </dev/null >>/var/log/opendisplay.log 2>&1 &
    printf '%s\\n' "$!" >/run/opendisplay.pid
fi

"""
PACKAGES = (
    "bumble==0.0.236",
    "click",
    "platformdirs",
    "prompt_toolkit",
    "pyee",
    "pycparser",
    "websockets",
    "pyserial-asyncio",
    "pyserial",
    "libusb1",
    "pyusb",
    "typing-extensions",
    "wcwidth",
)


def install_dependencies(stage):
    """Stage Python wheels and Alpine's native Python modules."""
    stage = stage.resolve()
    venv.EnvBuilder(with_pip=True).create(stage / "venv")
    deps = stage / "deps"
    subprocess.run(
        [
            stage / "venv/bin/pip",
            "install",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--no-deps",
            "--target",
            deps,
            *PACKAGES,
        ],
        check=True,
    )
    subprocess.run(
        ["apk", "fetch", "--output", stage, "py3-cryptography", "py3-cffi"],
        check=True,
    )
    prefix = "usr/lib/python3.14/site-packages/"
    for name in ("py3-cryptography", "py3-cffi"):
        (package,) = stage.glob(f"{name}-*.apk")
        with tarfile.open(package, ignore_zeros=True) as archive:
            archive.extractall(
                deps,
                (item for item in archive if item.name.startswith(prefix)),
                filter="data",
            )
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import bumble.transport, serial_asyncio; "
                "from cryptography.hazmat.primitives.ciphers.aead import AESGCM"
            ),
        ],
        env={**os.environ, "PYTHONPATH": f"{deps}:{deps / prefix}"},
        check=True,
    )


def patch_init(init):
    """Insert the same start hook in the installer and image build."""
    if "/opt/opendisplay/autostart" in init:
        return init
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

    TARGET.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".install-", dir=TARGET) as directory:
        stage = Path(directory)
        use_python = (
            receiver_binary is None and not (TARGET / "kindle-opendisplay").is_file()
        )
        if use_python:
            install_dependencies(stage)
        if receiver_binary is not None:
            binary = stage / "kindle-opendisplay"
            shutil.copyfile(receiver_binary, binary)
            binary.chmod(0o755)
            subprocess.run([binary, "--version"], check=True)
            binary.replace(TARGET / binary.name)
        for name in (
            "receiver.py",
            "kindle_gatt.py",
            "settings.py",
            "provision.py",
            "frontlight",
            "start",
        ):
            shutil.copy2(SOURCE / name, stage / name)
            (stage / name).replace(TARGET / name)
        if use_python:
            active_deps = TARGET / "deps"
            if active_deps.exists():
                active_deps.rename(stage / "previous-deps")
            try:
                (stage / "deps").rename(active_deps)
            except OSError:
                if (stage / "previous-deps").exists():
                    (stage / "previous-deps").rename(active_deps)
                raise

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
        help="Install the built Kindle ARMv7 receiver in place of Python BLE dependencies.",
    )
    args = parser.parse_args()
    install(args.cpu_latency_us, args.receiver_binary)
