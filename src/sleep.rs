//! Supervise the Paperwhite receiver across timed suspend cycles.

use crate::{actions::WIFI_OFF, advertising, settings::Settings};
use anyhow::{Context, Result, ensure};
use std::{
    fs::{self, File, OpenOptions, TryLockError},
    io,
    os::unix::process::{CommandExt as _, ExitStatusExt as _},
    path::Path,
    process::{Command as StdCommand, Stdio},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{
    process::{Child, Command},
    signal::unix::{Signal, SignalKind, signal},
    time::{sleep, timeout},
};

pub const SESSION_LOCK: &str = "/run/opendisplay-session.lock";
const WAKE_RECORD: &str = "/run/opendisplay-last-wake";
const RTC: &str = "/sys/class/rtc/rtc1";
const FRAME: &str = "frame.bin";
const RECEIVER_ARGS: [&str; 4] = ["kindle-pw4", "device.json", FRAME, "--render"];
const WIFI_PID: &str = "/run/udhcpc.wlan0.pid";
const SESSION_GRACE: Duration = Duration::from_secs(8);

pub async fn supervise() -> Result<()> {
    let settings = Settings::load(Path::new("."))?;
    let executable = std::env::current_exe()?;
    if settings.sleep_after_seconds == 0 || !settings.opendisplay {
        let error = StdCommand::new(executable).args(RECEIVER_ARGS).exec();
        return Err(error).context("start OpenDisplay receiver");
    }

    let mut terminate = signal(SignalKind::terminate())?;
    let mut interrupt = signal(SignalKind::interrupt())?;
    let mut sleep_failed = false;
    loop {
        tokio::select! {
            biased;
            _ = stop_requested(&mut terminate, &mut interrupt) => return Ok(()),
            _ = std::future::ready(()) => {}
        }
        let mut receiver = Command::new(&executable)
            .args(RECEIVER_ARGS)
            .stdin(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .context("start OpenDisplay receiver")?;
        let gate = loop {
            let gate = tokio::select! {
                biased;
                _ = stop_requested(&mut terminate, &mut interrupt) => {
                    stop_receiver(&mut receiver).await?;
                    return Ok(());
                }
                status = receiver.wait() => {
                    let status = status?;
                    if !status.success() {
                        std::process::exit(status.code().unwrap_or_else(|| 128 + status.signal().unwrap_or(0)));
                    }
                    return Ok(());
                }
                gate = idle_gate(&settings), if !sleep_failed => gate,
            };
            match gate {
                Ok(gate) => break gate,
                Err(error) => {
                    eprintln!("OpenDisplay timed suspend disabled: {error:#}");
                    sleep_failed = true;
                }
            }
        };
        if !stop_receiver(&mut receiver).await? {
            eprintln!("OpenDisplay receiver did not stop cleanly; disabling timed suspend");
            sleep_failed = true;
            continue;
        }

        tokio::select! {
            biased;
            _ = stop_requested(&mut terminate, &mut interrupt) => return Ok(()),
            _ = std::future::ready(()) => {}
        }
        let seconds = settings.sleep_for_seconds;
        let keep_awake_on_power = settings.stay_awake_on_external_power;
        // Keep the exclusive connection gate until the radio is off and the system has
        // resumed. Never cancel a power operation after arming the RTC.
        let resumed = tokio::task::spawn_blocking(move || {
            let _gate = gate;
            suspend(seconds, keep_awake_on_power)
        })
        .await?;
        match resumed {
            Ok(true) => {
                if let Err(error) = restore_wifi().await {
                    eprintln!("OpenDisplay Wi-Fi recovery failed: {error:#}");
                    sleep_failed = true;
                }
            }
            Ok(false) => {}
            Err(error) => {
                eprintln!("OpenDisplay timed suspend disabled: {error:#}");
                sleep_failed = true;
            }
        }
    }
}

async fn stop_requested(terminate: &mut Signal, interrupt: &mut Signal) {
    tokio::select! {
        _ = terminate.recv() => {}
        _ = interrupt.recv() => {}
    }
}

async fn stop_receiver(receiver: &mut Child) -> Result<bool> {
    if let Some(pid) = receiver.id() {
        terminate_pid(i32::try_from(pid)?)?;
    }
    match timeout(Duration::from_secs(8), receiver.wait()).await {
        Ok(status) => Ok(status?.success()),
        Err(_) => {
            receiver.kill().await?;
            Ok(false)
        }
    }
}

fn terminate_pid(pid: i32) -> io::Result<()> {
    // SAFETY: Only a checked positive PID is targeted; no pointers are passed.
    if pid <= 1 {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid PID"));
    }
    let result = unsafe { libc::kill(pid, libc::SIGTERM) };
    if result == 0 {
        return Ok(());
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(error)
    }
}

fn frame_stamp() -> io::Result<Option<SystemTime>> {
    match fs::metadata(FRAME) {
        Ok(metadata) => metadata.modified().map(Some),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error),
    }
}

fn sleep_allowed(keep_awake_on_power: bool) -> bool {
    !crate::update::inhibits_sleep()
        && !Path::new(crate::settings::PREVENT_SLEEP).exists()
        && (!keep_awake_on_power || advertising::external_power() == Some(false))
}

async fn idle_gate(settings: &Settings) -> Result<File> {
    let delay = Duration::from_secs(settings.sleep_after_seconds.into());
    let mut stamp = frame_stamp()?;
    let mut idle_since = Instant::now();
    loop {
        let updated = frame_stamp()?;
        if updated != stamp {
            stamp = updated;
            idle_since = Instant::now();
        }
        if idle_since.elapsed() >= delay
            && sleep_allowed(settings.stay_awake_on_external_power)
            && let Some(gate) = try_session_gate()?
        {
            return Ok(gate);
        }
        sleep(Duration::from_secs(1)).await;
    }
}

fn try_session_gate() -> Result<Option<File>> {
    let gate = OpenOptions::new()
        .create(true)
        .append(true)
        .open(SESSION_LOCK)?;
    match gate.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => return Ok(None),
        Err(error) => return Err(error).context("lock OpenDisplay session for suspend"),
    }
    let modified = gate.metadata()?.modified()?;
    Ok(modified
        .elapsed()
        .ok()
        .filter(|age| *age >= SESSION_GRACE)
        .map(|_| gate))
}

fn suspend(seconds: u32, keep_awake_on_power: bool) -> Result<bool> {
    if !sleep_allowed(keep_awake_on_power) {
        return Ok(false);
    }
    let rtc = Path::new(RTC);
    ensure!(
        fs::read_to_string(rtc.join("device/power/wakeup"))?.trim() == "enabled",
        "SNVS RTC wake is disabled"
    );
    let alarm = rtc.join("wakealarm");
    ensure!(
        fs::read_to_string(&alarm)?.trim().is_empty(),
        "SNVS RTC already has an alarm"
    );
    let deadline = fs::read_to_string(rtc.join("since_epoch"))?
        .trim()
        .parse::<u64>()?
        + u64::from(seconds);
    fs::write(&alarm, format!("{deadline}\n"))?;
    let result = (|| {
        ensure!(
            fs::read_to_string(&alarm)?.trim().parse::<u64>()? == deadline,
            "SNVS RTC did not accept the wake alarm"
        );
        if !sleep_allowed(keep_awake_on_power) {
            return Ok(false);
        }
        eprintln!("OpenDisplay entering timed suspend");
        let before = uptime()?;
        let awake = Instant::now();
        fs::write("/sys/power/state", "mem\n")?;
        let suspended = uptime()? - before - awake.elapsed().as_secs_f64();
        eprintln!("OpenDisplay resumed after {suspended:.2}s suspended");
        if suspended >= 1.0 {
            let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
            let staged = Path::new(WAKE_RECORD).with_extension("tmp");
            fs::write(
                &staged,
                serde_json::to_vec(&(timestamp, (suspended * 100.0).round() / 100.0))?,
            )?;
            fs::rename(staged, WAKE_RECORD)?;
        }
        Ok(true)
    })();
    let cleared = fs::write(&alarm, "0\n").context("clear RTC wake alarm");
    let resumed = result?;
    cleared?;
    Ok(resumed)
}

fn uptime() -> Result<f64> {
    Ok(fs::read_to_string("/proc/uptime")?
        .split_whitespace()
        .next()
        .context("missing kernel uptime")?
        .parse()?)
}

async fn restore_wifi() -> Result<()> {
    if Path::new(WIFI_OFF).exists() || !Path::new("/sys/class/net/wlan0").exists() {
        return Ok(());
    }
    if has_ipv4().await? {
        return Ok(());
    }
    renew_wifi_dhcp().await
}

pub(crate) async fn renew_wifi_dhcp() -> Result<()> {
    match fs::read_to_string(WIFI_PID) {
        Ok(pid) => {
            let pid: i32 = pid.trim().parse().context("read Wi-Fi DHCP PID")?;
            let comm = format!("/proc/{pid}/comm");
            match fs::read_to_string(&comm) {
                Ok(name) => {
                    ensure!(
                        name.trim() == "udhcpc",
                        "Wi-Fi DHCP PID belongs to a different process"
                    );
                    terminate_pid(pid)?;
                    timeout(Duration::from_secs(2), async {
                        while Path::new(&comm).exists() {
                            sleep(Duration::from_millis(100)).await;
                        }
                    })
                    .await
                    .context("previous Wi-Fi DHCP client did not exit")?;
                }
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error).context("identify Wi-Fi DHCP process"),
            }
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {}
        Err(error) => return Err(error).context("read Wi-Fi DHCP PID file"),
    }
    let status = timeout(
        Duration::from_secs(10),
        Command::new("udhcpc")
            .args(["-i", "wlan0", "-b", "-S", "-p", WIFI_PID])
            .stdin(Stdio::null())
            .kill_on_drop(true)
            .status(),
    )
    .await??;
    ensure!(status.success(), "Wi-Fi DHCP client failed");
    Ok(())
}

pub(crate) async fn has_ipv4() -> Result<bool> {
    let output = timeout(
        Duration::from_secs(5),
        Command::new("ip")
            .args(["-4", "addr", "show", "dev", "wlan0"])
            .kill_on_drop(true)
            .output(),
    )
    .await??;
    ensure!(
        output.status.success(),
        "could not inspect Wi-Fi IPv4 address"
    );
    Ok(String::from_utf8_lossy(&output.stdout).contains("inet "))
}
