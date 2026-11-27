# Repository guidance

- `src/` contains the Rust Kindle receiver. `opendisplay/` contains
  the post-installer and launcher. `custom_components/kindle_inkwell/`
  contains the Home Assistant integration.
- Keep the README and relevant pages under `docs/` up to date in the same
  change as setup, firmware, BLE, or Home Assistant behavior. Update the
  configuration reference for every changed key or default and the Home
  Assistant entity list whenever an entity changes.
- Keep keys, device identifiers, and instance-specific dashboards out of
  this repository.
- Coordinate live device changes before reloading the receiver or rebooting.
