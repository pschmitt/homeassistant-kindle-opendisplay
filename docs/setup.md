# Setup

The bridge and dashboard are a prototype extracted from the running demo.
The bridge configuration currently lives in `bridge/bridge.py`: it specifies
the local bind address, Home Assistant URL and entity IDs. Adjust those values
for the installation before starting it.

The bridge reads two files from `~/.local/state/agents/inkwell-demo/`:
`ha-token`, a Home Assistant long-lived access token, and `inkwell-token`, a
separate shared token for the Kindle. Keep both files private and outside this
repository. It also requires Python 3 and ImageMagick's `magick` executable.

Run `python3 bridge/bridge.py` on a machine that can reach Home Assistant.
The Kindle's `linux/dashboard.conf` needs the bridge URL, the Inkwell token,
and a refresh interval. The bridge sends this token over HTTP, so restrict
access to a trusted network. The bridge's `/photo` endpoint checks the vessel
MMSI to avoid displaying a photo for the wrong vessel.

## Kindle files

The modified `dashboard/dashboard.c` and `dashboard/dashboard-fetch` are based
on [Inkwell v1.3.0](https://github.com/pragyaangaur/Inkwell/tree/v1.3.0),
commit `c2543218f2d95b89e9621adb673aebce0b105aeb`. To rebuild, check out that
revision of Inkwell, prepare its Alpine armv7 sysroot as described upstream,
copy `dashboard.c` to `src/ui/dashboard.c`, and compile with `tools/kcc` using
`-Ithird_party/stb -Wno-unused-function -s`. Install the resulting executable
as `/usr/local/bin/dashboard` inside Inkwell, and `dashboard-fetch` as
`/usr/local/bin/dashboard-fetch`. Preserve copies of the upstream files for
rollback. These paths are inside the Inkwell image, not the stock Kindle OS.

Set `linux/dashboard.rotation` to `left` or `right` for landscape. The
dashboard refreshes the data and vessel photo together. If the photo cannot
be fetched, it removes the cached photo instead of displaying a stale one.
The hidden upper-left touch area returns to the launcher.

The current bridge is a transient user service with a temporary firewall rule.
Neither survives a host restart. The dashboard is launched manually after a
Kindle reboot. A persistent service, firewall configuration and installation
workflow remain to be implemented.
