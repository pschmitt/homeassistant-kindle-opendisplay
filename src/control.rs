//! Kindle control wire authentication. Each connection owns one single-use nonce.

use aes_gcm::{
    Aes256Gcm, KeyInit as _,
    aead::{Aead as _, Nonce, Payload},
};
use anyhow::{Context, Result, ensure};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::{
    fs::File,
    io::Read as _,
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq as _;

const CONTEXT: &[u8] = b"kindle-control-v1\0";
const FRONTLIGHT_LEVEL: u8 = 0xbc;
const COMMAND: u8 = 0x89;
const UPDATE_STATUS: u8 = 0x9c;
const UPDATE_START: u8 = 0x9d;
const UPDATE_CONFIRM: u8 = 0x9e;
const MAX_COMMAND: usize = 160;

pub enum Request {
    Control(u8),
    FrontlightLevel(u16),
    Command(String),
    UpdateStatus,
    StartUpdate(String),
    ConfirmUpdate(String),
}

pub struct Session<'a> {
    key: &'a [u8; 32],
    challenge: Option<([u8; 16], Instant)>,
    response: Option<Vec<u8>>,
}

pub struct Authenticated {
    pub request: Request,
    nonce: [u8; 16],
    opcode: u8,
}

impl Authenticated {
    pub fn encrypted(&self) -> bool {
        self.opcode & 0x80 != 0
    }

    pub fn telemetry_fields(&self) -> usize {
        match self.opcode & 0xf0 {
            0xa0 | 0xb0 => 19,
            0xf0 => 18,
            0xe0 => 17,
            0xc0 | 0xd0 => 16,
            _ if self.encrypted() => 15,
            _ => 13,
        }
    }

    pub fn reports_wifi_mac(&self) -> bool {
        self.opcode & 0xf0 == 0xa0
    }

    fn header(&self) -> Vec<u8> {
        [CONTEXT, &self.nonce, &[self.opcode]].concat()
    }
}

impl<'a> Session<'a> {
    pub fn new(key: &'a [u8; 32]) -> Self {
        Self {
            key,
            challenge: None,
            response: None,
        }
    }

    pub fn challenge(&mut self) -> Result<[u8; 16]> {
        let mut nonce = [0; 16];
        File::open("/dev/urandom")?.read_exact(&mut nonce)?;
        self.challenge = Some((nonce, Instant::now()));
        self.response = None;
        Ok(nonce)
    }

    pub fn authenticate(&mut self, packet: &[u8]) -> Result<Authenticated> {
        let (nonce, issued) = self.challenge.take().context("missing challenge")?;
        ensure!(
            issued.elapsed() <= Duration::from_secs(30),
            "expired challenge"
        );
        let (&opcode, data) = packet.split_first().context("missing opcode")?;
        let header = [CONTEXT, &nonce, &[opcode]].concat();
        let request = if opcode == COMMAND {
            ensure!(
                (17..=MAX_COMMAND + 16).contains(&data.len()),
                "invalid sealed command length"
            );
            let key = mac(self.key, &[b"kindle-control command request encryption"]);
            let cipher = Aes256Gcm::new((&key).into());
            let clear = cipher
                .decrypt(
                    &nonce_of(&nonce),
                    Payload {
                        msg: data,
                        aad: &header,
                    },
                )
                .map_err(|_| anyhow::anyhow!("invalid command authentication"))?;
            Request::Command(String::from_utf8(clear)?)
        } else if matches!(opcode, UPDATE_STATUS | UPDATE_START | UPDATE_CONFIRM) {
            ensure!(data.len() >= 16, "missing update authentication");
            let (payload, tag) = data.split_at(data.len() - 16);
            let expected = mac(self.key, &[b"request\0", &header, payload]);
            ensure!(
                bool::from(tag.ct_eq(&expected[..16])),
                "invalid update authentication"
            );
            match opcode {
                UPDATE_STATUS if payload.is_empty() => Request::UpdateStatus,
                UPDATE_START | UPDATE_CONFIRM if payload.len() == 3 => {
                    let version = format!("{}.{}.{}", payload[0], payload[1], payload[2]);
                    if opcode == UPDATE_START {
                        Request::StartUpdate(version)
                    } else {
                        Request::ConfirmUpdate(version)
                    }
                }
                _ => anyhow::bail!("invalid update payload"),
            }
        } else if opcode == FRONTLIGHT_LEVEL {
            let [high, low, tag @ ..] = data else {
                anyhow::bail!("missing frontlight level");
            };
            let level = [*high, *low];
            let expected = mac(self.key, &[b"request\0", &header, &level]);
            ensure!(
                tag.len() == 16 && bool::from(tag.ct_eq(&expected[..16])),
                "invalid frontlight authentication"
            );
            Request::FrontlightLevel(u16::from_be_bytes(level))
        } else {
            let tag = mac(self.key, &[b"request\0", &header]);
            ensure!(
                data.len() == 16 && bool::from(data.ct_eq(&tag[..16])),
                "invalid request authentication"
            );
            let mask = match opcode & 0xf0 {
                0xa0 | 0xb0 | 0xf0 => 0x0f,
                0xe0 => 0x1f,
                0xc0 | 0xd0 => 0x1f,
                _ => 0x7f,
            };
            Request::Control(opcode & mask)
        };
        Ok(Authenticated {
            request,
            nonce,
            opcode,
        })
    }

    pub fn respond(&mut self, request: &Authenticated, data: &[u8]) -> Result<()> {
        let header = request.header();
        self.response = Some(if request.encrypted() {
            let key = mac(self.key, &[b"kindle-control response encryption"]);
            Aes256Gcm::new((&key).into())
                .encrypt(
                    &nonce_of(&request.nonce),
                    Payload {
                        msg: data,
                        aad: &header,
                    },
                )
                .map_err(|_| anyhow::anyhow!("could not encrypt the control response"))?
        } else {
            let tag = mac(self.key, &[b"response\0", &header, data]);
            [&tag[..16], data].concat()
        });
        Ok(())
    }

    pub fn response(&self) -> Option<&[u8]> {
        self.response.as_deref()
    }
}

fn nonce_of(nonce: &[u8; 16]) -> Nonce<Aes256Gcm> {
    let mut gcm = [0; 12];
    gcm.copy_from_slice(&nonce[..12]);
    gcm.into()
}

fn mac(key: &[u8; 32], parts: &[&[u8]]) -> [u8; 32] {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).expect("HMAC accepts any key length");
    for part in parts {
        mac.update(part);
    }
    mac.finalize().into_bytes().into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frontlight_authentication_covers_the_level_and_challenge() -> Result<()> {
        let key = [0x23; 32];
        let mut session = Session::new(&key);
        for mutate in [false, true] {
            let nonce = session.challenge()?;
            let level = 1024u16.to_be_bytes();
            let tag = mac(
                &key,
                &[b"request\0", CONTEXT, &nonce, &[FRONTLIGHT_LEVEL], &level],
            );
            let mut packet = [&[FRONTLIGHT_LEVEL][..], &level, &tag[..16]].concat();
            if mutate {
                packet[2] ^= 1;
                assert!(session.authenticate(&packet).is_err());
            } else {
                let authenticated = session.authenticate(&packet)?;
                assert!(matches!(
                    authenticated.request,
                    Request::FrontlightLevel(1024)
                ));
                assert!(session.authenticate(&packet).is_err());
            }
        }
        Ok(())
    }
    #[test]
    fn update_authentication_covers_the_compact_version() -> Result<()> {
        let key = [0x23; 32];
        let mut session = Session::new(&key);
        let payload = [0u8, 9, 1];
        for altered in [None, Some(1), Some(3)] {
            let nonce = session.challenge()?;
            let tag = mac(
                &key,
                &[b"request\0", CONTEXT, &nonce, &[UPDATE_START], &payload],
            );
            let mut packet = [&[UPDATE_START][..], &payload, &tag[..16]].concat();
            if let Some(index) = altered {
                packet[index] ^= 1;
                assert!(session.authenticate(&packet).is_err());
            } else {
                let request = session.authenticate(&packet)?;
                assert!(matches!(
                    request.request,
                    Request::StartUpdate(version) if version == "0.9.1"
                ));
                assert!(session.authenticate(&packet).is_err());
            }
        }
        Ok(())
    }
}
