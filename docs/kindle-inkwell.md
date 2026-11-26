# Kindle Inkwell

The Kindle Inkwell integration uses an authenticated BLE service to read
battery capacity, charging, Wi-Fi association and signal strength. It also
controls the frontlight, Wi-Fi, and Wi-Fi SSH on port 2022. It reports the
Kindle firmware, kernel and Alpine versions. The built-in OpenDisplay
integration handles image uploads and chip temperature on the same radio.

## Install

Copy `custom_components/kindle_inkwell` to the corresponding directory in
Home Assistant's configuration. For a submodule deployment, link the domain
directory to its source tree on the server. Restart Home Assistant after
installing or updating the integration.

Follow the [receiver setup](opendisplay-ble.md) on the Kindle. Install
`receiver.py`, `kindle_gatt.py` and the `frontlight` helper together under
`/opt/opendisplay`.

Generate a random 32-byte key encoded as 64 hexadecimal characters. Keep a
mode-0600 copy at `/opt/opendisplay/control.key` on the Kindle and another in
a private file readable by Home Assistant Core. Reload the Kindle receiver
after installing the key. A receiver launched with `nohup` can inherit an
ignored SIGHUP. Use the launcher from the Inkwell boot hook or start it with
`setsid` when detaching manually.

## Configure

Add **Kindle Inkwell** under **Settings → Devices & services**, or choose
**Reconfigure** on an existing SSH-based entry to keep its entities. Enter
the Kindle's Bluetooth address and the absolute path to the key file inside
Core. Use an adapter or an active Bluetooth proxy in range of the Kindle.

The **Wi-Fi radio** and **Wi-Fi SSH** switches work over BLE even with Wi-Fi
turned off. Wi-Fi SSH controls the Inkwell listener on port 2022. USB SSH stays
available. Turning Wi-Fi back on reconnects to the saved network. The Wi-Fi
and SSH preferences persist through the normal Inkwell boot.

Control requests and telemetry responses are authenticated with one-time
challenges and a shared key. BLE telemetry travels in plaintext. Keep the
key out of source control.
