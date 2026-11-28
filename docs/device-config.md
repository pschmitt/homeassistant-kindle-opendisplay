# Device configuration

The receiver reads `/opt/opendisplay/config.toml` on the Kindle.
Omitted keys use the defaults below. Values at the top level go before
`[commands]` and `[updates]`. Reload from Inkwell after saving. The receiver
reads the update settings on each update attempt, so changing only those
settings takes effect without a reload.

```sh
kill -HUP "$(cat /run/opendisplay.pid)"
```

```toml
autostart = true
opendisplay = true
controls = true
frontlight_double_tap = true
battery_advertising = true
cpu_latency_us = 0
stay_awake_on_external_power = true
sleep_after_seconds = 0
sleep_for_seconds = 300
full_refresh_every = 10

[commands]
enabled = false
user = "nobody"

[updates]
require_external_power = true
minimum_battery_percent = 30
```

| Key | Default | Accepted values and effect |
| --- | --- | --- |
| `autostart` | `true` | Boolean. Start the receiver at Inkwell boot. With `opendisplay` enabled, also inhibit idle sleep in the patched Inkwell UI. The launcher can still run manually. |
| `opendisplay` | `true` | Boolean. Advertise OpenDisplay, accept images, and own the panel. Set to `false` for Inkwell Home with the other enabled BLE services. |
| `controls` | `true` | Boolean. Serve authenticated controls and active telemetry over BLE. Command execution also requires this. |
| `frontlight_double_tap` | `true` | Boolean. While OpenDisplay owns the panel and the Kindle is awake, double-tap the touchscreen to set the frontlight to 50% for 20 seconds. It then restores the previous level. A manual brightness change cancels the boost. |
| `battery_advertising` | `true` | Boolean. Broadcast battery percentage and charging state in BTHome advertisements. The broadcast is visible to nearby scanners. |
| `cpu_latency_us` | `0` | Integer, `0` or `50` microseconds. Limits CPU idle latency while the radio runs. Change it only when testing the latency and power tradeoff. |
| `stay_awake_on_external_power` | `true` | Boolean. Defer timed sleep on USB or a charger. Also inhibits automatic idle sleep in the patched Inkwell Home. |
| `sleep_after_seconds` | `0` | Integer, `0` or 30–86,400. Zero disables OpenDisplay timed suspend. Other values set the quiet period after launch or the last completed frame. |
| `sleep_for_seconds` | `300` | Integer, 15–86,400. Sets the RTC wake interval when OpenDisplay timed sleep is enabled. |
| `full_refresh_every` | `10` | Integer, 0–1,000. Frames normally use a REAGL partial update, which redraws only changed pixels without the black-and-white flash. The first frame after launch and every Nth frame after it use a flashing GC16 full refresh to clear ghosting. `1` flashes every frame, as before; `0` flashes only the first. |
| `commands.enabled` | `false` | Boolean. Allow authenticated, encrypted command execution with `commands.user`. |
| `commands.user` | `"nobody"` | Nonempty local username. When execution is enabled, both the account and its primary group must be non-root. |
| `updates.require_external_power` | `true` | Boolean. Set to `false` to allow receiver updates on battery. |
| `updates.minimum_battery_percent` | `30` | Integer, 1–100. When updating without external power, the battery gauge must report at least this percentage. |

**Prevent sleep** in Home Assistant can defer suspend even on battery.
Active BLE connections also defer timed suspend. The launcher keeps the
last frame on the panel while BLE and SSH are offline.

The installer preserves existing settings. For a legacy install without
TOML it can read `cpu-latency-us` and `allow-ble-command`. Once TOML
exists it takes precedence. The address in `device.json` and the key
in `control.key` are separate device-local files. Keep the key private.
