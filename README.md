<p align="center"><img src="custom_components/kindle_inkwell/brand/icon.png" width="120" alt="Kindle e-reader"></p>

<h1 align="center">Kindle OpenDisplay for Home Assistant</h1>

<p align="center">OpenDisplay BLE, Home Assistant device controls and an optional dashboard for a Kindle running Inkwell.</p>

## Features

- **OpenDisplay BLE:** send images to the e-ink panel from Home Assistant.
- **Kindle Inkwell integration:** frontlight, battery, Wi-Fi and SSH controls over BLE.
- **Full-screen display:** a clock, home measurements and the latest vessel.
- **Vessel photo:** the AIS integration's photo, with photographer credit.
- **Bridge:** a small authenticated HTTP server reads Home Assistant states.

## Install

For image uploads and Kindle telemetry, follow [OpenDisplay setup](docs/opendisplay-ble.md) and [Kindle Inkwell setup](docs/kindle-inkwell.md).

The dashboard needs a jailbroken Paperwhite 4 running Inkwell 1.3.0, a Home
Assistant instance and a machine to run the bridge. Follow [setup](docs/setup.md)
to configure credentials and install the dashboard.

## Quick start

After completing setup, start the bridge on the machine that can reach Home
Assistant:

```sh
python3 bridge/bridge.py
```

Open Dashboard on the Kindle. The screen updates every two minutes in the demo.

## Documentation

| Topic | Description |
| --- | --- |
| [Kindle Inkwell](docs/kindle-inkwell.md) | Install and configure the custom integration. |
| [OpenDisplay BLE](docs/opendisplay-ble.md) | Kindle receiver, panel refresh and hardware findings. |
| [Setup](docs/setup.md) | Build, credentials and deployment notes. |

## License

This project is licensed under [GPL-3.0-only](LICENSE).

The modified Inkwell files in `dashboard/` retain their upstream
[MIT license](dashboard/LICENSE.upstream).
