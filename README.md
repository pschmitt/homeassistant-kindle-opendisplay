<h1 align="center">Inkwell HA dashboard</h1>

<p align="center">A landscape Home Assistant dashboard for an Inkwell Kindle.</p>

## Features

- **Full-screen display:** a clock, home measurements and the latest vessel.
- **Vessel photo:** the AIS integration's photo, with photographer credit.
- **Bridge:** a small authenticated HTTP server reads Home Assistant states.

## Install

This prototype needs a jailbroken Paperwhite 4 running Inkwell 1.3.0, a Home
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
| [Setup](docs/setup.md) | Build, credentials and deployment notes. |

## License

The modified Inkwell files in `dashboard/` retain their upstream
[MIT license](dashboard/LICENSE.upstream).
