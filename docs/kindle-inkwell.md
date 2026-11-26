# Kindle Inkwell

The Kindle Inkwell integration reads battery capacity, charging status, Wi-Fi
association and signal strength. It also controls the frontlight and reports
the Kindle firmware, kernel and Alpine versions. Home Assistant's built-in
OpenDisplay integration sends images and reads the chip temperature over BLE.

## Install

Copy `custom_components/kindle_inkwell` to the corresponding directory in
Home Assistant's configuration. For a submodule deployment, link the domain
directory to the source tree on the server. Restart Home Assistant after first
installing the integration.

## Configure

Install the restricted Kindle SSH command from the [receiver setup](opendisplay-ble.md).
Prepare an OpenSSH configuration file inside Home Assistant's configuration
directory. The host alias must point to the Kindle, use the restricted key, and
pin its host key. Home Assistant Core needs the `ssh` executable on PATH.

Under **Settings → Devices & services → Add integration**, select **Kindle Inkwell**.
Enter the host alias and the absolute path to the SSH configuration inside
Core. Enter the optional OpenDisplay Bluetooth address to group the Kindle
entities under the same Home Assistant device.

Check that the new entities work before removing any old Command Line
switches or sensors for the Kindle. Wi-Fi controls depend on the Kindle being
reachable over SSH. The Wi-Fi entity reports association state and signal
without toggling the radio.
