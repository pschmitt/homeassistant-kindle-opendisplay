# OpenDisplay BLE on Kindle Paperwhite 4

The Inkwell Paperwhite 4 can use its internal Broadcom BCM4343A1 as an OpenDisplay BLE peripheral. The receiver advertises as `ODKindle` with service and characteristic UUID `0x2446`. It supports the reference firmware's configuration read and uncompressed monochrome direct-write commands for a 1072 × 1448 panel. A complete frame replaces the output file atomically. The receiver has no framebuffer integration and can run alongside the dashboard.

## Controller bring-up

The Lab126 4.1.15 kernel exposes /dev/ttymxc2 but has no attached HCI adapter under Inkwell. Bumble drives the controller over raw H4 UART. The successful initialization sequence keeps the SoC out of deep idle with /dev/cpu_dma_latency, enables the UART clock using /proc/bluetooth/sleep/uart_clk, rebinds only the Bluetooth UART (2034000.serial), enables Bluetooth through bt_pwr_ctrl, and asserts the active-low btwake line. The controller answers HCI Reset at 115200 baud with RTS/CTS. Its cold firmware accepts legacy connectable BLE advertising, so this path needs no Broadcom firmware download.

Opening the UART cold or calling the stock firmware loader without the clock and idle setup caused kernel hangs and watchdog resets. USB Ethernet remained enumerated during one hang, but USB SSH stopped responding along with Wi-Fi. Keeping the clock on made both paths safe to open in testing, and rebinding the UART was the step that made the controller respond. Keep the receiver in the foreground during initial tests so startup failures are visible. The receiver releases the idle constraint and turns Bluetooth off on normal exit, SIGINT, or SIGTERM.

## Running the receiver

Use Bumble 0.0.236 and Python 3.14 on Inkwell. The test installation staged the receiver and pure-Python dependencies under /opt/opendisplay, then extracted the Alpine armv7 py3-cryptography and py3-cffi packages to the same dependency directory. The system package database was left alone. Include both the dependency directory and its usr/lib/python3.14/site-packages directory in PYTHONPATH.

Create a Bumble device configuration named device.json with a unique static random BLE address. For example:

```json
{
  "name": "ODKindle",
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

The output is a 194,032-byte packed monochrome frame. This prototype accepts plaintext commands and implements a file sink for testing. Compression, partial refresh, pairing, and boot-time startup are outside its current scope.

A local Bumble virtual-controller test connected, discovered service 0x2446, and received the configuration. A protocol test also used 20-byte ATT payloads and verified CRC, peer isolation, rejection of a truncated upload, and an exact full frame. A separate physical host discovered the Kindle over BLE, read the configuration, and sent a full 194,032-byte frame in 180-byte chunks. The sender and the Kindle produced the same SHA-256 digest. Wi-Fi SSH remained available throughout.

## References

- [OpenDisplay BLE command flow](https://www.opendisplay.org/protocol/ble-flow.html)
- [Broadcom initialization in kindle-hid-passthrough](https://github.com/zampierilucas/kindle-hid-passthrough/blob/main/kindle_hid_passthrough/bt_brcm.py)
- [Inkwell PW4 port and USB networking](https://github.com/akaped/Inkwell)
