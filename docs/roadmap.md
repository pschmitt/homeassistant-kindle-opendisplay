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
