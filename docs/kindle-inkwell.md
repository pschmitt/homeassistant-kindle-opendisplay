# Home Assistant integration

The Kindle Inkwell integration uses an authenticated BLE service to read
battery capacity, charging, SSID, BSSID and Wi-Fi signal strength. It also
controls the frontlight, Wi-Fi, and Wi-Fi SSH on port 2022. It reports the
Kindle firmware, kernel and Alpine versions. The built-in OpenDisplay
integration handles image uploads and chip temperature on the same radio.

## Install

[![Open this integration in Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=pschmitt&repository=homeassistant-kindle-opendisplay&category=integration)

The button opens the custom repository in Marketplace on Home Assistant
2026.11 or later. While the GitHub repository is private, use a checkout
with access and install manually if Marketplace cannot fetch it.

Copy `custom_components/kindle_inkwell` to the corresponding directory in
Home Assistant's configuration. For a submodule deployment, link the domain
directory to its source tree on the server. Restart Home Assistant after
installing or updating the integration.

Run the [Kindle post-installer](opendisplay-ble.md#install-on-the-kindle).
It creates the key at `/opt/opendisplay/control.key` on the Kindle. Copy it
securely to a private mode-0600 file readable by Home Assistant Core.

## Configure

Add **Kindle Inkwell** under **Settings → Devices & services**, or choose
**Reconfigure** on an existing SSH-based entry to keep its entities. Enter
the Kindle's Bluetooth address and the absolute path to the key file inside
Core. Use an adapter or an active Bluetooth proxy in range of the Kindle.

The **Wi-Fi** and **SSH (Wi-Fi)** switches work over BLE even with Wi-Fi
turned off. Wi-Fi SSH controls the Inkwell listener on port 2022. USB SSH stays
available. Turning Wi-Fi back on reconnects to the saved network. This uses Inkwell's association control, while the shared Bluetooth radio stays available. The Wi-Fi
and SSH preferences persist through the normal Inkwell boot.

Control requests use one-time challenges and a shared key. Telemetry is
authenticated and encrypted. Keep the key out of source control.

## Passive battery monitoring

Add the discovered Kindle under Home Assistant's built-in **BTHome**
integration to receive battery percentage and charging status from BLE
advertisements. This needs no bindkey and works with a passive Bluetooth
scanner. The two readings are visible to nearby BLE receivers. The Kindle
Inkwell integration retains its existing battery entities and uses the
authenticated connection for controls and detailed status, including SSID
and BSSID.

## Reboot

The **Reboot into Inkwell** button restarts the device into Inkwell.
**Reboot into Kindle OS** selects Amazon's operating system for one boot.
The next normal reboot from Kindle OS returns to Inkwell if its boot hook
is enabled. The BLE buttons are available while the Inkwell receiver is
running, so restart from the Kindle UI to return from Kindle OS.

## Send an image

Add the discovered **ODKindlePaperwhite4** device through Home Assistant's
native OpenDisplay integration. Use the `opendisplay.upload_image` action
with that device and a media image. A 1072 × 1448 portrait image fills the
panel. This works from automations and scripts using the regular OpenDisplay
action.
