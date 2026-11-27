# Rust receiver validation

The ready-made Inkwell image includes the static Rust ARMv7 receiver.
The [post-installer](opendisplay-ble.md#install-on-the-kindle) also accepts
that binary for existing Inkwell installations.

CI exercises framebuffer-sized compressed uploads, reconnects, encrypted
controls, and replay rejection using a virtual BLE link. Run the virtual
test after building the Rust binary.

```sh
uv run tests/virtual_hci.py target/debug/kindle-opendisplay
```

The ARMv7 workflow runs the same test under QEMU. On the physical
[Paperwhite 4](tested-device.md), the receiver rendered a Home Assistant
upload and matched every framebuffer pixel.

## Idle CPU use

The current-thread Tokio build busy-polled on the Lab126 kernel. The
current runtime leaves BLE on the main thread and drives I/O on one worker.
A 50-second device test recorded one receiver CPU tick while idle. The
measurement used external power and does not quantify battery life.
