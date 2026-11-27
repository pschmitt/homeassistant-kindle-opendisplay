# OpenDisplay BLE on Kindle Paperwhite 4

The Inkwell Paperwhite 4 can use its internal Broadcom BCM4343A1 as an OpenDisplay BLE peripheral. The receiver advertises as `ODKindlePaperwhite4` with service and characteristic UUID `0x2446`. It supports the reference firmware's configuration read and monochrome direct-write commands for a 1072 × 1448 panel. A complete frame replaces the output file atomically. The receiver can save frames for testing or refresh the Kindle panel in OpenDisplay mode.

## Install on the Kindle

Install [Inkwell for Paperwhite 4](https://github.com/akaped/Inkwell) first.
From a checkout of this repository, copy the `opendisplay/` directory to the
Kindle. Run [`install.py`](../opendisplay/install.py) as root inside Inkwell from the copied
directory. The Kindle needs network access to PyPI and its Alpine package
repositories.

```sh
python3 install.py
```

Pass `--cpu-latency-us 50` to opt in to the tested deeper idle setting.
Omitting the flag preserves an existing setting during upgrades.
[See the power and suspend notes](#suspend-and-battery-use).

The installer stages the Python dependencies in `/opt/opendisplay`, creates
a BLE address and control key if needed, and registers the receiver for
the next Inkwell boot. It leaves the saved address and control key in place
on upgrades. It reports the address for the
[Home Assistant integration](kindle-inkwell.md). Start the launcher from
an Inkwell shell or reboot into Inkwell when ready to activate the display.

For the Rust receiver, build the ARMv7 binary with `nix build '.#kindle-armv7'`
and copy it to the Kindle. Pass `--receiver-binary PATH` to the post-installer
to install it. The launcher selects the installed native binary and retains
the Python receiver and dependencies from an earlier installation. Reload
the running launcher with `kill -HUP "$(cat /run/opendisplay.pid)"` to switch
without releasing the Home process. To return to Python, move the binary
out of `/opt/opendisplay` and use the same reload. A full
[Inkwell image](inkwell-image.md) includes the Rust receiver.

## Device settings

Edit `/opt/opendisplay/config.toml` on the Kindle:

```toml
autostart = true
controls = true
opendisplay = true
battery_advertising = true
stay_awake_on_external_power = true
cpu_latency_us = 0

[commands]
enabled = false
user = "nobody"
```

- `autostart` starts the receiver on an Inkwell boot. Use
  `/opt/opendisplay/start --manual` for a foreground session when off.
- `controls` enables authenticated Kindle controls. Command execution also
  requires controls.
- `opendisplay` enables OpenDisplay discovery, image uploads, and panel
  ownership. Turn it off to return the panel to Inkwell Home while keeping
  the optional battery broadcast and authenticated Kindle controls.
- `battery_advertising` enables passive BTHome battery and charging data.
- When Inkwell Home owns the panel, `stay_awake_on_external_power` skips its
  idle sleep screen and suspend on USB or a wall charger. Home still handles
  manual sleep and battery-powered idle. OpenDisplay mode keeps the BLE
  receiver awake for incoming frames.
- `cpu_latency_us` accepts `0` or `50`. See the suspend notes below.
- `commands` enables the BLE command action and selects a local non-root
  Unix account. The account's primary group must also be non-root.

Reload the launcher with SIGHUP after editing the file. The installer
migrates the old `cpu-latency-us` and `allow-ble-command` files when
creating TOML. Once TOML exists it takes precedence. Upgrades preserve it
unless you supply an explicit idle limit. The installer keeps the legacy boot marker for older Inkwell boot hooks.
The TOML setting has the final say. The Bluetooth identity and private
BLE key stay in their own files.

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
  python3 receiver.py --python kindle-pw4 device.json "$PWD/frame.bin"
```

The output is a 194,032-byte packed monochrome frame. The command above saves frames without refreshing the screen. Add `--render` to refresh the panel, or use the launcher described below. BLE commands are plaintext. Partial refresh and pairing are outside the current scope.

A local Bumble virtual-controller test connected, discovered service 0x2446, and received the configuration. A protocol test also used 20-byte ATT payloads and verified CRC, peer isolation, rejection of a truncated upload, and an exact full frame. A separate physical host discovered the Kindle over BLE, read the configuration, and sent a full 194,032-byte frame in 180-byte chunks. The sender and the Kindle produced the same SHA-256 digest. Wi-Fi SSH remained available throughout.

## Suspend and battery use

By default, the receiver requests a zero-microsecond CPU idle latency limit
and holds the Bluetooth UART clock on. A live sample on the Paperwhite 4
entered only its shallow WFI state. In a short trial with a 50 μs latency
limit, the Kindle spent 8.8 of 10 seconds in the deeper WAIT state. BLE
discovery, a GATT read, and a Home Assistant image upload worked at this
setting. The test used USB power, so it measured idle residency without
measuring battery-life improvement.

Opt in to the tested 50 μs setting during installation:

```sh
python3 install.py --cpu-latency-us 50
```

On an installed Kindle, set `cpu_latency_us = 50` in `config.toml`.
The receiver reads it on its next launch. The installer preserves the file
on upgrades unless given an explicit value. Set it to `0` to restore the
default.

In a 35-second suspend-to-idle test, the receiver's BLE advertisements were
initially visible. A client attempted a GATT connection, the read timed
out, and the Bluetooth host-wake interrupt count stayed unchanged. A
battery-backed RTC alarm woke Linux after about 36 seconds and BLE
advertising resumed. USB SSH recovered. Wi-Fi reassociated, but restoring
its IPv4 lease required restarting the Wi-Fi DHCP client over USB. This test
did not exercise deeper suspend modes. Keep the receiver awake if the
display must accept on-demand updates. A scheduled sleep mode would need
an on-device RTC alarm, an HA upload during the awake window, and verified
network recovery after wake. The e-ink panel can hold the last frame
between updates.

A later Paperwhite 4 test entered `mem` with a 45-second alarm on the
wake-enabled SNVS RTC (`rtc1`). It resumed on the same boot after 44.47
seconds of kernel-accounted suspend. USB SSH came back. The Wi-Fi driver
reassociated but needed a fresh DHCP client to regain IPv4. The Bluetooth
receiver exited with HCI `Command Disallowed` and advertising resumed
after restarting the receiver. Scheduled suspend therefore needs explicit
recovery of DHCP and BLE before it can serve an unattended display.

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

The receiver accepts raw and zlib-compressed frames. With autostart and OpenDisplay enabled, Inkwell starts the receiver before launching Home. Home takes over if the receiver exits. Starting the receiver manually pauses an already running Home process and resumes it on exit. Send SIGHUP to the launcher PID in `/run/opendisplay.pid` to reload the receiver. Completed transfers use the PW4 EPDC full refresh ioctl and save the raw frame in `/opt/opendisplay/frame.bin`. This mode holds the controller awake and is intended for a powered display.

With `opendisplay = false` and autostart enabled, Inkwell Home starts normally and the receiver starts in controls-only mode. To stop receiver autostart, set `autostart = false` in `/opt/opendisplay/config.toml`. To stop the running receiver immediately, send SIGTERM to the launcher PID in `/run/opendisplay.pid`. The installer backs up the original Inkwell init script as `/sbin/own-init.pre-opendisplay`.

`sensor.odkindle_temperature` is the Kindle's internal i.MX SoC temperature. The receiver refreshes the advertisement every 30 seconds when the encoded reading changes. It measures the chip, so it will be warmer than the room.

The [Kindle Inkwell integration](kindle-inkwell.md) uses a separate authenticated
BLE service on the same receiver. It provides the frontlight, Wi-Fi and Wi-Fi
SSH switches, battery and charging sensors, and device diagnostics.

A Home Assistant 2026.11.3 test completed the native image action through an ESPHome Bluetooth proxy. HA sent 5,054 compressed bytes, the Kindle reconstructed and saved the 194,032-byte frame, and the panel reported refresh complete.
