# Setup

The bridge and dashboard are a prototype extracted from the running demo. The
dashboard was tested on a Paperwhite 4 running Inkwell 1.3.0. It is a custom
Inkwell app, not an OpenDisplay receiver.

## Bridge

The bridge configuration currently lives in `bridge/bridge.py`: it specifies
the local bind address, Home Assistant URL and entity IDs. Adjust those values
for the installation before starting it.

The bridge reads two files from `~/.local/state/agents/inkwell-demo/`:
`ha-token`, a Home Assistant long-lived access token, and `inkwell-token`, a
separate shared token for the Kindle. Keep both files private and outside this
repository. It also requires Python 3 and ImageMagick's `magick` executable.

Run `python3 bridge/bridge.py` on a machine that can reach Home Assistant.
The Kindle's `linux/dashboard.conf` needs the bridge URL, the Inkwell token,
and a refresh interval. For example, with the actual address and token filled
in on the Kindle:

```ini
server = http://bridge.example.com:18765
token = <separate-inkwell-token>
refresh_minutes = 2
sleep_screen = no
```

The bridge sends this token over HTTP, so restrict access to a trusted network
and use a separate token from the Home Assistant credential. The bridge's
`/photo` endpoint checks the vessel MMSI to avoid displaying a photo for the
wrong vessel. Photo attribution comes from the AIS integration and is displayed
below the image.

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
An Inkwell image update can replace these custom files; keep the source and
backups available to reinstall them.

Set `linux/dashboard.rotation` to `left` or `right` for landscape. The
dashboard refreshes the data and vessel photo together. If the photo cannot
be fetched, it removes the cached photo instead of displaying a stale one.
The hidden upper-left touch area returns to the launcher.

## Operation and recovery

Open **Dashboard** from Inkwell's launcher to start the display. The dashboard
stays awake while open, so leave the Kindle on power for a long-running demo.
It refreshes at the configured interval and renders the last cached data if a
refresh cannot complete. If a vessel photo cannot be fetched, the image is
cleared on a successful data refresh; an older screen can remain visible if the
entire bridge is unreachable. The full-screen layout does not show a freshness
indicator, so verify the connection before relying on the displayed values.

If the screen is blank or out of date, verify that the bridge is running, the
Kindle can reach its listening address and port, and both sides use the same
Inkwell token. Verify the Home Assistant token and the configured entities on
the bridge host. Do not print either token in logs or diagnostic output.

To restore the standard Inkwell Dashboard, close Dashboard and restore the
original `/usr/local/bin/dashboard` and `/usr/local/bin/dashboard-fetch` from
the backups made during installation. This does not undo the Kindle jailbreak.

The current bridge is a transient user service with a temporary firewall rule.
Neither survives a host restart. The dashboard is launched manually after a
Kindle reboot. A persistent service, firewall configuration and installation
workflow remain to be implemented.
