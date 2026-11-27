//! Paperwhite frontlight and the legacy forced SSH command.

use crate::{actions, advertising};
use anyhow::{Context, Result, ensure};
use serde_json::json;
use std::{fs, path::Path};

const BACKLIGHT: &str = "/sys/class/backlight/bl";
const SAVED_LEVEL: &str = "/opt/opendisplay/frontlight-level";

struct Frontlight<'a> {
    directory: &'a Path,
    saved: &'a Path,
}

impl Frontlight<'_> {
    fn read_level(&self, file: &str) -> Result<u32> {
        Ok(fs::read_to_string(self.directory.join(file))?
            .trim()
            .parse()?)
    }

    fn apply(&self, requested: u32) -> Result<()> {
        // This sysfs driver may report a write error after applying the value.
        let result = fs::write(self.directory.join("brightness"), format!("{requested}\n"));
        if self.read_level("brightness")? != requested {
            result.context("write frontlight brightness")?;
            anyhow::bail!("frontlight driver did not apply the requested brightness");
        }
        Ok(())
    }

    fn save(&self, level: u32) -> Result<()> {
        Ok(fs::write(self.saved, format!("{level}\n"))?)
    }

    fn set(&self, requested: u32, current: u32) -> Result<()> {
        if requested == 0 && current > 0 {
            self.save(current)?;
        }
        self.apply(requested)?;
        if requested > 0 {
            self.save(requested)?;
        }
        Ok(())
    }

    fn toggle(&self, enabled: bool, current: u32) -> Result<()> {
        if enabled && current == 0 {
            let level = match fs::read_to_string(self.saved) {
                Ok(text) if !text.is_empty() => text.trim().parse()?,
                Ok(_) => 297,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => 297,
                Err(error) => return Err(error.into()),
            };
            ensure!(
                level > 0 && level <= self.read_level("max_brightness")?,
                "invalid saved brightness"
            );
            self.apply(level)?;
        } else if !enabled && current > 0 {
            self.save(current)?;
            self.apply(0)?;
        }
        Ok(())
    }
}

fn device() -> Frontlight<'static> {
    Frontlight {
        directory: Path::new(BACKLIGHT),
        saved: Path::new(SAVED_LEVEL),
    }
}

pub fn set(level: u16) -> Result<()> {
    let light = device();
    let current = light.read_level("brightness")?;
    ensure!(
        u32::from(level) <= light.read_level("max_brightness")?,
        "invalid brightness"
    );
    light.set(level.into(), current)
}

pub fn toggle(enabled: bool) -> Result<()> {
    let light = device();
    light.toggle(enabled, light.read_level("brightness")?)
}

pub async fn forced_command() -> Result<i32> {
    let light = device();
    let current = light.read_level("brightness")?;
    let command = std::env::var("SSH_ORIGINAL_COMMAND").unwrap_or_default();
    match command.as_str() {
        "status" => println!("{}", if current > 0 { "ON" } else { "OFF" }),
        "on" | "off" => light.toggle(command == "on", current)?,
        "battery" => {
            let battery = advertising::battery().context("read battery state")?;
            ensure!(
                matches!(
                    battery.status.as_str(),
                    "Charging" | "Discharging" | "Full" | "Not charging" | "Unknown"
                ),
                "invalid battery status"
            );
            println!(
                "{}",
                json!({
                    "capacity": battery.capacity,
                    "charging": battery.status == "Charging",
                    "status": battery.status,
                    "plugged_in": advertising::external_power(),
                })
            );
        }
        "info" => println!(
            "{}",
            serde_json::to_string(&actions::device_info(true).await)?
        ),
        _ => {
            if let Some(value) = command.strip_prefix("level ") {
                if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                    return Ok(2);
                }
                let Ok(level) = value.parse::<u32>() else {
                    return Ok(2);
                };
                if level > light.read_level("max_brightness")? {
                    return Ok(2);
                }
                light.set(level, current)?;
            } else {
                eprintln!("Expected Kindle command: on, off, level, status, battery, or info");
                return Ok(2);
            }
        }
    }
    Ok(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn off_and_on_restore_the_last_level() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path();
        fs::write(path.join("brightness"), "150\n")?;
        fs::write(path.join("max_brightness"), "300\n")?;
        let saved = path.join("saved");
        let light = Frontlight {
            directory: path,
            saved: &saved,
        };
        light.toggle(false, 150)?;
        assert_eq!(light.read_level("brightness")?, 0);
        light.toggle(true, 0)?;
        assert_eq!(light.read_level("brightness")?, 150);
        light.set(200, 150)?;
        assert_eq!(fs::read_to_string(&saved)?, "200\n");
        light.set(0, 200)?;
        assert_eq!(light.read_level("brightness")?, 0);
        assert_eq!(fs::read_to_string(saved)?, "200\n");
        Ok(())
    }
}
