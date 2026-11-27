# OpenDisplay BLE

The Rust receiver runs on the jailbroken Kindle Paperwhite 4 (10th
generation) under [Inkwell](https://github.com/akaped/Inkwell).

## Install on the Kindle

The [prebuilt Inkwell image](inkwell-image.md) includes the Rust receiver
and boot hook. For an existing Inkwell installation, put the
`opendisplay/` directory and the ARMv7 release binary on the Kindle. Run
the installer as root from that directory.

```sh
python3 install.py --receiver-binary /path/to/kindle-opendisplay-armv7
```

The installer requires the Rust binary for a new install or an upgrade
from the legacy receiver. For subsequent helper-only updates it can reuse
an installed Rust binary. It keeps the BLE address, control key, and TOML
settings. On first launch it creates
`/opt/opendisplay/device.json`, `control.key`, and `config.toml`.
Pair the resulting device using the
[Home Assistant guide](kindle-inkwell.md).

On next boot, OpenDisplay takes ownership of the panel before Inkwell
Home starts. Home starts if the receiver exits. To start the receiver
from a running Inkwell session, run `/opt/opendisplay/start --manual`.
Reload the running launcher with
`kill -HUP "$(cat /run/opendisplay.pid)"`. The installer saves the
previous init script as `/sbin/own-init.pre-opendisplay`.

## Device settings

See [Device configuration](device-config.md) for every TOML key, default,
and accepted value.

### Timed sleep

For a five-minute idle and five-minute sleep cycle, set both sleep values
to `300`. The **Prevent sleep** HA switch and the default external-power
policy defer suspend. An active BLE connection also defers it.

The last e-ink frame stays visible during suspend. The receiver closes BLE
before suspending, then wakes on the SNVS RTC, repairs DHCP if needed, and
starts BLE again. USB and Wi-Fi SSH and BLE controls need the Kindle awake.
A tested cycle spent about 135 seconds suspended and received a fresh
Home Assistant frame after wake on the same boot.

## Hardware notes

The receiver drives the Broadcom controller over H4 on `/dev/ttymxc2`
at 115200 baud with RTS/CTS. Its bring-up holds the CPU idle constraint,
enables the UART clock, rebinds the UART, powers Bluetooth on, and asserts
the active-low wake line. Cold firmware supports legacy BLE advertising.
Earlier unguarded UART and firmware-loader probes caused watchdog resets.

Use a 1072 × 1448 frame. The receiver writes
`/opt/opendisplay/frame.bin` and refreshes the PW4 panel through EPDC.
The OpenDisplay temperature reads the i.MX chip temperature. The
[hardware validation notes](tested-device.md) cover upload, boot, and
rollback tests.
