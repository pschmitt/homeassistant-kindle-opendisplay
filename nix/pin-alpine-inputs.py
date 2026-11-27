"""Write the package paths and hashes for the pinned Inkwell source.

Run on a build worker with Python, curl, and a checkout of the pinned upstream
revision. Only the JSON manifest belongs in the repository.
"""

import concurrent.futures
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ALPINE = "https://dl-cdn.alpinelinux.org/alpine/v3.24"
SYSROOT = [
    "musl",
    "musl-dev",
    "linux-headers",
    "compiler-rt",
    "libc++",
    "libc++-dev",
    "libc++-static",
    "llvm-libunwind-dev",
    "llvm-libunwind-static",
]


def download(url):
    return subprocess.check_output(["curl", "-fsSL", "--retry", "3", url])


def names(args):
    return subprocess.check_output(
        [sys.executable, upstream / "tools/apkdeps.py", *args], text=True
    ).splitlines()


def record(package):
    url = f"{ALPINE}/{package.replace('/', '/armv7/', 1)}.apk"
    return {
        "name": package.split("/", 1)[1] + ".apk",
        "url": url,
        "sha256": hashlib.sha256(download(url)).hexdigest(),
    }


upstream, scratch = map(Path, sys.argv[1:])
scratch.mkdir(parents=True, exist_ok=True)
indexes = [scratch / f"APKINDEX.{repo}" for repo in ("main", "community")]
for index in indexes:
    repo = index.suffix[1:]
    with tarfile.open(
        fileobj=io.BytesIO(download(f"{ALPINE}/{repo}/armv7/APKINDEX.tar.gz"))
    ) as archive:
        source = archive.extractfile("APKINDEX")
        if source is None:
            raise RuntimeError("missing APKINDEX")
        index.write_bytes(source.read())

build = (upstream / "build-rootfs.sh").read_text()
package_line = re.search(r'^PKGS="([^"]+)"$', build, re.MULTILINE)
if package_line is None:
    raise RuntimeError("missing Inkwell package list")
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as workers:
    print(
        json.dumps(
            {
                "sysroot": list(
                    workers.map(record, names(["--exact", indexes[0], *SYSROOT]))
                ),
                "rootfs": list(
                    workers.map(
                        record,
                        names([",".join(map(str, indexes)), *package_line[1].split()]),
                    )
                ),
            },
            indent=2,
        )
    )
