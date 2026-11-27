# Rust receiver parity

The Python receiver remains the reference for Home Assistant interoperability.
The Rust protocol library handles per-connection image transfers, the
Paperwhite 4 display configuration, version and manufacturer queries, and
OpenDisplay acknowledgments. The transport sends the frame finish
acknowledgment before refreshing the panel and sends the completion status
afterward.

The Paperwhite 4 hardware module ports the existing guarded Broadcom UART
sequence and framebuffer refresh. A timed trial on a Paperwhite 4
verified a Home Assistant upload against every framebuffer pixel and a
BLE command running as the configured unprivileged account. USB SSH
stayed connected and the trial restored the Python launcher on exit.
The receiver also advertises battery status and reports external power
through authenticated telemetry.

CI runs `uv run tests/virtual_hci.py target/debug/kindle-opendisplay` after
building the Rust binary. The test uses two Bumble controllers on a virtual
BLE link and verifies a compressed upload, reconnect, authenticated
controls, and rejection of a replayed request. The new Inkwell image
includes the Rust launcher. Existing installations can select it with the
post-installer's `--receiver-binary` option.
