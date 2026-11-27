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
and Wi-Fi SSH controls were exercised over BLE. The post-installer's
dependency and boot-hook setup ran in a staging directory on the same device.
The diagnostic boot actions were tested with the reboot command mocked.
The release image and rollback were also tested with actual reboots on
this device. USB and Wi-Fi SSH recovered, and the release image received
and rendered a fresh OpenDisplay frame with Inkwell Home absent.

A timed suspend resumed without a reboot, restarted BLE and restored the
Wi-Fi lease. Home Assistant then delivered a fresh dashboard frame. The
frontlight slider was verified against the driver's actual brightness.

The receiver uses the Paperwhite 4 framebuffer and UART layout. The
controller initialization and power findings are in the
[OpenDisplay BLE guide](opendisplay-ble.md).
