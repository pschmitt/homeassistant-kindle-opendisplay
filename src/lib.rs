//! OpenDisplay framing for the Kindle Paperwhite 4.

use flate2::{Decompress, FlushDecompress, Status};
#[cfg(target_os = "linux")]
pub mod paperwhite;

pub const WIDTH: u16 = 1072;
pub const HEIGHT: u16 = 1448;
pub const FRAME_BYTES: usize = WIDTH as usize / 8 * HEIGHT as usize;

pub enum Event {
    Notify(Vec<u8>),
    // The transport sends the finish acknowledgment before rendering the frame.
    Render(Vec<u8>),
}

struct Transfer {
    frame: Vec<u8>,
    decoder: Option<Decompress>,
    at_end: bool,
}

impl Transfer {
    fn new(compressed: bool) -> Self {
        Self {
            frame: Vec::with_capacity(FRAME_BYTES + 1),
            decoder: compressed.then(|| Decompress::new(true)),
            at_end: false,
        }
    }

    fn add(&mut self, data: &[u8]) -> Result<(), ()> {
        if let Some(decoder) = &mut self.decoder {
            if self.at_end {
                return Err(());
            }
            let previous_input = decoder.total_in();
            let status = decoder
                .decompress_vec(data, &mut self.frame, FlushDecompress::None)
                .map_err(|_| ())?;
            self.at_end = status == Status::StreamEnd;
            if decoder.total_in() - previous_input != data.len() as u64 {
                return Err(());
            }
        } else if data.len() <= FRAME_BYTES - self.frame.len() {
            self.frame.extend_from_slice(data);
        } else {
            return Err(());
        }
        (self.frame.len() <= FRAME_BYTES).then_some(()).ok_or(())
    }

    fn complete(&self) -> bool {
        self.frame.len() == FRAME_BYTES && (self.decoder.is_none() || self.at_end)
    }
}

#[derive(Default)]
pub struct Connection {
    transfer: Option<Transfer>,
}

impl Connection {
    pub fn receive(&mut self, packet: &[u8], payload_limit: usize, temperature: u8) -> Vec<Event> {
        let [namespace, opcode, data @ ..] = packet else {
            return Vec::new();
        };
        let ack = || vec![Event::Notify(vec![0, *opcode])];
        let reject = || vec![Event::Notify(vec![0xff, *opcode, 0, 0])];
        match (*namespace, *opcode, data) {
            (0, 0x40, []) => configuration_packets(payload_limit),
            (0, 0x43, []) => vec![Event::Notify(b"\x00\x43\x01\x00\x070000000".to_vec())],
            (0, 0x44, []) => {
                let mut response = vec![0; 18];
                response[..4].copy_from_slice(&[0, 0x44, 0x46, 0x24]);
                response[15] = temperature;
                vec![Event::Notify(response)]
            }
            (0, 0x70, _) => {
                self.transfer = None;
                let mut transfer = Transfer::new(!data.is_empty());
                if !data.is_empty()
                    && (!data.starts_with(&(FRAME_BYTES as u32).to_le_bytes())
                        || (data.len() > 4 && transfer.add(&data[4..]).is_err()))
                {
                    return reject();
                }
                self.transfer = Some(transfer);
                ack()
            }
            (0, 0x71, _) => {
                if !data.is_empty()
                    && self
                        .transfer
                        .as_mut()
                        .is_some_and(|transfer| transfer.add(data).is_ok())
                {
                    ack()
                } else {
                    self.transfer = None;
                    reject()
                }
            }
            (0, 0x72, _) => match self.transfer.take() {
                Some(transfer) if transfer.complete() => {
                    vec![Event::Notify(vec![0, 0x72]), Event::Render(transfer.frame)]
                }
                _ => reject(),
            },
            _ => reject(),
        }
    }
}

pub fn render_status(success: bool) -> [u8; 2] {
    [0, if success { 0x73 } else { 0x74 }]
}

fn configuration_packets(payload_limit: usize) -> Vec<Event> {
    if payload_limit <= 6 {
        return vec![Event::Notify(vec![0xff, 0x40, 0, 0])];
    }
    let config = display_configuration();
    let mut remaining = config.as_slice();
    let mut packets = Vec::new();
    while !remaining.is_empty() {
        let index = packets.len() as u16;
        let mut packet = vec![0, 0x40];
        packet.extend(index.to_le_bytes());
        if index == 0 {
            packet.extend((config.len() as u16).to_le_bytes());
        }
        let (chunk, rest) = remaining.split_at(remaining.len().min(payload_limit - packet.len()));
        packet.extend_from_slice(chunk);
        packets.push(Event::Notify(packet));
        remaining = rest;
    }
    packets
}

fn display_configuration() -> Vec<u8> {
    let mut config = vec![0, 0, 1, 0, 1, 0, 0, 1, 0, 255];
    config.extend([0; 15]);
    config.extend([255, 255, 0, 2]);
    config.extend([0; 22]);
    config.extend([0, 4]);
    config.extend([0; 30]);
    config.extend([0, 32, 0, 0, 0, 0]);
    config.extend(WIDTH.to_le_bytes());
    config.extend(HEIGHT.to_le_bytes());
    config.extend([0; 6]);
    config.extend([0, 255, 255, 255, 255, 255, 0, 0, 3, 255]);
    config.extend([255; 7]);
    config.extend([0; 15]);
    let crc = config.iter().fold(0xffffu16, |crc, &byte| {
        (0..8).fold(crc ^ (u16::from(byte) << 8), |crc, _| {
            (crc << 1) ^ if crc & 0x8000 == 0 { 0 } else { 0x1021 }
        })
    });
    config.extend(crc.to_le_bytes());
    config
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::{Compression, write::ZlibEncoder};
    use std::io::Write as _;

    fn notify(events: &[Event], expected: &[u8]) {
        assert!(matches!(events, [Event::Notify(bytes)] if bytes == expected));
    }

    fn start_compressed(connection: &mut Connection) {
        let start = [vec![0, 0x70], (FRAME_BYTES as u32).to_le_bytes().to_vec()].concat();
        notify(&connection.receive(&start, 20, 130), &[0, 0x70]);
    }

    #[test]
    fn configuration_matches_python_at_small_att_mtu() {
        let mut connection = Connection::default();
        let packets = connection.receive(&[0, 0x40], 20, 130);
        let mut config = Vec::new();
        for (index, event) in packets.iter().enumerate() {
            let Event::Notify(packet) = event else {
                panic!("configuration produced a frame");
            };
            assert!(packet.len() <= 20);
            assert_eq!(&packet[..4], &[0, 0x40, index as u8, 0]);
            if index == 0 {
                assert_eq!(&packet[4..6], &[133, 0]);
            }
            config.extend_from_slice(&packet[if index == 0 { 6 } else { 4 }..]);
        }
        assert_eq!(config.len(), 133);
        assert_eq!(&config[89..93], &[0x30, 0x04, 0xa8, 0x05]);
        assert_eq!(&config[131..], &EXPECTED_CRC);
    }

    const EXPECTED_CRC: [u8; 2] = [214, 69];

    #[test]
    fn compressed_frame_round_trips_and_rejects_trailing_bytes() {
        let frame = vec![0x5a; FRAME_BYTES];
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&frame).unwrap();
        let compressed = encoder.finish().unwrap();

        let mut connection = Connection::default();
        start_compressed(&mut connection);
        for chunk in compressed.chunks(18) {
            let packet = [&[0, 0x71], chunk].concat();
            notify(&connection.receive(&packet, 20, 130), &[0, 0x71]);
        }
        assert!(matches!(
            connection.receive(&[0, 0x72], 20, 130).as_slice(),
            [Event::Notify(ack), Event::Render(bytes)] if ack == &[0, 0x72] && bytes == &frame
        ));

        start_compressed(&mut connection);
        let packet = [&[0, 0x71], compressed.as_slice(), &[0]].concat();
        notify(&connection.receive(&packet, 20, 130), &[0xff, 0x71, 0, 0]);
        notify(
            &connection.receive(&[0, 0x72], 20, 130),
            &[0xff, 0x72, 0, 0],
        );
    }

    #[test]
    fn raw_transfer_is_isolated_and_limited() {
        let mut first = Connection::default();
        let mut second = Connection::default();
        notify(&first.receive(&[0, 0x70], 20, 130), &[0, 0x70]);
        notify(&second.receive(&[0, 0x71, 0], 20, 130), &[0xff, 0x71, 0, 0]);
        let packet = [&[0, 0x71], vec![0; FRAME_BYTES + 1].as_slice()].concat();
        notify(&first.receive(&packet, 20, 130), &[0xff, 0x71, 0, 0]);
    }
}
