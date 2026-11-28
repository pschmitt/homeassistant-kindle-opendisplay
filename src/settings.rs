use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};

pub const PREVENT_SLEEP: &str = "/opt/opendisplay/prevent-sleep";

#[derive(Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Settings {
    pub autostart: bool,
    pub controls: bool,
    pub frontlight_double_tap: bool,
    pub opendisplay: bool,
    pub battery_advertising: bool,
    pub stay_awake_on_external_power: bool,
    pub cpu_latency_us: i32,
    pub commands: Commands,
    pub updates: Updates,
    pub sleep_after_seconds: u32,
    pub sleep_for_seconds: u32,
    pub full_refresh_every: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Commands {
    pub enabled: bool,
    pub user: String,
}

#[derive(Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct Updates {
    pub require_external_power: bool,
    pub minimum_battery_percent: u8,
}

impl Default for Updates {
    fn default() -> Self {
        Self {
            require_external_power: true,
            minimum_battery_percent: 30,
        }
    }
}

impl Default for Commands {
    fn default() -> Self {
        Self {
            enabled: false,
            user: "nobody".into(),
        }
    }
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            autostart: true,
            controls: true,
            frontlight_double_tap: true,
            opendisplay: true,
            battery_advertising: true,
            stay_awake_on_external_power: true,
            cpu_latency_us: 0,
            commands: Commands::default(),
            updates: Updates::default(),
            sleep_after_seconds: 0,
            sleep_for_seconds: 300,
            full_refresh_every: 10,
        }
    }
}

impl Settings {
    pub fn load(directory: &Path) -> Result<Self> {
        let settings: Self = match fs::read_to_string(directory.join("config.toml")) {
            Ok(data) => toml::from_str(&data).context("invalid config.toml")?,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let latency = fs::read_to_string(directory.join("cpu-latency-us"))
                    .ok()
                    .and_then(|value| value.trim().parse().ok())
                    .filter(|value| matches!(value, 0 | 50))
                    .unwrap_or_default();
                Self {
                    cpu_latency_us: latency,
                    commands: Commands {
                        enabled: directory.join("allow-ble-command").is_file(),
                        ..Commands::default()
                    },
                    ..Self::default()
                }
            }
            Err(error) => return Err(error).context("read config.toml"),
        };
        ensure!(
            matches!(settings.cpu_latency_us, 0 | 50),
            "cpu_latency_us must be 0 or 50"
        );
        ensure!(
            settings.sleep_after_seconds == 0
                || (30..=86400).contains(&settings.sleep_after_seconds),
            "sleep_after_seconds must be 0 or between 30 and 86400"
        );
        ensure!(
            (15..=86400).contains(&settings.sleep_for_seconds),
            "sleep_for_seconds must be between 15 and 86400"
        );
        ensure!(
            settings.full_refresh_every <= 1000,
            "full_refresh_every must be between 0 and 1000"
        );
        ensure!(
            (1..=100).contains(&settings.updates.minimum_battery_percent),
            "updates.minimum_battery_percent must be between 1 and 100"
        );
        ensure!(!settings.commands.user.is_empty(), "commands.user is empty");
        if settings.commands.enabled {
            settings.commands.account()?;
        }
        Ok(settings)
    }
}

pub struct Account {
    pub uid: u32,
    pub gid: u32,
    pub home: String,
}

impl Commands {
    pub fn account(&self) -> Result<Account> {
        let records = fs::read_to_string("/etc/passwd").context("read local users")?;
        for line in records.lines() {
            let fields: Vec<_> = line.split(':').collect();
            if let [name, _, uid, gid, _, home, _] = fields.as_slice()
                && *name == self.user
            {
                let (uid, gid) = (uid.parse()?, gid.parse()?);
                ensure!(
                    uid != 0 && gid != 0,
                    "BLE commands require a non-root account"
                );
                return Ok(Account {
                    uid,
                    gid,
                    home: (*home).to_owned(),
                });
            }
        }
        anyhow::bail!("commands.user is not a local account")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn update_settings_default_and_validate() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let config = directory.path().join("config.toml");
        let defaults = Settings::load(directory.path())?.updates;
        assert!(defaults.require_external_power);
        assert_eq!(defaults.minimum_battery_percent, 30);

        fs::write(&config, "[updates]\nrequire_external_power = false\n")?;
        let updates = Settings::load(directory.path())?.updates;
        assert!(!updates.require_external_power);
        assert_eq!(updates.minimum_battery_percent, 30);

        for invalid in [0, 101] {
            fs::write(
                &config,
                format!("[updates]\nminimum_battery_percent = {invalid}\n"),
            )?;
            assert!(Settings::load(directory.path()).is_err());
        }
        Ok(())
    }
}
