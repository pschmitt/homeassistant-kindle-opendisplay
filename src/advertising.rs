use std::fs;
use std::path::Path;

const BATTERY: &str = "/sys/class/power_supply/bd71827_bat";
const DISPLAY_UUID: [u8; 4] = [3, 3, 0x46, 0x24];

pub fn temperature() -> u8 {
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
        .map_or(130, |value| {
            (f64::from(value) / 500.0 + 80.0)
                .round_ties_even()
                .clamp(0.0, 255.0) as u8
        })
}

fn battery_data(path: &Path) -> Vec<u8> {
    let Some(capacity) = fs::read_to_string(path.join("capacity"))
        .ok()
        .and_then(|value| value.trim().parse::<u8>().ok())
        .filter(|&value| value <= 100)
    else {
        return Vec::new();
    };
    let Ok(status) = fs::read_to_string(path.join("status")) else {
        return Vec::new();
    };
    let mut data = vec![6, 0x16, 0xd2, 0xfc, 0x40, 1, capacity];
    match status.trim() {
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
        manufacturer[15] = temperature();
        data.extend(manufacturer);
    }
    if battery {
        data.extend(battery_data(Path::new(BATTERY)));
    }
    (data, scan)
}
