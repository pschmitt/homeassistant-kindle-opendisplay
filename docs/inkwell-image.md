# Inkwell image for Paperwhite 4

The Nix build uses the pinned [Paperwhite 4 port of Inkwell][inkwell] and
the static ARMv7 OpenDisplay receiver. The Kindle must already support
Inkwell. See the upstream install and recovery instructions for the
Kindle OS and boot hook.

[inkwell]: https://github.com/akaped/Inkwell/tree/29cc6d02c14c6897fe47356d228b318c846fdfcd

## Build

```sh
nix build '.#inkwell-pw4'
(cd result && sha256sum -c SHA256SUMS)
```

`result/Inkwell-Paperwhite4-OpenDisplay.zip` contains `linux/` and
`documents/` in the upstream release layout. The archive includes the
receiver and its startup hook. The first run generates the BLE identity and
shared control key and writes the default TOML settings inside the Inkwell
filesystem. Add your own Wi-Fi and SSH configuration using the upstream
instructions. Device keys, addresses, and user configuration belong on the
Kindle.

With OpenDisplay enabled, the receiver starts before Inkwell Home can draw.
Home starts if the receiver exits, or immediately if OpenDisplay or
autostart is disabled. When Home owns the panel, external power inhibits
automatic idle sleep by default. Edit
`stay_awake_on_external_power` in `/opt/opendisplay/config.toml` to change it.
The **Prevent sleep** diagnostic switch also inhibits automatic idle sleep
on battery.

For an existing installation, build just the receiver with
`nix build '.#kindle-armv7'`. Copy the binary to the device and use
`python3 install.py --receiver-binary PATH` from the
[post-installer directory](../opendisplay/). The installer preserves an
existing BLE identity, key and TOML settings.

## Validation

CI exercises the ARMv7 binary with an emulated Cortex-A9 and two virtual
BLE controllers. It tests encrypted controls, command replay rejection,
full compressed image upload, and reconnect. The ext3 image build checks
the filesystem and verifies that it contains the receiver and has no BLE
identity or control key.

On the tested Paperwhite 4, booting the image brought back USB and Wi-Fi
SSH. OpenDisplay started before Inkwell Home, and all framebuffer pixels
matched a fresh upload from Home Assistant. Restoring the previous
`alpine.img` also booted and received a new frame. Keep a copy of your
working image and its device-local data when installing a replacement.
