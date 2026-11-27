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


## Idle CPU use

The initial current-thread Tokio build continuously called `epoll_pwait`
with a zero timeout on the Paperwhite 4 and saturated its single core.
The single-worker runtime keeps the BLE futures on the main thread and
drives I/O on a worker. A bounded device comparison recorded zero
receiver CPU ticks over 10 idle seconds with that runtime. A subsequent
50-second run crossed the advertisement refresh interval and recorded one
receiver CPU tick. The Python fallback used about 1.2% total CPU over 15 seconds with the same idle
latency limit. The comparison was on external power and measured CPU
activity, not battery life.
