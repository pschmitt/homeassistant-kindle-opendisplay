<p align="center"><img src="custom_components/kindle_inkwell/brand/icon.png" width="120" alt="Kindle e-reader"></p>

<h1 align="center">Kindle OpenDisplay for Home Assistant</h1>

<p align="center">Use an Inkwell Kindle Paperwhite 4 as a Bluetooth e-ink display for Home Assistant.</p>

## Features

- **OpenDisplay over BLE** sends images to the e-ink panel.
- **Kindle Inkwell** adds battery diagnostics, frontlight controls, Wi-Fi
  and SSH switches, and buttons to select the next boot system.
- **Timed sleep** can save power on battery and bring Wi-Fi and BLE back
  on wake. The bundled Inkwell image skips its own idle sleep when
  OpenDisplay is set to start at boot.
- **Receiver recovery** restarts an exited boot receiver while keeping the
  last frame visible.

## Install

Download the Inkwell ZIP or static Rust ARMv7 receiver from
[GitHub Releases](https://github.com/pschmitt/homeassistant-kindle-opendisplay/releases).
The [image guide](docs/inkwell-image.md) covers a fresh Inkwell installation.
For an existing [Inkwell](https://github.com/akaped/Inkwell) installation,
follow the [Kindle setup guide](docs/opendisplay-ble.md#install-on-the-kindle).

Then add the [Home Assistant integration](docs/kindle-inkwell.md) and the
discovered OpenDisplay device. See the integration guide for feature
requirements when using an older receiver.

## Development

Use `nix develop` for development tools and `nix build '.#kindle-armv7'`
for the Kindle binary. See [Rust receiver validation](docs/rust-parity.md)
for tests and performance measurements.

## Documentation

| Topic | Description |
| --- | --- |
| [Device configuration](docs/device-config.md) | Defaults and allowed values for every Kindle TOML setting. |
| [OpenDisplay BLE](docs/opendisplay-ble.md) | Kindle post-install, panel refresh, and Bluetooth hardware findings. |
| [Home Assistant integration](docs/kindle-inkwell.md) | Marketplace link, pairing, BLE controls, and image uploads. |
| [Tested device](docs/tested-device.md) | Hardware, firmware, and verification on the Paperwhite 4. |
| [Inkwell image](docs/inkwell-image.md) | Nix-built Paperwhite 4 archive and ARMv7 receiver. |
| [Rust receiver validation](docs/rust-parity.md) | Protocol coverage and idle CPU use. |
| [Roadmap](docs/roadmap.md) | Milestones for the receiver, Nix builds, and images. |

## License

This project is licensed under [GPL-3.0-only](LICENSE).
