//! Detect double taps on the Paperwhite's Goodix touchscreen.

use crate::frontlight::Boost;
use anyhow::{Context, Result, ensure};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, OpenOptions},
    io::Read as _,
    os::unix::fs::OpenOptionsExt as _,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::{
    io::unix::AsyncFd,
    time::{Instant, sleep_until},
};

const EV_SYN: u16 = 0;
const EV_ABS: u16 = 3;
const SYN_DROPPED: u16 = 3;
const SLOT: u16 = 0x2f;
const TRACKING_ID: u16 = 0x39;
const POSITION_X: u16 = 0x35;
const POSITION_Y: u16 = 0x36;
const TAP_MAX: Duration = Duration::from_millis(220);
const DOUBLE_TAP_GAP: Duration = Duration::from_millis(400);
const BOOST_DURATION: Duration = Duration::from_secs(20);

#[derive(Clone, Copy, Default)]
struct Position {
    x: Option<i32>,
    y: Option<i32>,
}

struct Contact {
    start: Duration,
    first: Position,
    last: Position,
    moved: bool,
}

impl Contact {
    fn update(&mut self, axis: u16, value: i32) {
        let (first, last) = if axis == POSITION_X {
            (&mut self.first.x, &mut self.last.x)
        } else {
            (&mut self.first.y, &mut self.last.y)
        };
        self.moved |= first.get_or_insert(value).abs_diff(value) > 65;
        *last = Some(value);
    }
}

#[derive(Default)]
struct DoubleTap {
    slot: i32,
    active: BTreeSet<i32>,
    positions: BTreeMap<i32, Position>,
    contact: Option<Contact>,
    recent: Option<(Duration, i32, i32)>,
}

impl DoubleTap {
    fn event(&mut self, kind: u16, code: u16, value: i32, now: Duration) -> bool {
        match (kind, code) {
            (EV_SYN, SYN_DROPPED) => *self = Self::default(),
            (EV_ABS, SLOT) => self.slot = value,
            (EV_ABS, TRACKING_ID) if value >= 0 => {
                self.active.insert(self.slot);
                if self.active.len() == 1 {
                    self.contact = Some(Contact {
                        start: now,
                        first: Position::default(),
                        last: self.positions.get(&self.slot).copied().unwrap_or_default(),
                        moved: false,
                    });
                } else {
                    self.contact = None;
                    self.recent = None;
                }
            }
            (EV_ABS, TRACKING_ID) if self.active.remove(&self.slot) && self.active.is_empty() => {
                if let Some(tap) = self.contact.take()
                    && !tap.moved
                    && now
                        .checked_sub(tap.start)
                        .is_some_and(|elapsed| elapsed <= TAP_MAX)
                    && let (Some(x), Some(y)) = (tap.last.x, tap.last.y)
                {
                    if self.recent.take().is_some_and(|(end, old_x, old_y)| {
                        tap.start
                            .checked_sub(end)
                            .is_some_and(|elapsed| elapsed <= DOUBLE_TAP_GAP)
                            && old_x.abs_diff(x) <= 125
                            && old_y.abs_diff(y) <= 125
                    }) {
                        return true;
                    }
                    self.recent = Some((now, x, y));
                } else {
                    self.recent = None;
                }
            }
            (EV_ABS, POSITION_X | POSITION_Y) => {
                let position = self.positions.entry(self.slot).or_default();
                if code == POSITION_X {
                    position.x = Some(value);
                } else {
                    position.y = Some(value);
                }
                if let Some(contact) = self.contact.as_mut()
                    && self.active.contains(&self.slot)
                {
                    contact.update(code, value);
                }
            }
            _ => {}
        }
        false
    }
}

fn touchscreen() -> Result<PathBuf> {
    for entry in fs::read_dir("/sys/class/input")? {
        let entry = entry?;
        if entry.file_name().as_encoded_bytes().starts_with(b"event")
            && fs::read_to_string(entry.path().join("device/name"))
                .is_ok_and(|name| name.trim() == "goodix-ts")
        {
            return Ok(Path::new("/dev/input").join(entry.file_name()));
        }
    }
    anyhow::bail!("Goodix touchscreen input device not found")
}

async fn input() -> Result<()> {
    let device = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK)
        .open(touchscreen()?)?;
    let device = AsyncFd::new(device)?;
    // Linux evdev uses the kernel's native long width in the event timestamp.
    const LONG: usize = size_of::<libc::c_long>();
    const HEADER: usize = 2 * LONG;
    const EVENT_SIZE: usize = HEADER + 8;
    let mut buffer = [0; EVENT_SIZE * 16];
    let mut gesture = DoubleTap::default();
    let mut boost: Option<Boost> = None;
    let mut deadline = Instant::now();
    loop {
        tokio::select! {
            _ = sleep_until(deadline), if boost.is_some() => {
                boost = None;
            }
            readiness = device.readable() => {
                let mut ready = readiness?;
                let Ok(result) = ready.try_io(|fd| (&*fd.get_ref()).read(&mut buffer)) else {
                    continue;
                };
                let length = result?;
                ensure!(length != 0 && length % EVENT_SIZE == 0, "incomplete touchscreen input event");
                for bytes in buffer[..length].chunks_exact(EVENT_SIZE) {
                    let kind = u16::from_ne_bytes(bytes[HEADER..HEADER + 2].try_into()?);
                    let code = u16::from_ne_bytes(bytes[HEADER + 2..HEADER + 4].try_into()?);
                    let value = i32::from_ne_bytes(bytes[HEADER + 4..].try_into()?);
                    let seconds = u64::try_from(libc::c_long::from_ne_bytes(bytes[..LONG].try_into()?))?;
                    let micros = u64::try_from(libc::c_long::from_ne_bytes(bytes[LONG..HEADER].try_into()?))?;
                    let time = Duration::from_secs(seconds) + Duration::from_micros(micros);
                    if gesture.event(kind, code, value, time) {
                        let result = if let Some(active) = &boost {
                            active.renew()
                        } else {
                            Boost::begin().map(|active| boost = Some(active))
                        };
                        if let Err(error) = result {
                            eprintln!("Double-tap frontlight: {error:#}");
                        } else {
                            deadline = Instant::now() + BOOST_DURATION;
                        }
                    }
                }
            }
        }
    }
}

pub async fn listen(enabled: bool) {
    if enabled && let Err(error) = input().await.context("listen for touchscreen double taps") {
        eprintln!("{error:#}");
    }
    std::future::pending::<()>().await;
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tap(gesture: &mut DoubleTap, start: Duration, x: i32, length: Duration) -> bool {
        assert!(!gesture.event(EV_ABS, TRACKING_ID, 1, start));
        gesture.event(EV_ABS, POSITION_X, x, start);
        gesture.event(EV_ABS, POSITION_Y, 100, start);
        gesture.event(EV_ABS, TRACKING_ID, -1, start + length)
    }

    #[test]
    fn only_two_nearby_quick_taps_trigger_the_light() {
        let now = Duration::ZERO;
        let short = Duration::from_millis(80);
        let next = now + Duration::from_millis(170);
        let mut gesture = DoubleTap::default();
        assert!(!tap(&mut gesture, now, 200, short));
        assert!(tap(&mut gesture, next, 212, short));
        assert!(!tap(&mut gesture, next + short, 200, short));

        let mut gesture = DoubleTap::default();
        assert!(!tap(&mut gesture, now, 200, short));
        assert!(!tap(&mut gesture, next, 480, short));
        assert!(!tap(&mut gesture, next + short, 480, TAP_MAX + short));
    }

    #[test]
    fn unchanged_coordinates_can_be_omitted_by_evdev() {
        let mut gesture = DoubleTap::default();
        let short = Duration::from_millis(80);
        assert!(!tap(&mut gesture, Duration::ZERO, 200, short));
        let next = Duration::from_millis(170);
        gesture.event(EV_ABS, TRACKING_ID, 2, next);
        assert!(gesture.event(EV_ABS, TRACKING_ID, -1, next + short));
    }

    #[test]
    fn a_drag_or_second_finger_cancels_pairing() {
        let now = Duration::ZERO;
        let short = Duration::from_millis(80);
        for second_finger in [false, true] {
            let mut gesture = DoubleTap::default();
            assert!(!tap(&mut gesture, now, 200, short));
            let next = now + short;
            gesture.event(EV_ABS, TRACKING_ID, 2, next);
            gesture.event(EV_ABS, POSITION_X, 200, next);
            gesture.event(EV_ABS, POSITION_Y, 100, next);
            if second_finger {
                gesture.event(EV_ABS, SLOT, 1, next);
                gesture.event(EV_ABS, TRACKING_ID, 3, next);
                gesture.event(EV_ABS, TRACKING_ID, -1, next);
                gesture.event(EV_ABS, SLOT, 0, next);
            } else {
                gesture.event(EV_ABS, POSITION_X, 300, next);
            }
            assert!(!gesture.event(EV_ABS, TRACKING_ID, -1, next + short));
        }
    }
}
