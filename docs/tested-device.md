# Tested device

| Item | Tested configuration |
| --- | --- |
| Kindle | Paperwhite 4 (10th generation, 2018) |
| Display | 1072 × 1448 e-ink panel |
| Kindle firmware | 5.18.1.1.1 |
| Kernel | 4.1.15-lab126 |
| Inkwell environment | Alpine Linux 3.24.2, armv7, Python 3.14.8 |
| Bluetooth | Internal Broadcom BCM4343A1, H4 UART on `/dev/ttymxc2` |
| Home Assistant | Core 2026.11.3, with an active ESPHome Bluetooth proxy |

Home Assistant sent a full image over native OpenDisplay and the Kindle
confirmed the panel refresh. Battery telemetry and the frontlight, Wi-Fi,
and Wi-Fi SSH controls were exercised over BLE. The post-installer's
dependency and boot-hook setup ran in a staging directory on the same device.
The boot targets were tested with the actual reboot command mocked.

The receiver uses the Paperwhite 4 framebuffer and UART layout. The
controller initialization and power findings are in the
[OpenDisplay BLE guide](opendisplay-ble.md).
