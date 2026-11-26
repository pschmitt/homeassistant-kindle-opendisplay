# OpenDisplay BLE on Kindle Paperwhite 4

The Inkwell Paperwhite 4 can use its internal Broadcom BCM4343A1 as an OpenDisplay BLE peripheral. The receiver advertises as `ODKindlePaperwhite4` with service and characteristic UUID `0x2446`. It supports the reference firmware's configuration read and monochrome direct-write commands for a 1072 × 1448 panel. A complete frame replaces the output file atomically. The receiver can save frames for testing or refresh the Kindle panel in OpenDisplay mode.

## Install on the Kindle

Install [Inkwell for Paperwhite 4](https://github.com/akaped/Inkwell) first.
From a checkout of this repository, copy the `opendisplay/` directory to the
Kindle. Run the following command as root inside Inkwell from the copied
directory. The Kindle needs network access to PyPI and its Alpine package
repositories.

```sh
python3 install.py
```

The installer stages the Python dependencies in `/opt/opendisplay`, creates
a BLE address and control key if needed, and registers the receiver for
the next Inkwell boot. It leaves the saved address and control key in place
on upgrades. It reports the address for the
[Home Assistant integration](kindle-inkwell.md). Start the launcher from
an Inkwell shell or reboot into Inkwell when ready to activate the display.

## Controller bring-up

The Lab126 4.1.15 kernel exposes /dev/ttymxc2 but has no attached HCI adapter under Inkwell. Bumble drives the controller over raw H4 UART. The successful initialization sequence keeps the SoC out of deep idle with /dev/cpu_dma_latency, enables the UART clock using /proc/bluetooth/sleep/uart_clk, rebinds only the Bluetooth UART (2034000.serial), enables Bluetooth through bt_pwr_ctrl, and asserts the active-low btwake line. The controller answers HCI Reset at 115200 baud with RTS/CTS. Its cold firmware accepts legacy connectable BLE advertising, so this path needs no Broadcom firmware download.

Opening the UART cold or calling the stock firmware loader without the clock and idle setup caused kernel hangs and watchdog resets. USB Ethernet remained enumerated during one hang, but USB SSH stopped responding along with Wi-Fi. Keeping the clock on made both paths safe to open in testing, and rebinding the UART was the step that made the controller respond. Keep the receiver in the foreground during initial tests so startup failures are visible. The receiver releases the idle constraint and turns Bluetooth off on normal exit, SIGINT, or SIGTERM.

## Running the receiver

Use Bumble 0.0.236 and Python 3.14 on Inkwell. The test installation staged the receiver and pure-Python dependencies under /opt/opendisplay, then extracted the Alpine armv7 py3-cryptography and py3-cffi packages to the same dependency directory. The system package database was left alone. Include both the dependency directory and its usr/lib/python3.14/site-packages directory in PYTHONPATH.

Create a Bumble device configuration named device.json with a unique static random BLE address. For example:

```json
{
  "name": "ODKindlePaperwhite4",
  "address": "C0:00:00:46:24:01",
  "advertising_interval_min": 100,
  "advertising_interval_max": 150
}
```

Run the receiver on the Kindle as root from its installation directory:

```sh
PYTHONPATH="$PWD/deps:$PWD/deps/usr/lib/python3.14/site-packages" \
  python3 receiver.py kindle-pw4 device.json "$PWD/frame.bin"
```

The output is a 194,032-byte packed monochrome frame. The command above saves frames without refreshing the screen. Add `--render` to refresh the panel, or use the launcher described below. BLE commands are plaintext. Partial refresh and pairing are outside the current scope.

A local Bumble virtual-controller test connected, discovered service 0x2446, and received the configuration. A protocol test also used 20-byte ATT payloads and verified CRC, peer isolation, rejection of a truncated upload, and an exact full frame. A separate physical host discovered the Kindle over BLE, read the configuration, and sent a full 194,032-byte frame in 180-byte chunks. The sender and the Kindle produced the same SHA-256 digest. Wi-Fi SSH remained available throughout.

## BTHome advertisements

On the Paperwhite 4, the receiver includes BTHome v2 battery percentage and
charging in its legacy advertisement and refreshes readings every 30 seconds.
It keeps the OpenDisplay manufacturer data in the primary packet and fits the
name and OpenDisplay service UUID list in the scan response. Long custom names
can use the full scan response, in which case the UUID remains available from
GATT discovery. This layout keeps the passive BTHome data in the primary
packet.

## References

- [BTHome v2 packet format](https://bthome.io/format/)
- [OpenDisplay BLE command flow](https://www.opendisplay.org/protocol/ble-flow.html)
- [Broadcom initialization in kindle-hid-passthrough](https://github.com/zampierilucas/kindle-hid-passthrough/blob/main/kindle_hid_passthrough/bt_brcm.py)
- [Inkwell PW4 port and USB networking](https://github.com/akaped/Inkwell)

## Home Assistant

The receiver includes the manufacturer data and four configuration records required by Home Assistant. Add the discovered **ODKindlePaperwhite4** device under OpenDisplay. It can be named **Kindle Paperwhite 4** in Home Assistant. Then call `opendisplay.upload_image` with the device and a media image. An active Bluetooth adapter or ESPHome proxy must be in range. Reload the OpenDisplay entry after changing receiver capabilities because Home Assistant caches the configuration.

The receiver accepts raw and zlib-compressed frames. For panel output, install and run `/opt/opendisplay/start`. It pauses the Inkwell home process while the receiver owns the panel and resumes it on exit. Send SIGHUP to the launcher PID in `/run/opendisplay.pid` to reload the receiver without letting Home draw its lock screen or suspend the Kindle. Completed transfers use the PW4 EPDC full refresh ioctl and save the raw frame in `/opt/opendisplay/frame.bin`. This mode holds the controller awake and is intended for a powered display.

The installer adds an Inkwell init hook that starts the receiver after the usual boot checkpoint when `/opt/opendisplay/autostart` exists. To return to Inkwell home, remove that marker and send SIGTERM to the receiver PID in `/run/opendisplay.pid`. The installer backs up the original Inkwell init script as `/sbin/own-init.pre-opendisplay`.

`sensor.odkindle_temperature` is the Kindle's internal i.MX SoC temperature. The receiver refreshes the advertisement every 30 seconds when the encoded reading changes. It measures the chip, so it will be warmer than the room.

The [Kindle Inkwell integration](kindle-inkwell.md) uses a separate authenticated
BLE service on the same receiver. It provides the frontlight, Wi-Fi and Wi-Fi
SSH switches, battery and charging sensors, and device diagnostics.

A Home Assistant 2026.11.3 test completed the native image action through an ESPHome Bluetooth proxy. HA sent 5,054 compressed bytes, the Kindle reconstructed and saved the 194,032-byte frame, and the panel reported refresh complete.
