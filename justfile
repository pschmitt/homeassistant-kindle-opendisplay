# Release tasks for the Kindle receiver and the Home Assistant integration.

default:
    @just --list

# Bump the receiver and integration version, commit and push to main
release-prepare version:
    tools/release.sh prepare {{ version }}

# Push the signed tag for the current version once CI is green, then wait for the release
release-tag:
    tools/release.sh tag

# Install the released receiver through a Home Assistant update entity (needs HASS_URL, HASS_TOKEN)
release-ota entity:
    tools/release.sh ota {{ entity }}
