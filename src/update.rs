//! Fetch, verify and activate a receiver-only release.

use anyhow::{Context, Result, ensure};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions, TryLockError},
    os::unix::fs::PermissionsExt,
    path::Path,
    time::Duration,
};
use tokio::process::Command;

use crate::{advertising, setup::DIRECTORY};

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const MAX_SIZE: u64 = 16 * 1024 * 1024;
const REPOSITORY: &str = "https://github.com/pschmitt/homeassistant-kindle-opendisplay";
const STAGED: &str = ".receiver-next";
const PREVIOUS: &str = ".receiver-previous";
const DOWNLOAD_LOCK: &str = "/run/opendisplay-update.lock";
const BINARY: &str = "kindle-opendisplay";
pub const TRIAL_TIMEOUT: Duration = Duration::from_secs(180);

pub fn parse_version(version: &str) -> Option<[u32; 3]> {
    let mut parts = version.split('.');
    let mut numbers = [0; 3];
    for value in &mut numbers {
        let part = parts.next()?;
        if part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        *value = part.parse().ok()?;
        if value.to_string() != part {
            return None;
        }
    }
    parts.next().is_none().then_some(numbers)
}

pub fn pending(directory: &Path) -> bool {
    directory.join(PREVIOUS).is_file()
}

pub fn ready(directory: &Path) -> bool {
    directory.join(STAGED).is_file()
}

pub fn activate(directory: &Path) -> Result<()> {
    let active = directory.join(BINARY);
    fs::hard_link(&active, directory.join(PREVIOUS)).context("save previous receiver")?;
    File::open(directory)?.sync_all()?;
    fs::rename(directory.join(STAGED), active).context("activate the staged receiver")?;
    File::open(directory)?.sync_all()?;
    Ok(())
}

fn remove_if_present(path: &Path) -> Result<()> {
    match fs::remove_file(path) {
        Err(err) if err.kind() != std::io::ErrorKind::NotFound => Err(err.into()),
        _ => Ok(()),
    }
}

pub fn discard_staged(directory: &Path) -> Result<()> {
    remove_if_present(&directory.join(STAGED))
}

pub fn rollback(directory: &Path) -> Result<()> {
    if pending(directory) {
        // A power loss before activation can leave both paths linked to the
        // same inode. rename then succeeds without unlinking the backup.
        discard_staged(directory)?;
        fs::rename(directory.join(PREVIOUS), directory.join(BINARY))
            .context("restore previous receiver")?;
        remove_if_present(&directory.join(PREVIOUS))?;
        File::open(directory)?.sync_all()?;
    }
    Ok(())
}

pub fn confirm(version: &str) -> Result<()> {
    ensure!(version == VERSION, "running version does not match");
    let directory = Path::new(DIRECTORY);
    remove_if_present(&directory.join(PREVIOUS))?;
    File::open(directory)?.sync_all()?;
    Ok(())
}

pub fn check_request(version: &str) -> Result<()> {
    let requested = parse_version(version).context("invalid release version")?;
    let installed = parse_version(VERSION).context("unversioned receiver")?;
    ensure!(requested > installed, "release is not newer");
    let directory = Path::new(DIRECTORY);
    ensure!(
        !pending(directory) && !ready(directory),
        "update already pending"
    );
    ensure!(
        advertising::external_power() == Some(true),
        "connect the Kindle to external power before updating"
    );
    ensure!(
        Path::new("/run/opendisplay-mode.lock").is_dir(),
        "start the receiver through its launcher"
    );
    Ok(())
}

fn download_lock() -> Result<File> {
    Ok(OpenOptions::new()
        .create(true)
        .append(true)
        .open(DOWNLOAD_LOCK)?)
}

pub fn inhibits_sleep() -> bool {
    let directory = Path::new(DIRECTORY);
    ready(directory)
        || pending(directory)
        || download_lock()
            .is_ok_and(|lock| matches!(lock.try_lock(), Err(TryLockError::WouldBlock)))
}

async fn download(version: &str, asset: &str, path: &Path, max_size: u64) -> Result<()> {
    let url = format!("{REPOSITORY}/releases/download/v{version}/{asset}");
    let result = Command::new("/usr/bin/curl")
        .args([
            "--disable",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-redirs",
            "5",
            "--max-time",
            "45",
            "--connect-timeout",
            "10",
            "--max-filesize",
        ])
        .arg(max_size.to_string())
        .arg("--output")
        .arg(path)
        .arg("--")
        .arg(url)
        .kill_on_drop(true)
        .status()
        .await
        .context("download release")?;
    ensure!(result.success(), "release download failed");
    ensure!(
        fs::metadata(path)?.len() <= max_size,
        "release asset exceeds size limit"
    );
    Ok(())
}

const ASSET: &str = "kindle-opendisplay-armv7";

fn checksum(text: &str) -> Result<[u8; 32]> {
    let mut entries = text.lines().filter_map(|line| {
        let (sum, name) = line.split_once("  ")?;
        (name == ASSET).then_some(sum)
    });
    let hash = entries.next().context("missing ARMv7 checksum")?;
    ensure!(entries.next().is_none(), "duplicate ARMv7 checksums");
    let mut digest = [0; 32];
    hex::decode_to_slice(hash, &mut digest).context("invalid ARMv7 checksum")?;
    Ok(digest)
}

pub async fn fetch(version: &str) -> Result<()> {
    let lock = download_lock()?;
    lock.try_lock().context("another download is running")?;
    check_request(version)?;
    let directory = Path::new(DIRECTORY);
    let sums = tempfile::NamedTempFile::new_in(directory)?;
    download(version, "SHA256SUMS", sums.path(), 4096).await?;
    let digest = checksum(&fs::read_to_string(sums.path())?)?;
    let temporary = tempfile::NamedTempFile::new_in(directory)?;
    download(version, ASSET, temporary.path(), MAX_SIZE).await?;
    let bytes = fs::read(temporary.path())?;
    ensure!(bytes.len() as u64 <= MAX_SIZE, "release exceeds size limit");
    ensure!(
        <[u8; 32]>::from(Sha256::digest(&bytes)) == digest,
        "release digest mismatch"
    );
    temporary
        .as_file()
        .set_permissions(fs::Permissions::from_mode(0o755))?;
    let output = tokio::time::timeout(
        Duration::from_secs(5),
        Command::new(temporary.path())
            .arg("--version")
            .kill_on_drop(true)
            .output(),
    )
    .await??;
    ensure!(
        output.status.success()
            && std::str::from_utf8(&output.stdout)?.trim()
                == format!("kindle-opendisplay {version}"),
        "release binary reported an unexpected version"
    );
    temporary.as_file().sync_all()?;
    temporary.persist_noclobber(directory.join(STAGED))?;
    File::open(directory)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_versions_are_canonical_and_cannot_form_paths() {
        assert_eq!(parse_version("0.10.1"), Some([0, 10, 1]));
        for invalid in ["../0.9.1", "0.09.1", "0.9", "0.9.1-rc", "v0.9.1", "+0.9.1"] {
            assert_eq!(parse_version(invalid), None);
        }
    }

    #[test]
    fn checksum_is_for_the_exact_binary_and_rejects_duplicates() -> Result<()> {
        let checksums = format!("{}  {ASSET}\n", "ab".repeat(32));
        assert_eq!(checksum(&checksums)?, [0xab; 32]);
        assert!(checksum(&checksums.replace(ASSET, "another-file")).is_err());
        assert!(checksum(&checksums.repeat(2)).is_err());
        Ok(())
    }

    #[test]
    fn a_trial_can_be_rolled_back_and_partial_activation_is_safe() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path();
        fs::write(path.join(BINARY), b"previous")?;
        fs::write(path.join(STAGED), b"next")?;
        activate(path)?;
        assert_eq!(fs::read(path.join(BINARY))?, b"next");
        rollback(path)?;
        assert_eq!(fs::read(path.join(BINARY))?, b"previous");
        assert!(!pending(path));
        fs::hard_link(path.join(BINARY), path.join(PREVIOUS))?;
        rollback(path)?;
        assert_eq!(fs::read(path.join(BINARY))?, b"previous");
        assert!(!pending(path));
        Ok(())
    }
}
