# OpenDisplay BLE on Kindle Paperwhite 4

The Inkwell Paperwhite 4 can use its internal Broadcom BCM4343A1 as an OpenDisplay BLE peripheral. The receiver advertises as `ODKindlePaperwhite4` with service and characteristic UUID `0x2446`. It supports the reference firmware's configuration read and monochrome direct-write commands for a 1072 × 1448 panel. A complete frame replaces the output file atomically. The receiver can save frames for testing or refresh the Kindle panel in OpenDisplay mode.

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

## References

- [OpenDisplay BLE command flow](https://www.opendisplay.org/protocol/ble-flow.html)
- [Broadcom initialization in kindle-hid-passthrough](https://github.com/zampierilucas/kindle-hid-passthrough/blob/main/kindle_hid_passthrough/bt_brcm.py)
- [Inkwell PW4 port and USB networking](https://github.com/akaped/Inkwell)

## Home Assistant

The receiver includes the manufacturer data and four configuration records required by Home Assistant. Add the discovered **ODKindlePaperwhite4** device under OpenDisplay. It can be named **Kindle Paperwhite 4** in Home Assistant. Then call `opendisplay.upload_image` with the device and a media image. An active Bluetooth adapter or ESPHome proxy must be in range. Reload the OpenDisplay entry after changing receiver capabilities because Home Assistant caches the configuration.

The receiver accepts raw and zlib-compressed frames. For panel output, install and run `/opt/opendisplay/start`. It pauses the Inkwell home process while the receiver owns the panel and resumes it on exit. Send SIGHUP to the launcher PID in `/run/opendisplay.pid` to reload the receiver without letting Home draw its lock screen or suspend the Kindle. Completed transfers use the PW4 EPDC full refresh ioctl and save the raw frame in `/opt/opendisplay/frame.bin`. The foreground dashboard remains available after exiting OpenDisplay mode. This mode holds the controller awake and is intended for a powered display.

On the configured Kindle, the Inkwell init hook starts the receiver after the usual boot checkpoint when `/opt/opendisplay/autostart` exists. To return to Inkwell home, remove that marker and send SIGTERM to the receiver PID in `/run/opendisplay.pid`. The original Inkwell init script is saved as `/sbin/own-init.pre-opendisplay`.

`sensor.odkindle_temperature` is the Kindle's internal i.MX SoC temperature. The receiver refreshes the advertisement every 30 seconds when the encoded reading changes. It measures the chip, so it will be warmer than the room.

The [Kindle Inkwell integration](kindle-inkwell.md) provides a frontlight switch and battery and Wi-Fi sensors. Install `opendisplay/frontlight` as `/opt/opendisplay/frontlight` on the Kindle, and give Home Assistant a dedicated SSH key with that forced command and forwarding and PTY disabled. Pin the Kindle host key. The endpoint accepts `on`, `off`, `status`, `battery`, and `info` only. Turning the frontlight on restores its last nonzero brightness. The battery command reports the kernel's actual capacity percentage and charging state.

The Wi-Fi sensor includes the association state, RSSI, device type, Kindle firmware and build, kernel release, and Alpine version. It is read-only. Home Assistant cannot turn Wi-Fi back on over an SSH connection that depends on it. A BLE Wi-Fi control would need a separate authenticated GATT service and a Home Assistant client for that service.

A Home Assistant 2026.11.3 test completed the native image action through an ESPHome Bluetooth proxy. HA sent 5,054 compressed bytes, the Kindle reconstructed and saved the 194,032-byte frame, and the panel reported refresh complete.
