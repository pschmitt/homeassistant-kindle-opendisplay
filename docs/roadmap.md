# Roadmap

- [ ] Port the Kindle-side receiver to Rust. Keep the Python implementation
  as a reference for BLE wire compatibility, PW4 UART bring-up, and
  framebuffer refresh. Verify the Rust receiver on the Paperwhite 4.
- [ ] Build the Rust receiver with Nix and [Crane](https://github.com/ipetkov/crane).
  Add native checks and an ARMv7 Linux package for the Kindle, with separate
  build outputs for host tests and target binaries.
- [ ] Onboard the flake into Circus once the receiver package and checks
  exist. Publish reproducible ARMv7 artifacts from successful builds.
- [ ] Build ready-made Inkwell images with Nix. Pin upstream Inkwell, apply
  the receiver and startup hook as a reproducible overlay or patch, and
  keep per-device keys and configuration outside the image. Validate boot,
  rollback, and Home Assistant compatibility on a Paperwhite 4 before
  publishing the images.
