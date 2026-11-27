# Roadmap

- [x] Port the Kindle-side receiver to Rust and verify BLE, UART bring-up,
  and framebuffer refresh on the Paperwhite 4.
- [x] Build the Rust receiver with Nix and [Crane](https://github.com/ipetkov/crane).
  Add native checks and an ARMv7 Linux package for the Kindle, with separate
  build outputs for host tests and target binaries.
- [x] Onboard the flake into Circus once the receiver package and checks
  exist. Publish reproducible ARMv7 artifacts from successful builds.
- [x] Build ready-made Inkwell images with Nix. Pin upstream Inkwell, apply
  the receiver and startup hook as a reproducible overlay or patch, and
  keep per-device keys and configuration outside the image. Validate boot,
  rollback, and Home Assistant compatibility on a Paperwhite 4 before
  publishing the images.

## Home Assistant updates

- [x] Match the ARMv7 binary version with the GitHub release and report it
  over authenticated BLE.
- [x] Add a receiver update entity to Home Assistant. Fetch, verify, and
  trial the new binary on the Kindle. Confirm it after BLE reconnect.
- [ ] Evaluate full Inkwell image updates separately. They replace the
  root filesystem and need a boot and rollback strategy of their own.
