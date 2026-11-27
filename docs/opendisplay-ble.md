# OpenDisplay BLE

The Rust receiver runs on the jailbroken Kindle Paperwhite 4 (10th
generation) under [Inkwell](https://github.com/akaped/Inkwell).

## Install on the Kindle

The [prebuilt Inkwell image](inkwell-image.md) includes the Rust receiver
and boot hook. For an existing Inkwell installation, copy the ARMv7
release binary to a Linux filesystem on the Kindle, such as `/tmp`. Run
it as root.

```sh
chmod +x /tmp/kindle-opendisplay-armv7
/tmp/kindle-opendisplay-armv7 --install
```

The binary installs itself and the boot hook. It keeps the existing BLE
address, control key, and TOML settings. If any are missing, setup creates
`/opt/opendisplay/device.json`, `control.key`, or `config.toml`. The prebuilt
image provisions these files on first boot. Pass `--cpu-latency-us 0` or
`--cpu-latency-us 50` with `--install` to change that setting during setup.
Pair the resulting device using the
[Home Assistant guide](kindle-inkwell.md).

On next boot, OpenDisplay takes ownership of the panel before Inkwell
Home starts. Home starts if the receiver exits. To start the receiver
from a running Inkwell session, run `/opt/opendisplay/start --manual`.
Reload the running launcher with
`kill -HUP "$(cat /run/opendisplay.pid)"`. The installer saves the
previous init script as `/sbin/own-init.pre-opendisplay`.

The Rust binary handles display ownership, sleep, installation, first-boot
provisioning, and frontlight control. The installer creates `start` and
`frontlight` as links to the binary, preserving the boot and legacy forced
SSH entry points. The legacy `frontlight info` command and BLE diagnostics
share the same Rust telemetry code.

## Device settings

See [Device configuration](device-config.md) for every TOML key, default,
and accepted value.

### Timed sleep

For a five-minute idle and five-minute sleep cycle, set both sleep values
to `300`. The **Prevent sleep** HA switch and the default external-power
policy defer suspend. An active BLE connection also defers it.

The last e-ink frame stays visible during suspend. The receiver closes BLE
before suspending. The Rust supervisor wakes on the SNVS RTC, repairs
DHCP if needed, and starts BLE again. USB and Wi-Fi SSH and BLE controls need the Kindle awake.
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
