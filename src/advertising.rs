use std::fs;
use std::path::Path;

const BATTERY: &str = "/sys/class/power_supply/bd71827_bat";
const DISPLAY_UUID: [u8; 4] = [3, 3, 0x46, 0x24];
/// Index of the external-power flags within the OpenDisplay manufacturer
/// record: the last byte of its 11-byte dynamic block, which this receiver
/// leaves otherwise unused. The BTHome record has no room left in the
/// 31-byte advertisement.
const POWER_FLAGS: usize = 4 + 10;
/// Set when the flags byte carries a reading; bit 0 is then AC online.
const POWER_REPORTED: u8 = 0x80;

/// Encode the external power state for the passive advertisement.
pub fn power_flags(online: Option<bool>) -> u8 {
    online.map_or(0, |online| POWER_REPORTED | u8::from(online))
}

pub fn cpu_temperature() -> Option<i32> {
    let zone = fs::read_dir("/sys/class/thermal")
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| {
            fs::read_to_string(path.join("type"))
                .is_ok_and(|kind| kind.trim() == "imx_thermal_zone")
        });
    zone.and_then(|path| fs::read_to_string(path.join("temp")).ok())
        .and_then(|value| value.trim().parse::<i32>().ok())
}

pub fn temperature() -> u8 {
    cpu_temperature().map_or(130, |value| {
        (f64::from(value) / 500.0 + 80.0)
            .round_ties_even()
            .clamp(0.0, 255.0) as u8
    })
}

pub fn external_power() -> Option<bool> {
    match fs::read_to_string("/sys/class/power_supply/bd71827_ac/online")
        .ok()?
        .trim()
    {
        "0" => Some(false),
        "1" => Some(true),
        _ => None,
    }
}

pub struct Battery {
    pub capacity: u8,
    pub status: String,
}

pub fn battery() -> Option<Battery> {
    let path = Path::new(BATTERY);
    let capacity = fs::read_to_string(path.join("capacity"))
        .ok()
        .and_then(|value| value.trim().parse::<u8>().ok())
        .filter(|&value| value <= 100)?;
    let status = match fs::read_to_string(path.join("status")) {
        Ok(status) => status.trim().to_owned(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let charging = fs::read_to_string(path.join("charging")).ok()?;
            let online = external_power() == Some(true);
            if charging.trim() == "1" {
                "Charging"
            } else if online && capacity == 100 {
                "Full"
            } else {
                "Discharging"
            }
            .to_owned()
        }
        Err(_) => return None,
    };
    Some(Battery { capacity, status })
}

fn battery_data() -> Vec<u8> {
    let Some(Battery { capacity, status }) = battery() else {
        return Vec::new();
    };
    let mut data = vec![6, 0x16, 0xd2, 0xfc, 0x40, 1, capacity];
    match status.as_str() {
        "Charging" => data.extend([0x16, 1]),
        "Discharging" | "Full" | "Not charging" => data.extend([0x16, 0]),
        _ => {}
    }
    data[0] = (data.len() - 1) as u8;
    data
}

pub fn packets(name: &str, battery: bool, display: bool) -> (Vec<u8>, Vec<u8>) {
    let mut data = vec![2, 1, 6];
    let mut scan = vec![(name.len() + 1) as u8, 9];
    scan.extend(name.bytes());
    if display {
        if battery {
            if scan.len() + DISPLAY_UUID.len() <= 31 {
                scan.extend(DISPLAY_UUID);
            }
        } else {
            data.extend(DISPLAY_UUID);
        }
        let mut manufacturer = [0; 18];
        manufacturer[..4].copy_from_slice(&[0x11, 0xff, 0x46, 0x24]);
        manufacturer[POWER_FLAGS] = power_flags(external_power());
        manufacturer[15] = temperature();
        data.extend(manufacturer);
    }
    if battery {
        data.extend(battery_data());
    }
    (data, scan)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn power_flags_mark_reported_state() {
        assert_eq!(power_flags(None), 0);
        assert_eq!(power_flags(Some(false)), 0x80);
        assert_eq!(power_flags(Some(true)), 0x81);
    }

    #[test]
    fn advertisement_fits_with_power_flags() {
        let (data, scan) = packets("ODKindlePaperwhite4", true, true);
        assert!(data.len() <= 31, "advertisement is {} bytes", data.len());
        assert!(scan.len() <= 31, "scan response is {} bytes", scan.len());
    }
}
