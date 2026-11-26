# Rust receiver parity

The Python receiver remains the reference for Home Assistant interoperability.
The Rust protocol library handles per-connection image transfers, the
Paperwhite 4 display configuration, version and manufacturer queries, and
OpenDisplay acknowledgments. The transport sends the frame finish
acknowledgment before refreshing the panel and sends the completion status
afterward.

Hardware parity still requires BLE GATT registration and advertising,
Broadcom UART initialization and cleanup, framebuffer refresh, battery
advertising, and authenticated Kindle telemetry and controls. Verify those
features through Home Assistant on a Paperwhite 4 before switching the
device launcher to Rust.
