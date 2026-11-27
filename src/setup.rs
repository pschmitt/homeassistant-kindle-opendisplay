use crate::settings::Settings;
use anyhow::{Context, Result, bail, ensure};
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::Command;
use tempfile::NamedTempFile;

pub const DIRECTORY: &str = "/opt/opendisplay";
const HOOK: &str = include_str!("../opendisplay/boot-hook.sh");
const PREVIOUS_HOOK: &str = include_str!("../opendisplay/previous-boot-hook.sh");
const LEGACY_HOOK: &str = include_str!("../opendisplay/legacy-boot-hook.sh");
const MARKER: &str = "\ncrashes=0\n";

fn patch_init(init: &str) -> Result<String> {
    if init.contains(HOOK) {
        return Ok(init.to_owned());
    }
    let older = LEGACY_HOOK
        .replace(
            "after Inkwell rearms its boot marker",
            "after home has passed Inkwell's boot re-arm checkpoint",
        )
        .replace("[ -d /sys/class/power_supply/bd71827_bat ] && ", "");
    let clean = [PREVIOUS_HOOK, LEGACY_HOOK, &older]
        .into_iter()
        .fold(init.to_owned(), |text, hook| text.replace(hook, ""));
    ensure!(
        !clean.contains("/opt/opendisplay/autostart"),
        "unrecognized OpenDisplay boot hook"
    );
    ensure!(
        clean.matches(MARKER).count() == 1,
        "Inkwell init lacks a unique boot hook location"
    );
    Ok(clean.replacen(MARKER, &format!("\n{HOOK}crashes=0\n"), 1))
}

fn stage(path: &Path, mode: u32) -> Result<NamedTempFile> {
    let directory = path
        .parent()
        .context("installation path has no directory")?;
    let file = NamedTempFile::new_in(directory)?;
    file.as_file()
        .set_permissions(fs::Permissions::from_mode(mode))?;
    Ok(file)
}

fn write_file(path: &Path, mode: u32, contents: &[u8], replace: bool) -> Result<()> {
    let mut file = stage(path, mode)?;
    file.write_all(contents)?;
    file.as_file().sync_all()?;
    if replace {
        file.persist(path)?;
    } else if let Err(error) = file.persist_noclobber(path)
        && error.error.kind() != ErrorKind::AlreadyExists
    {
        return Err(error.into());
    }
    Ok(())
}

fn install_settings(directory: &Path, latency: Option<i32>) -> Result<()> {
    let path = directory.join("config.toml");
    let mut settings = Settings::load(directory)?;
    if path.try_exists()? && latency.is_none() {
        return Ok(());
    }
    if let Some(latency) = latency {
        settings.cpu_latency_us = latency;
    }
    let contents = format!(
        "# Reload the receiver after editing this file.\n{}",
        toml::to_string_pretty(&settings)?
    );
    write_file(&path, 0o600, contents.as_bytes(), latency.is_some())
}

pub fn provision(directory: &Path) -> Result<()> {
    provision_with_latency(directory, None)
}

fn provision_with_latency(directory: &Path, latency: Option<i32>) -> Result<()> {
    install_settings(directory, latency)?;
    let identity = directory.join("device.json");
    let key = directory.join("control.key");
    if !identity.try_exists()? {
        let mut address = [0; 6];
        File::open("/dev/urandom")?.read_exact(&mut address)?;
        address[0] |= 0xc0;
        let address = address.map(|octet| format!("{octet:02X}")).join(":");
        let config = serde_json::json!({
            "name": "ODKindlePaperwhite4",
            "address": address,
            "advertising_interval_min": 100,
            "advertising_interval_max": 150
        });
        let contents = serde_json::to_string_pretty(&config)? + "\n";
        write_file(&identity, 0o644, contents.as_bytes(), false)?;
    }
    if !key.try_exists()? {
        let mut secret = [0; 32];
        File::open("/dev/urandom")?.read_exact(&mut secret)?;
        let contents = hex::encode(secret) + "\n";
        write_file(&key, 0o600, contents.as_bytes(), false)?;
    }
    fs::set_permissions(key, fs::Permissions::from_mode(0o600))?;
    Ok(())
}

pub fn install(args: impl IntoIterator<Item = OsString>) -> Result<()> {
    let args: Vec<_> = args.into_iter().collect();
    let latency = match args.as_slice() {
        [] => None,
        [flag, value] if flag == "--cpu-latency-us" => match value.to_str() {
            Some("0") => Some(0),
            Some("50") => Some(50),
            _ => bail!("cpu_latency_us must be 0 or 50"),
        },
        _ => bail!("usage: kindle-opendisplay --install [--cpu-latency-us 0|50]"),
    };
    let init = Path::new("/sbin/own-init");
    // SAFETY: geteuid has no arguments or memory preconditions.
    let root = unsafe { libc::geteuid() } == 0;
    ensure!(
        root && init.is_file()
            && Path::new("/mnt/us/linux/boot.sh").is_file()
            && Path::new("/dev/ttymxc2").exists()
            && Path::new("/sys/bus/platform/devices/2034000.serial").is_dir(),
        "run this as root on the Inkwell Kindle Paperwhite 4"
    );
    install_into(
        init,
        Path::new(DIRECTORY),
        &std::env::current_exe()?,
        latency,
    )?;
    println!("OpenDisplay installed for the next Inkwell boot.");
    println!(
        "Copy {DIRECTORY}/control.key securely to Home Assistant to configure Kindle controls."
    );
    Ok(())
}

fn install_into(init: &Path, directory: &Path, source: &Path, latency: Option<i32>) -> Result<()> {
    let original = fs::read_to_string(init).context("read Inkwell init")?;
    let patched = patch_init(&original)?;
    let init_mode = fs::metadata(init)?.permissions().mode();
    let mut staged_init = stage(init, init_mode)?;
    staged_init.write_all(patched.as_bytes())?;
    staged_init.as_file().sync_all()?;
    ensure!(
        Command::new("/bin/sh")
            .arg("-n")
            .arg(staged_init.path())
            .status()?
            .success(),
        "invalid patched Inkwell init"
    );

    fs::create_dir_all(directory)?;
    provision_with_latency(directory, latency)?;
    let binary = directory.join("kindle-opendisplay");
    let mut staged_binary = stage(&binary, 0o755)?;
    std::io::copy(&mut File::open(source)?, &mut staged_binary)?;
    staged_binary.as_file().sync_all()?;
    staged_binary.persist(&binary)?;
    for (name, contents) in [
        ("start", include_bytes!("../opendisplay/start").as_slice()),
        (
            "frontlight",
            include_bytes!("../opendisplay/frontlight").as_slice(),
        ),
    ] {
        write_file(&directory.join(name), 0o755, contents, true)?;
    }
    if patched != original {
        write_file(
            &init.with_extension("pre-opendisplay"),
            init_mode,
            original.as_bytes(),
            false,
        )?;
        staged_init.persist(init)?;
    }
    OpenOptions::new()
        .append(true)
        .create(true)
        .open(directory.join("autostart"))?;
    Ok(())
}

pub fn setting(feature: &str) -> Result<bool> {
    let settings = Settings::load(Path::new(DIRECTORY))?;
    match feature {
        "autostart" => Ok(settings.autostart),
        "opendisplay" => Ok(settings.opendisplay),
        "stay_awake_on_external_power" => Ok(settings.stay_awake_on_external_power),
        _ => bail!("unknown OpenDisplay feature"),
    }
}

pub fn launch(args: impl IntoIterator<Item = OsString>) -> Result<()> {
    for signal in [libc::SIGHUP, libc::SIGINT, libc::SIGTERM] {
        // SAFETY: the signal numbers are valid and SIG_DFL is a permitted disposition.
        let previous = unsafe { libc::signal(signal, libc::SIG_DFL) };
        ensure!(
            previous != libc::SIG_ERR,
            "restore launcher signal disposition"
        );
    }
    Err(Command::new(Path::new(DIRECTORY).join("start"))
        .args(args)
        .env("OPENDISPLAY_SIGNALS_READY", "1")
        .exec())
    .context("start OpenDisplay")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn boot_hook_replaces_known_versions_and_rejects_unknown_hooks() -> Result<()> {
        let fresh = "#!/bin/sh\ncrashes=0\n";
        let patched = patch_init(fresh)?;
        assert_eq!(patch_init(&patched)?, patched);
        for old in [PREVIOUS_HOOK, LEGACY_HOOK] {
            assert_eq!(
                patch_init(&format!("#!/bin/sh\n{old}crashes=0\n"))?,
                patched
            );
        }
        assert!(patch_init("#/opt/opendisplay/autostart\ncrashes=0\n").is_err());
        assert!(patch_init("#!/bin/sh\n").is_err());
        Ok(())
    }

    #[test]
    fn installer_upgrades_legacy_init_and_keeps_the_rollback() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let root = directory.path();
        let init = root.join("own-init");
        let target = root.join("opendisplay");
        let receiver = root.join("receiver");
        let before = format!("#!/bin/sh\n{PREVIOUS_HOOK}crashes=0\n");
        fs::write(&init, &before)?;
        fs::set_permissions(&init, fs::Permissions::from_mode(0o751))?;
        fs::write(&receiver, b"receiver image")?;
        install_into(&init, &target, &receiver, Some(50))?;
        assert_eq!(fs::read_to_string(&init)?, patch_init(&before)?);
        assert_eq!(
            fs::read_to_string(init.with_extension("pre-opendisplay"))?,
            before
        );
        assert_eq!(fs::metadata(&init)?.permissions().mode() & 0o777, 0o751);
        assert_eq!(
            fs::read(target.join("kindle-opendisplay"))?,
            b"receiver image"
        );
        assert!(target.join("start").is_file());
        assert!(target.join("autostart").is_file());
        assert_eq!(Settings::load(&target)?.cpu_latency_us, 50);

        let installed = target.join("kindle-opendisplay");
        install_into(&init, &target, &installed, None)?;
        assert_eq!(fs::read(&installed)?, b"receiver image");
        assert_eq!(
            fs::read_to_string(init.with_extension("pre-opendisplay"))?,
            before
        );
        Ok(())
    }

    #[test]
    fn provisioning_preserves_identity_and_migrates_config() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path();
        fs::write(path.join("cpu-latency-us"), "50\n")?;
        provision(path)?;
        let identity = fs::read(path.join("device.json"))?;
        let key = fs::read(path.join("control.key"))?;
        assert_eq!(hex::decode(std::str::from_utf8(&key)?.trim())?.len(), 32);
        assert_eq!(
            fs::metadata(path.join("control.key"))?.permissions().mode() & 0o777,
            0o600
        );
        assert_eq!(Settings::load(path)?.cpu_latency_us, 50);
        let config = b"# preserve this comment\ncpu_latency_us = 50\n";
        fs::write(path.join("config.toml"), config)?;
        provision(path)?;
        assert_eq!(fs::read(path.join("device.json"))?, identity);
        assert_eq!(fs::read(path.join("control.key"))?, key);
        assert_eq!(fs::read(path.join("config.toml"))?, config);
        Ok(())
    }
}
