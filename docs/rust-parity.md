# Rust receiver parity

The Python receiver remains the reference for Home Assistant interoperability.
The Rust protocol library handles per-connection image transfers, the
Paperwhite 4 display configuration, version and manufacturer queries, and
OpenDisplay acknowledgments. The transport sends the frame finish
acknowledgment before refreshing the panel and sends the completion status
afterward.

The Paperwhite 4 hardware module ports the existing guarded Broadcom UART
sequence and framebuffer refresh. Both paths still need device testing.
The receiver registers the configured GATT services, advertises battery
status, and implements the existing authenticated Kindle telemetry and
control messages. Verify them through Home Assistant on a Paperwhite 4
before switching the device launcher to Rust.

CI runs `uv run tests/virtual_hci.py target/debug/kindle-opendisplay` after
building the Rust binary. The test uses two Bumble controllers on a virtual
BLE link and verifies a compressed upload, reconnect, authenticated
controls, and rejection of a replayed request. The installed launcher
continues to use the Python receiver until device validation.
