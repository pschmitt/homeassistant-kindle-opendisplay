//! Kindle control wire authentication. Each connection owns one single-use nonce.

use aes_gcm::{
    Aes256Gcm, KeyInit as _,
    aead::{Aead as _, Payload},
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
const COMMAND: u8 = 0x89;
const MAX_COMMAND: usize = 160;

pub enum Request {
    Control(u8),
    Command(String),
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
            0xf0 => 18,
            0xe0 => 17,
            0xc0 | 0xd0 => 16,
            _ if self.encrypted() => 15,
            _ => 13,
        }
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
                    nonce[..12].into(),
                    Payload {
                        msg: data,
                        aad: &header,
                    },
                )
                .map_err(|_| anyhow::anyhow!("invalid command authentication"))?;
            Request::Command(String::from_utf8(clear)?)
        } else {
            let tag = mac(self.key, &[b"request\0", &header]);
            ensure!(
                data.len() == 16 && bool::from(data.ct_eq(&tag[..16])),
                "invalid request authentication"
            );
            let mask = match opcode & 0xf0 {
                0xf0 => 0x0f,
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
                    request.nonce[..12].into(),
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

fn mac(key: &[u8; 32], parts: &[&[u8]]) -> [u8; 32] {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).expect("HMAC accepts any key length");
    for part in parts {
        mac.update(part);
    }
    mac.finalize().into_bytes().into()
}
