use anyhow::{Context, Result, ensure};
use serde::Deserialize;
use std::{fs, path::Path};

pub const PREVENT_SLEEP: &str = "/opt/opendisplay/prevent-sleep";

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Settings {
    pub autostart: bool,
    pub controls: bool,
    pub opendisplay: bool,
    pub battery_advertising: bool,
    pub stay_awake_on_external_power: bool,
    pub cpu_latency_us: i32,
    pub commands: Commands,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Commands {
    pub enabled: bool,
    pub user: String,
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
            opendisplay: true,
            battery_advertising: true,
            stay_awake_on_external_power: true,
            cpu_latency_us: 0,
            commands: Commands::default(),
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
