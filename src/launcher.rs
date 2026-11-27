//! Own the panel until the receiver exits or the launcher is stopped.

use crate::{settings::Settings, setup};
use anyhow::{Context, Result, bail, ensure};
use std::{ffi::OsString, fs, io, os::unix::process::ExitStatusExt as _, path::Path};
use tokio::{
    process::Command,
    signal::unix::{SignalKind, signal},
};

const LOCK: &str = "/run/opendisplay-mode.lock";

#[derive(Default)]
struct Display {
    home_pid: Option<i32>,
}

impl Display {
    fn acquire() -> Result<Self> {
        fs::create_dir(LOCK).context("acquire OpenDisplay mode lock")?;
        Ok(Self::default())
    }

    async fn pause_home(&mut self) -> Result<()> {
        if self.home_pid.is_none() {
            let result = Command::new("pidof").args(["-s", "home"]).output().await?;
            ensure!(
                result.status.success(),
                "OpenDisplay requires a running Inkwell Home process"
            );
            let pid = std::str::from_utf8(&result.stdout)?.trim().parse()?;
            send_signal(pid, libc::SIGSTOP)?;
            self.home_pid = Some(pid);
        }
        Ok(())
    }

    fn resume_home(&mut self) {
        if let Some(pid) = self.home_pid.take()
            && fs::read_to_string(format!("/proc/{pid}/comm"))
                .is_ok_and(|name| name.trim() == "home")
            && let Err(error) = send_signal(pid, libc::SIGCONT)
        {
            eprintln!("Resume Inkwell Home: {error}");
        }
    }
}

impl Drop for Display {
    fn drop(&mut self) {
        self.resume_home();
        if let Err(error) = fs::remove_dir(LOCK) {
            eprintln!("Remove OpenDisplay mode lock: {error}");
        }
    }
}

fn send_signal(pid: i32, signal: libc::c_int) -> io::Result<()> {
    if pid <= 1 {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid PID"));
    }
    // SAFETY: pid is positive and signal is a valid signal number.
    if unsafe { libc::kill(pid, signal) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

pub async fn launch(args: impl IntoIterator<Item = OsString>) -> Result<i32> {
    let mut args = args.into_iter();
    let mode = args.next();
    let (manual, exclusive) = match mode.as_deref().and_then(|mode| mode.to_str()) {
        None if mode.is_none() => (false, false),
        Some("--manual") => (true, false),
        Some("--boot-exclusive") => (false, true),
        _ => bail!("usage: start [--manual|--boot-exclusive]"),
    };
    ensure!(
        args.next().is_none(),
        "usage: start [--manual|--boot-exclusive]"
    );
    let directory = Path::new(setup::DIRECTORY);
    if !manual && !Settings::load(directory)?.autostart {
        return Ok(0);
    }
    let mut terminate = signal(SignalKind::terminate())?;
    let mut interrupt = signal(SignalKind::interrupt())?;
    let mut reload = signal(SignalKind::hangup())?;
    let mut display = Display::acquire()?;
    setup::provision(directory)?;
    let receiver = directory.join("kindle-opendisplay");
    loop {
        let enabled = Settings::load(directory)?.opendisplay;
        if enabled && !exclusive {
            display.pause_home().await?;
        } else if !enabled {
            if exclusive {
                return Ok(0);
            }
            display.resume_home();
        }

        let mut child = Command::new(&receiver)
            .current_dir(directory)
            .arg("--supervise")
            .kill_on_drop(true)
            .spawn()
            .context("start OpenDisplay supervisor")?;
        let restarting = tokio::select! {
            biased;
            _ = terminate.recv() => false,
            _ = interrupt.recv() => false,
            _ = reload.recv() => true,
            status = child.wait() => {
                let status = status?;
                return Ok(status.code().unwrap_or_else(|| 128 + status.signal().unwrap_or(0)));
            }
        };
        if let Some(pid) = child.id()
            && let Err(error) = send_signal(i32::try_from(pid)?, libc::SIGTERM)
            && error.raw_os_error() != Some(libc::ESRCH)
        {
            return Err(error).context("stop OpenDisplay supervisor");
        }
        child.wait().await?;
        if !restarting {
            return Ok(0);
        }
    }
}
