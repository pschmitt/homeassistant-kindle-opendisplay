"""Create the receiver identity and key on each Kindle."""

import json
import os
import secrets
from pathlib import Path


def provision(directory):
    """Initialize missing device files without replacing an existing identity."""
    config = directory / "device.json"
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
    key = directory / "control.key"
    if not key.exists():
        with os.fdopen(
            os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
        ) as stream:
            stream.write(secrets.token_hex(32) + "\n")
    key.chmod(0o600)

    return config, key


if __name__ == "__main__":
    provision(Path(__file__).resolve().parent)
