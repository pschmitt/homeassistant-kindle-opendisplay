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

Install the [Kindle receiver](opendisplay-ble.md#install-on-the-kindle).
The installation creates the key at `/opt/opendisplay/control.key` on the Kindle. Copy it
securely to a private mode-0600 file readable by Home Assistant Core.

## Configure

Add **Kindle Inkwell** under **Settings → Devices & services**, or choose
**Reconfigure** on an existing SSH-based entry to keep its entities. Enter
the Kindle's Bluetooth address and the absolute path to the key file inside
Core. Use an adapter or an active Bluetooth proxy in range of the Kindle.

After the first successful poll, the integration registers the Kindle's
`wlan0` MAC address as a network connection on its Home Assistant device.
Device-registry integrations such as NetBox can match this connection.
The Wi-Fi access point address is reported separately by **BSSID**.

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

## Entities

Names are shown as they appear on the Kindle Inkwell device. The entity
ID normally includes the Kindle's device name.

| Domain | Entity | Reading or action |
| --- | --- | --- |
| Sensor | **Battery** | Capacity in percent, using the BTHome broadcast when available. |
| Sensor | **Wi-Fi signal** | Signal strength in dBm. |
| Sensor | **SSID** | Associated network name. Attributes include device model, Kindle firmware and build, kernel, and Alpine version. |
| Sensor | **BSSID** | Associated access point address. |
| Sensor | **IP address** | Current Wi-Fi IPv4 address. |
| Sensor | **Last telemetry poll** | Last successful active telemetry read. |
| Sensor | **Last battery broadcast** | Last observed BTHome battery packet, sampled at most once a minute. BLE only. |
| Sensor | **CPU temperature** | i.MX chip temperature in °C. |
| Sensor | **Battery temperature** | Stock gauge temperature in °C. |
| Sensor | **Battery voltage** | Voltage in V. |
| Sensor | **Battery current** | Instantaneous current in mA, with the driver sign preserved. |
| Sensor | **Battery average current** | Driver average in mA. |
| Sensor | **Battery charge** | Remaining charge in mAh. |
| Sensor | **Battery full charge** | Learned full charge in mAh. |
| Sensor | **Battery design charge** | Design charge in mAh. |
| Sensor | **Battery cycles** | Cycle count reported by the battery driver. |
| Sensor | **Battery health** | Driver state such as Good. |
| Sensor | **Uptime** | Seconds since boot, including suspend. |
| Sensor | **Total suspend time** | Seconds spent suspended since boot. |
| Sensor | **Last wake** | Time of the most recent recorded timed-suspend resume. |
| Sensor | **Last suspend duration** | Duration of that suspend in seconds. |
| Binary sensor | **Charging** | The battery is actively charging. |
| Binary sensor | **Plugged in** | USB or charger power is present, including when charging stops at 100%. |
| Switch | **Frontlight** | Turn the light off or restore the last nonzero level. |
| Switch | **Wi-Fi** | Disconnect or reassociate Wi-Fi over BLE. |
| Switch | **SSH (Wi-Fi)** | Toggle Inkwell's Wi-Fi SSH listener on port 2022 over BLE. |
| Switch | **Prevent sleep** | Keep the receiver awake over BLE. The override persists across receiver restarts. |
| Number | **Frontlight brightness** | Slider from 0% (off) to 100% of the driver maximum. |
| Select | **Orientation** | HA-stored portrait or landscape hint for your dashboard. Defaults to portrait and can be set while the Kindle is offline. |
| Event | **Event** | New `wake` event after HA observes a recorded timed-suspend resume. Attributes give the device's wake time and suspended seconds. |
| Button | **Reboot into Inkwell** | Restart into Inkwell over BLE. |
| Button | **Reboot into Kindle OS** | Boot Amazon's OS once over BLE. Its next normal reboot returns to Inkwell if the boot hook is enabled. |

The extended battery and CPU readings, uptime, sleep history, the wake event,
and brightness slider require the updated Rust receiver and BLE. The
v0.7.0 receiver supports the earlier readings and controls. Build the
ARMv7 receiver from the current checkout if your release predates these
features.

The contact timestamps retain their last reading during a connection loss.
BLE controls require an awake Kindle. The wake event is based on the
scheduler's resume record. A gap in BLE contact can occur during suspend,
loss of range, or power-off. See [Device configuration](device-config.md)
for the sleep and external-power settings.

## Send an image

Add the discovered **ODKindlePaperwhite4** device through Home Assistant's
native OpenDisplay integration. Use the `opendisplay.upload_image` action
with that device and a media image. A 1072 × 1448 portrait image fills the
panel. This works from automations and scripts using the regular OpenDisplay
action.

Use the **Orientation** select in your dashboard automation to choose the
layout. It stores a preference in Home Assistant. The renderer still sends
an image in the display's native 1072 × 1448 pixel format.

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
