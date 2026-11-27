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

Kindle Inkwell listens to the receiver's BTHome advertisements automatically.
The existing **Battery** and **Charging** entities use the announced readings
when available. Older receivers still provide readings through the
authenticated connection. The two advertised values are visible to nearby
BLE scanners. SSID, BSSID, the current Wi-Fi IPv4 address, and control commands use the
authenticated connection. **Plugged in** reports whether USB or a charger
supplies power, even at 100% when **Charging** is off. Update the Kindle
receiver to enable this sensor. The IP address is unknown while Wi-Fi is
disconnected.

The standalone Home Assistant BTHome entry is optional and creates an
additional device record. If you previously added it, remove that entry
and ignore its rediscovery to keep a single pair of battery entities.

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

The optional `kindle_inkwell.upload_image` action takes the same device,
media image and upload options as `opendisplay.upload_image`. Select the
OpenDisplay device on the same Bluetooth address as the Kindle Inkwell
entry. This action holds the Kindle's BLE lock while calling OpenDisplay,
so status polls and control commands wait for the image transfer.

## Execute a command over BLE

Enable the action in [the Kindle's settings file](opendisplay-ble.md#device-settings):

```toml
[commands]
enabled = true
user = "nobody"
```

Reload the receiver after changing the settings. Commands run as the
selected non-root user inside Inkwell. The BLE command and result are
encrypted with the existing shared key.

Call `kindle_inkwell.execute_command` as a Home Assistant administrator:

```yaml
action: kindle_inkwell.execute_command
data:
  device_id: YOUR_KINDLE_DEVICE_ID
  command: uname -r
response_variable: kindle_result
```

The response contains `stdout`, `stderr`, `exit_code`, `timed_out`, and
`truncated`. Commands accept up to 160 UTF-8 bytes and run for up to five
seconds. The response keeps up to 128 bytes per output stream. A timeout
sets `exit_code` to null. The integration sends each command once.
