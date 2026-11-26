<p align="center"><img src="custom_components/kindle_inkwell/brand/icon.png" width="120" alt="Kindle e-reader"></p>

<h1 align="center">Kindle OpenDisplay for Home Assistant</h1>

<p align="center">Use an Inkwell Kindle Paperwhite 4 as a Bluetooth e-ink display for Home Assistant.</p>

## Features

- **OpenDisplay BLE** sends images to the e-ink panel from Home Assistant.
- **BTHome** feeds passive battery and charging readings into Kindle Inkwell.
- **Kindle Inkwell** adds frontlight, Wi-Fi and SSH controls, battery and
  device diagnostics, and buttons for rebooting into Inkwell or Kindle OS.

## Install

Install the Paperwhite 4 port of [Inkwell](https://github.com/akaped/Inkwell).
Copy the repository's `opendisplay/` directory to the Kindle. Run the
[post-installer](opendisplay/install.py) as root from that directory:

```sh
python3 install.py --cpu-latency-us 50
```

Omit the option to keep the existing idle setting. See the
[Kindle setup guide](docs/opendisplay-ble.md#install-on-the-kindle), then
configure the [Home Assistant integration](docs/kindle-inkwell.md).

## Documentation

| Topic | Description |
| --- | --- |
| [OpenDisplay BLE](docs/opendisplay-ble.md) | Kindle post-install, panel refresh, and Bluetooth hardware findings. |
| [Home Assistant integration](docs/kindle-inkwell.md) | Marketplace link, pairing, BLE controls, and image uploads. |
| [Tested device](docs/tested-device.md) | Hardware, firmware, and verification on the Paperwhite 4. |

## License

This project is licensed under [GPL-3.0-only](LICENSE).
