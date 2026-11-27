//! Local operations behind the authenticated Kindle control service.

use crate::{
    control::{Authenticated, Request},
    settings::{Commands, PREVENT_SLEEP},
};
use anyhow::{Context, Result, ensure};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::os::unix::process::CommandExt as _;
use std::{
    collections::HashMap,
    fs::{self, File},
    io,
    net::Ipv4Addr,
    path::Path,
    process::Stdio,
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt as _},
    process::Command,
    task::JoinHandle,
};

const ROOT: &str = "/mnt/us/linux";
const FRONTLIGHT: &str = "/opt/opendisplay/frontlight";
const SSH_WIFI: &str = "/usr/local/bin/ssh-wifi";
const WPA: &str = "/sbin/wpa_cli";
const MAX_STREAM: usize = 128;

pub struct Actions<'a> {
    commands: &'a Commands,
    paperwhite: bool,
    reboot: Option<JoinHandle<()>>,
}

impl<'a> Actions<'a> {
    pub fn new(commands: &'a Commands, paperwhite: bool) -> Self {
        Self {
            commands,
            paperwhite,
            reboot: None,
        }
    }

    pub async fn perform(&mut self, request: &Authenticated) -> Value {
        match &request.request {
            Request::Control(opcode) => match self.control(*opcode, request).await {
                Ok(state) => Value::Array(state),
                Err(error) => {
                    eprintln!("Kindle control request failed: {error:#}");
                    Value::Null
                }
            },
            Request::FrontlightLevel(level) => match self.set_frontlight(*level).await {
                Ok(level) => json!(level),
                Err(error) => {
                    eprintln!("Kindle frontlight request failed: {error:#}");
                    Value::Null
                }
            },
            Request::Command(text) => {
                if !self.commands.enabled {
                    json!({"error": "disabled"})
                } else if text.trim().is_empty() || text.contains('\0') {
                    json!({"error": "invalid"})
                } else {
                    match run_shell(text, self.commands).await {
                        Ok(result) => result,
                        Err(_) => json!({"error": "start_failed"}),
                    }
                }
            }
        }
    }

    async fn set_frontlight(&self, level: u16) -> Result<u16> {
        ensure!(
            self.paperwhite,
            "hardware operations require the Paperwhite transport"
        );
        command(FRONTLIGHT, &[], &format!("level {level}"), 8).await?;
        Ok(level)
    }

    async fn control(&mut self, opcode: u8, request: &Authenticated) -> Result<Vec<Value>> {
        ensure!(
            self.paperwhite,
            "hardware operations require the Paperwhite transport"
        );
        match opcode {
            0 => {}
            1 | 2 => {
                command(FRONTLIGHT, &[], if opcode == 1 { "off" } else { "on" }, 8).await?;
            }
            3 | 4 => {
                let enabled = opcode == 4;
                let action = if enabled { "reassociate" } else { "disconnect" };
                ensure!(
                    command(WPA, &["-i", "wlan0", action], "", 8).await? == "OK",
                    "Wi-Fi command rejected"
                );
                set_marker("wifi.off", !enabled)?;
            }
            5 | 6 => {
                let enabled = opcode == 6;
                command(SSH_WIFI, &[if enabled { "start" } else { "stop" }], "", 8).await?;
                set_marker("ssh-wifi", enabled)?;
            }
            7 | 8 => {
                ensure!(
                    request.encrypted() && Path::new(ROOT).join("BOOT_OWN").is_file(),
                    "boot selection unavailable"
                );
                ensure!(
                    self.reboot.as_ref().is_none_or(JoinHandle::is_finished),
                    "reboot already scheduled"
                );
            }
            10 | 11 => {
                ensure!(
                    request.telemetry_fields() >= 18,
                    "missing diagnostic protocol version"
                );
                set_file(Path::new(PREVENT_SLEEP), opcode == 11)?;
            }
            _ => anyhow::bail!("unknown Kindle control"),
        }
        let mut state = telemetry().await?;
        if request.telemetry_fields() == 19 {
            state.push(diagnostics());
        } else {
            state.truncate(request.telemetry_fields());
        }
        if matches!(opcode, 7 | 8) {
            self.reboot = Some(tokio::spawn(async move {
                if let Err(error) = reboot(opcode == 8).await {
                    eprintln!("Kindle reboot failed: {error:#}");
                }
            }));
        }
        Ok(state)
    }
}

fn set_marker(name: &str, present: bool) -> io::Result<()> {
    set_file(&Path::new(ROOT).join(name), present)
}

fn set_file(path: &Path, present: bool) -> io::Result<()> {
    if present {
        File::options()
            .create(true)
            .truncate(false)
            .write(true)
            .open(path)?;
    } else if let Err(error) = fs::remove_file(path)
        && error.kind() != io::ErrorKind::NotFound
    {
        return Err(error);
    }
    Ok(())
}

async fn reboot(stock: bool) -> Result<()> {
    tokio::time::sleep(Duration::from_secs(5)).await;
    let prior = Path::new(ROOT).join("STOCK_ONCE").exists();
    set_marker("STOCK_ONCE", stock)?;
    // SAFETY: sync takes no pointers and has no caller-specific preconditions.
    unsafe { libc::sync() };
    let result = command("/usr/local/bin/kindle", &["/sbin/reboot"], "", 8).await;
    if result.is_err() {
        set_marker("STOCK_ONCE", prior)?;
        // SAFETY: sync takes no pointers and has no caller-specific preconditions.
        unsafe { libc::sync() };
    }
    result.map(|_| ())
}

async fn command(path: &str, args: &[&str], action: &str, seconds: u64) -> Result<String> {
    let output = tokio::time::timeout(
        Duration::from_secs(seconds),
        Command::new(path)
            .args(args)
            .env("SSH_ORIGINAL_COMMAND", action)
            .kill_on_drop(true)
            .output(),
    )
    .await??;
    ensure!(output.status.success(), "{path} returned {}", output.status);
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

fn read(path: &str) -> Option<String> {
    fs::read_to_string(path)
        .ok()
        .map(|text| text.trim().to_owned())
}

async fn telemetry() -> Result<Vec<Value>> {
    let crate::advertising::Battery {
        capacity,
        status: charge,
    } = crate::advertising::battery().context("read battery state")?;
    ensure!(
        matches!(
            charge.as_str(),
            "Charging" | "Discharging" | "Full" | "Not charging" | "Unknown"
        ),
        "invalid battery status"
    );
    let light = read("/sys/class/backlight/bl/brightness")
        .context("read frontlight")?
        .parse::<u32>()?;
    let wifi = !Path::new(ROOT).join("wifi.off").exists();
    let status = if wifi {
        command(WPA, &["-i", "wlan0", "status"], "", 2)
            .await
            .unwrap_or_default()
    } else {
        String::new()
    };
    let status: HashMap<_, _> = status
        .lines()
        .filter_map(|line| line.split_once('='))
        .collect();
    let state = status.get("wpa_state").copied().unwrap_or("unknown");
    let connected = state == "COMPLETED";
    let rssi = if connected {
        command(WPA, &["-i", "wlan0", "signal_poll"], "", 2)
            .await
            .ok()
            .and_then(|text| {
                text.lines()
                    .find_map(|line| line.strip_prefix("RSSI=")?.parse::<i32>().ok())
            })
    } else {
        None
    };
    let ip = status
        .get("ip_address")
        .and_then(|address| address.parse::<Ipv4Addr>().ok());
    let firmware = read("/proc/1/root/etc/prettyversion.txt");
    let firmware = firmware.as_deref().and_then(|text| {
        text.strip_prefix("Kindle ")
            .unwrap_or(text)
            .split_whitespace()
            .next()
    });
    let build = read("/proc/1/root/etc/version.txt");
    let build = build
        .as_deref()
        .and_then(|text| text.lines().next())
        .map(|line| {
            line.strip_prefix("System Software Version: ")
                .unwrap_or(line)
        });
    let alpine = read("/etc/os-release");
    let alpine = alpine.as_deref().and_then(|text| {
        text.lines().find_map(|line| {
            line.strip_prefix("VERSION_ID=")
                .map(|version| version.trim_matches('"'))
        })
    });
    let ssh = command(SSH_WIFI, &["status"], "", 8).await? == "on";
    Ok(vec![
        json!(light > 0),
        json!(capacity),
        json!(charge == "Charging"),
        json!(charge),
        json!(if !wifi {
            "off".into()
        } else if connected {
            "connected".into()
        } else {
            state.to_ascii_lowercase()
        }),
        json!(rssi),
        json!("Kindle Paperwhite 4 (10th generation)"),
        json!(firmware),
        json!(build),
        json!(read("/proc/sys/kernel/osrelease")),
        json!(alpine),
        json!(wifi),
        json!(ssh),
        json!(connected.then(|| status.get("ssid")).flatten()),
        json!(connected.then(|| status.get("bssid")).flatten()),
        json!(connected.then_some(ip).flatten()),
        json!(crate::advertising::external_power()),
        json!(Path::new(PREVENT_SLEEP).is_file()),
    ])
}

fn diagnostics() -> Value {
    let battery = "/sys/class/power_supply/bd71827_bat";
    let reading = |name| read(&format!("{battery}/{name}")).and_then(|s| s.parse::<i64>().ok());
    let backlight = "/sys/class/backlight/bl";
    let light = |name| read(&format!("{backlight}/{name}")).and_then(|s| s.parse::<u16>().ok());
    let uptime =
        read("/proc/uptime").and_then(|text| text.split_whitespace().next()?.parse::<f64>().ok());
    let wake = read("/run/opendisplay-last-wake")
        .and_then(|text| serde_json::from_str::<Value>(&text).ok());
    json!([
        crate::advertising::cpu_temperature().map(|temp| f64::from(temp) / 1000.0),
        reading("temp"),
        reading("voltage_now"),
        reading("current_now"),
        reading("current_avg"),
        reading("charge_now"),
        reading("charge_full"),
        reading("charge_full_design"),
        reading("battery_cycle"),
        read(&format!("{battery}/health")),
        light("actual_brightness"),
        light("max_brightness"),
        uptime,
        uptime
            .zip(monotonic_seconds())
            .map(|(boot, monotonic)| (boot - monotonic).max(0.0)),
        wake,
    ])
}

fn monotonic_seconds() -> Option<f64> {
    let mut value = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: value is an initialized, writable timespec.
    let status = unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut value) };
    (status == 0).then(|| value.tv_sec as f64 + (value.tv_nsec as f64 / 1e9))
}

struct ProcessGroup(i32);

impl Drop for ProcessGroup {
    fn drop(&mut self) {
        // SAFETY: The positive PID comes from our child that created a new
        // process group. Negating it targets that group without using pointers.
        unsafe { libc::kill(-self.0, libc::SIGKILL) };
    }
}

async fn drain(mut stream: impl AsyncRead + Unpin, output: &mut Vec<u8>) -> io::Result<()> {
    let mut chunk = [0; 4096];
    loop {
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Ok(());
        }
        output.extend_from_slice(&chunk[..count.min(MAX_STREAM + 1 - output.len())]);
    }
}

async fn run_shell(text: &str, settings: &Commands) -> Result<Value> {
    let account = settings.account()?;
    let mut command = Command::new("/bin/sh");
    command.as_std_mut().process_group(0);
    let mut child = command
        .args(["-c", text])
        .uid(account.uid)
        .gid(account.gid)
        .current_dir("/tmp")
        .env_clear()
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        .env("HOME", account.home)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn()?;
    let group = ProcessGroup(child.id().context("missing child PID")?.try_into()?);
    let stdout = child.stdout.take().context("missing child stdout")?;
    let stderr = child.stderr.take().context("missing child stderr")?;
    let (mut out, mut err) = (Vec::new(), Vec::new());
    let result = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::try_join!(
            child.wait(),
            drain(stdout, &mut out),
            drain(stderr, &mut err)
        )
    })
    .await;
    drop(group);
    let timed_out = result.is_err();
    let code = match result {
        Ok(result) => result?.0.code(),
        Err(_) => {
            child.wait().await?;
            None
        }
    };
    let truncated = out.len() > MAX_STREAM || err.len() > MAX_STREAM;
    out.truncate(MAX_STREAM);
    err.truncate(MAX_STREAM);
    Ok(json!({
        "stdout": STANDARD.encode(out),
        "stderr": STANDARD.encode(err),
        "exit_code": code,
        "timed_out": timed_out,
        "truncated": truncated,
    }))
}
