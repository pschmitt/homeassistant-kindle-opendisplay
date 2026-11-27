//! Paperwhite frontlight and the legacy forced SSH command.

use crate::{actions, advertising};
use anyhow::{Context, Result, ensure};
use serde_json::json;
use std::{fs, io::Write as _, path::Path};

const BACKLIGHT: &str = "/sys/class/backlight/bl";
const SAVED_LEVEL: &str = "/opt/opendisplay/frontlight-level";
const ACTIVE_LEVEL: &str = "/opt/opendisplay/frontlight-active-level";
const BOOST_STATE: &str = "/run/opendisplay-frontlight-boost";
const LOCK: &str = "/run/opendisplay-frontlight.lock";

struct Frontlight<'a> {
    directory: &'a Path,
    saved: &'a Path,
    active: &'a Path,
    boost: &'a Path,
    lock: &'a Path,
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

    fn remember_active(&self, level: u32) -> Result<()> {
        let directory = self.active.parent().context("frontlight state directory")?;
        let mut staged = tempfile::NamedTempFile::new_in(directory)?;
        writeln!(staged, "{level}")?;
        staged.as_file().sync_all()?;
        staged.persist(self.active)?;
        fs::File::open(directory)?.sync_all()?;
        Ok(())
    }

    fn restore(&self) -> Result<()> {
        let value = match fs::read_to_string(self.active) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(error.into()),
        };
        let level = value.trim().parse()?;
        ensure!(
            level <= self.read_level("max_brightness")?,
            "invalid persisted brightness"
        );
        if level != self.read_level("brightness")? {
            self.apply(level)?;
        }
        Ok(())
    }

    fn lock(&self) -> Result<fs::File> {
        let lock = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.lock)?;
        lock.lock()?;
        Ok(lock)
    }

    fn cancel_boost(&self) -> Result<()> {
        let text = match fs::read_to_string(self.boost) {
            Ok(text) => text,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(error) => return Err(error.into()),
        };
        let (previous, applied) = text.split_once(' ').context("invalid frontlight boost")?;
        if self.read_level("brightness")? == applied.trim().parse::<u32>()? {
            self.apply(previous.parse()?)?;
        }
        fs::remove_file(self.boost)?;
        Ok(())
    }

    fn start_boost(&self) -> Result<()> {
        let _lock = self.lock()?;
        if self.boost.is_file() {
            return Ok(());
        }
        let previous = self.read_level("brightness")?;
        let level = self.read_level("max_brightness")?.div_ceil(2);
        fs::write(self.boost, format!("{previous} {level}\n"))?;
        if let Err(error) = self.apply(level) {
            fs::remove_file(self.boost)?;
            return Err(error);
        }
        Ok(())
    }

    fn set(&self, requested: u32) -> Result<()> {
        let _lock = self.lock()?;
        self.cancel_boost()?;
        let current = self.read_level("brightness")?;
        if requested == 0 && current > 0 {
            self.save(current)?;
        }
        self.apply(requested)?;
        if requested > 0 {
            self.save(requested)?;
        }
        self.remember_active(requested)
    }

    fn toggle(&self, enabled: bool) -> Result<()> {
        let _lock = self.lock()?;
        self.cancel_boost()?;
        let current = self.read_level("brightness")?;
        let mut applied = current;
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
            applied = level;
        } else if !enabled && current > 0 {
            self.save(current)?;
            self.apply(0)?;
            applied = 0;
        }
        self.remember_active(applied)
    }
}

fn device() -> Frontlight<'static> {
    Frontlight {
        directory: Path::new(BACKLIGHT),
        saved: Path::new(SAVED_LEVEL),
        active: Path::new(ACTIVE_LEVEL),
        boost: Path::new(BOOST_STATE),
        lock: Path::new(LOCK),
    }
}

pub fn restore() -> Result<()> {
    let light = device();
    let _lock = light.lock()?;
    light.cancel_boost()?;
    light.restore()
}

pub struct Boost {
    _wake_lock: fs::File,
}

impl Boost {
    pub fn begin() -> Result<Self> {
        let wake_lock = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(crate::sleep::SESSION_LOCK)?;
        wake_lock
            .try_lock_shared()
            .context("Kindle is preparing to suspend")?;
        device().start_boost()?;
        Ok(Self {
            _wake_lock: wake_lock,
        })
    }

    pub fn renew(&self) -> Result<()> {
        device().start_boost()
    }
}

impl Drop for Boost {
    fn drop(&mut self) {
        let light = device();
        if let Err(error) = light.lock().and_then(|_lock| light.cancel_boost()) {
            eprintln!("Restore frontlight after double-tap: {error:#}");
        }
    }
}

pub fn set(level: u16) -> Result<()> {
    let light = device();
    ensure!(
        u32::from(level) <= light.read_level("max_brightness")?,
        "invalid brightness"
    );
    light.set(level.into())
}

pub fn toggle(enabled: bool) -> Result<()> {
    let light = device();
    light.toggle(enabled)
}

pub async fn forced_command() -> Result<i32> {
    let light = device();
    let current = light.read_level("brightness")?;
    let command = std::env::var("SSH_ORIGINAL_COMMAND").unwrap_or_default();
    match command.as_str() {
        "status" => println!("{}", if current > 0 { "ON" } else { "OFF" }),
        "on" | "off" => light.toggle(command == "on")?,
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
                light.set(level)?;
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
        let active = path.join("active");
        let boost = path.join("boost");
        let lock = path.join("lock");
        let light = Frontlight {
            directory: path,
            saved: &saved,
            active: &active,
            boost: &boost,
            lock: &lock,
        };
        light.restore()?;
        assert_eq!(light.read_level("brightness")?, 150);
        light.toggle(false)?;
        assert_eq!(light.read_level("brightness")?, 0);
        light.toggle(true)?;
        assert_eq!(light.read_level("brightness")?, 150);
        light.set(200)?;
        assert_eq!(fs::read_to_string(&saved)?, "200\n");
        light.set(0)?;
        assert_eq!(light.read_level("brightness")?, 0);
        assert_eq!(fs::read_to_string(&saved)?, "200\n");
        fs::write(path.join("brightness"), "75\n")?;
        light.restore()?;
        assert_eq!(light.read_level("brightness")?, 0);
        light.toggle(true)?;
        fs::write(path.join("brightness"), "75\n")?;
        light.restore()?;
        assert_eq!(light.read_level("brightness")?, 200);
        light.set(0)?;
        light.start_boost()?;
        assert_eq!(light.read_level("brightness")?, 150);
        assert_eq!(fs::read_to_string(&active)?, "0\n");
        light.cancel_boost()?;
        assert_eq!(light.read_level("brightness")?, 0);
        light.start_boost()?;
        light.toggle(false)?;
        light.cancel_boost()?;
        light.toggle(true)?;
        assert_eq!(light.read_level("brightness")?, 200);
        light.start_boost()?;
        light.set(120)?;
        light.cancel_boost()?;
        assert_eq!(light.read_level("brightness")?, 120);
        Ok(())
    }
}
