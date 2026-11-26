//! Paperwhite 4 UART power sequencing and portrait EPDC framebuffer updates.

use crate::{FRAME_BYTES, HEIGHT, WIDTH};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::path::Path;
use std::ptr;
use std::thread;
use std::time::Duration;

pub const UART: &str = "/dev/ttymxc2";
pub const BAUD_RATE: u32 = 115_200;
const DRIVER: &str = "/sys/bus/platform/drivers/imx-uart";
const UART_DEVICE: &str = "2034000.serial";
const POWER: &str = "/sys/bus/platform/devices/bt_pwr_ctrl/btenable";
const CLOCK: &str = "/proc/bluetooth/sleep/uart_clk";
const WAKE: &str = "/proc/bluetooth/sleep/btwake";
const LOCK: &str = "/run/opendisplay-ble.lock";

pub struct Radio {
    _lock: File,
    _latency: File,
}

impl Radio {
    /// Hold the same controller lock as the Python receiver and power up its UART.
    ///
    /// # Errors
    ///
    /// Returns an error when the radio is busy or the required PW4 interfaces are unavailable.
    pub fn acquire(cpu_latency_us: i32) -> io::Result<Self> {
        if cpu_latency_us < 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "negative CPU latency",
            ));
        }
        let lock = OpenOptions::new().create(true).append(true).open(LOCK)?;
        lock.try_lock().map_err(io::Error::from)?;
        let driver = Path::new(DRIVER);
        if fs::read_to_string(POWER)?.trim() != "disabled" || !driver.join(UART_DEVICE).exists() {
            return Err(io::Error::other(
                "expected an idle Bluetooth controller and bound UART",
            ));
        }
        let mut latency = File::options().write(true).open("/dev/cpu_dma_latency")?;
        latency.write_all(&cpu_latency_us.to_ne_bytes())?;

        // Construct the cleanup guard before changing any driver state.
        let radio = Self {
            _lock: lock,
            _latency: latency,
        };
        fs::write(CLOCK, b"1\n")?;
        fs::write(driver.join("unbind"), UART_DEVICE)?;
        fs::write(driver.join("bind"), UART_DEVICE)?;
        fs::write(POWER, b"1\n")?;
        thread::sleep(Duration::from_millis(500));
        fs::write(WAKE, b"0\n")?;
        thread::sleep(Duration::from_millis(500));
        Ok(radio)
    }
}

impl Drop for Radio {
    fn drop(&mut self) {
        let driver = Path::new(DRIVER);
        if !driver.join(UART_DEVICE).exists()
            && let Err(error) = fs::write(driver.join("bind"), UART_DEVICE)
        {
            eprintln!("Could not restore the Bluetooth UART binding: {error}");
        }
        for (path, value) in [(WAKE, b"1\n"), (POWER, b"0\n"), (CLOCK, b"0\n")] {
            if let Err(error) = fs::write(path, value) {
                eprintln!("Could not restore {path}: {error}");
            }
        }
    }
}

/// Draw a packed monochrome image and wait for a full refresh.
///
/// # Errors
///
/// Returns an error when the frame or framebuffer mode is incompatible or a device operation fails.
pub fn render(frame: &[u8]) -> io::Result<()> {
    const GET_MODE: libc::c_ulong = 0x4600;
    const SEND_UPDATE: libc::c_ulong = 0x4050462e;
    const WAIT_UPDATE: libc::c_ulong = 0xc008462f;
    const ROW_BYTES: usize = WIDTH as usize / 8;

    if frame.len() != FRAME_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "incorrect frame length",
        ));
    }
    let stride: u64 = fs::read_to_string("/sys/class/graphics/fb0/stride")?
        .trim()
        .parse()
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    let fb = File::options().read(true).write(true).open("/dev/fb0")?;
    let mut mode = [0u32; 40];
    // SAFETY: GET_MODE copies the 160-byte Linux fb_var_screeninfo into this
    // aligned writable buffer. The file remains open until the call returns.
    ioctl_result(unsafe { libc::ioctl(fb.as_raw_fd(), GET_MODE as _, mode.as_mut_ptr()) })?;
    let (width, height, y) = (u32::from(WIDTH), u32::from(HEIGHT), mode[5]);
    if (mode[0], mode[1], mode[4], mode[6], mode[7], mode[34]) != (width, height, 0, 8, 1, 3)
        || y.checked_add(height).is_none_or(|end| end > mode[3])
        || stride < u64::from(width)
        || stride
            .checked_mul(u64::from(mode[3]))
            .is_none_or(|len| len > isize::MAX as u64)
    {
        return Err(io::Error::other(
            "unexpected PW4 framebuffer geometry or pixel format",
        ));
    }
    let length = usize::try_from((u64::from(y) + u64::from(height)) * stride)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    let stride = usize::try_from(stride)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    // SAFETY: This is a shared, writable kernel mapping of the open framebuffer.
    // The checked length covers each row and no Rust references alias the mapping.
    let mapping = unsafe {
        libc::mmap(
            ptr::null_mut(),
            length,
            libc::PROT_READ | libc::PROT_WRITE,
            libc::MAP_SHARED,
            fb.as_raw_fd(),
            0,
        )
    };
    if mapping == libc::MAP_FAILED {
        return Err(io::Error::last_os_error());
    }
    if mapping.is_null() {
        // SAFETY: This releases a successful mapping at address zero.
        ioctl_result(unsafe { libc::munmap(mapping, length) })?;
        return Err(io::Error::other("framebuffer mapped at a null address"));
    }
    for (row, packed) in frame.as_chunks::<ROW_BYTES>().0.iter().enumerate() {
        let offset = (y as usize + row) * stride;
        for (index, byte) in packed.iter().enumerate() {
            for bit in 0..8 {
                let pixel = if byte & (0x80 >> bit) != 0 { 255 } else { 0 };
                // SAFETY: Each offset is inside a mapped row. Volatile raw
                // writes avoid creating references into device-owned memory.
                unsafe {
                    mapping
                        .cast::<u8>()
                        .add(offset + index * 8 + bit)
                        .write_volatile(pixel)
                };
            }
        }
    }
    // SAFETY: The pointer and length exactly match the successful mapping,
    // and no later operation accesses it.
    ioctl_result(unsafe { libc::munmap(mapping, length) })?;
    let mut marker = [0; 4];
    File::open("/dev/urandom")?.read_exact(&mut marker)?;
    let marker = u32::from_ne_bytes(marker) | 0x8000_0000;
    let mut update = [0u32; 20];
    // Region, GC16 waveform, full update, marker, ambient temperature.
    update[..8].copy_from_slice(&[0, 0, width, height, 2, 1, marker, 0x1000]);
    let mut completed = [marker, 0u32];
    // SAFETY: SEND_UPDATE copies exactly 80 bytes from the aligned update
    // buffer following the PW4 driver ABI. Both the buffer and file remain live.
    ioctl_result(unsafe { libc::ioctl(fb.as_raw_fd(), SEND_UPDATE as _, update.as_ptr()) })?;
    // SAFETY: WAIT_UPDATE reads and writes exactly 8 bytes in the aligned,
    // writable marker buffer. Both the buffer and file remain live.
    ioctl_result(unsafe { libc::ioctl(fb.as_raw_fd(), WAIT_UPDATE as _, completed.as_mut_ptr()) })
}

fn ioctl_result(result: libc::c_int) -> io::Result<()> {
    if result < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}
