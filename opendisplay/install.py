#!/usr/bin/env python3
"""Install the OpenDisplay receiver after installing Inkwell on a PW4."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import venv
from pathlib import Path
from tempfile import TemporaryDirectory

SOURCE = Path(__file__).resolve().parent
TARGET = Path("/opt/opendisplay")
INIT = Path("/sbin/own-init")
BOOT = Path("/mnt/us/linux")
HOOK = """# Start OpenDisplay after Inkwell rearms its boot marker.
if [ -f /opt/opendisplay/autostart ] && [ -x /opt/opendisplay/start ]; then
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


def install():
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
    hooked = "/opt/opendisplay/autostart" in init
    if not hooked and init.count("\ncrashes=0\n") != 1:
        raise SystemExit(
            "This Inkwell init script lacks the expected boot hook location."
        )

    TARGET.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix=".install-", dir=TARGET) as directory:
        stage = Path(directory)
        install_dependencies(stage)
        for name in ("receiver.py", "kindle_gatt.py", "frontlight", "start"):
            shutil.copy2(SOURCE / name, stage / name)
            (stage / name).replace(TARGET / name)
        active_deps = TARGET / "deps"
        if active_deps.exists():
            active_deps.rename(stage / "previous-deps")
        try:
            (stage / "deps").rename(active_deps)
        except OSError:
            if (stage / "previous-deps").exists():
                (stage / "previous-deps").rename(active_deps)
            raise

    config = TARGET / "device.json"
    if not config.exists():
        address = bytearray(secrets.token_bytes(6))
        address[0] |= 0xC0
        config.write_text(
            json.dumps(
                {
                    "name": "ODKindlePaperwhite4",
                    "address": address.hex(":").upper(),
                    "advertising_interval_min": 100,
                    "advertising_interval_max": 150,
                },
                indent=2,
            )
            + "\n"
        )
    key = TARGET / "control.key"
    if not key.exists():
        with os.fdopen(
            os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
        ) as stream:
            stream.write(secrets.token_hex(32) + "\n")
    key.chmod(0o600)

    if not hooked:
        backup = INIT.with_suffix(".pre-opendisplay")
        if not backup.exists():
            shutil.copy2(INIT, backup)
        with TemporaryDirectory(prefix=".opendisplay-", dir=INIT.parent) as directory:
            staged_init = Path(directory) / INIT.name
            staged_init.write_text(
                init.replace("\ncrashes=0\n", f"\n{HOOK}crashes=0\n")
            )
            shutil.copymode(INIT, staged_init)
            subprocess.run(["/bin/sh", "-n", staged_init], check=True)
            staged_init.replace(INIT)
    (TARGET / "autostart").touch()
    print(
        f"OpenDisplay installed for the next Inkwell boot ({json.loads(config.read_text())['address']})."
    )
    print(f"Copy {key} securely to Home Assistant to configure Kindle controls.")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    install()
