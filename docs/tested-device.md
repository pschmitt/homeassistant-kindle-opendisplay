# Tested device

| Item | Tested configuration |
| --- | --- |
| Kindle | Paperwhite 4 (10th generation, 2018) |
| Display | 1072 × 1448 e-ink panel |
| Kindle firmware | 5.18.1.1.1 |
| Kernel | 4.1.15-lab126 |
| Inkwell environment | Alpine Linux 3.24.2, armv7 |
| Bluetooth | Internal Broadcom BCM4343A1, H4 UART on `/dev/ttymxc2` |
| Home Assistant | Core 2026.11.3, with an active ESPHome Bluetooth proxy |

Home Assistant sent a full image over native OpenDisplay and the Kindle
confirmed the panel refresh. Battery telemetry and the frontlight, Wi-Fi,
and Wi-Fi SSH controls were exercised over BLE. The diagnostic boot
actions were tested with the reboot command mocked.

The v0.7.0 image and its rollback were tested with physical reboots.
The v0.8.0 Rust installer was tested as an in-place upgrade on the same
device. It preserved the BLE identity, control key, and TOML settings.
After reboot, both USB and Wi-Fi SSH returned, OpenDisplay owned the
panel before Inkwell Home, the boot marker rearmed, and Home Assistant
sent a fresh dashboard frame.

The single-binary launcher and frontlight commands were verified in a
subsequent in-place upgrade. After reboot, USB and Wi-Fi SSH returned,
the Rust launcher owned the panel, and Home Assistant sent a fresh frame.
The legacy frontlight status, battery, and info commands still worked.

A timed suspend resumed without a reboot, restarted BLE and restored the
Wi-Fi lease. Home Assistant then delivered a fresh dashboard frame. The
frontlight slider was verified against the driver's actual brightness.

The receiver uses the Paperwhite 4 framebuffer and UART layout. The
controller initialization and power findings are in the
[OpenDisplay BLE guide](opendisplay-ble.md).
