# Repository guidance

- `src/` contains the Rust Kindle receiver and installer.
  `opendisplay/` contains the Inkwell boot hooks. `custom_components/kindle_inkwell/`
  contains the Home Assistant integration.
- Keep the README and relevant pages under `docs/` up to date in the same
  change as setup, firmware, BLE, or Home Assistant behavior. Update the
  configuration reference for every changed key or default and the Home
  Assistant entity list whenever an entity changes.
- Keep keys, device identifiers, and instance-specific dashboards out of
  this repository.
- Coordinate live device changes before reloading the receiver or rebooting.
- Release with `just release-prepare X.Y.Z`, then `just release-tag` once the
  bump is on `main`. The tag must match the versions in `Cargo.toml` and the
  integration manifest; the release workflow checks both. `just release-ota
  ENTITY` installs the release through a Home Assistant update entity and
  reads `HASS_URL` and `HASS_TOKEN` from the environment. Coordinate it like
  any other live device change.
