mod advertising;

use anyhow::{Context, Result, bail, ensure};
use bt_hci_serial::SerialTransport;
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embedded_io_adapters::tokio_1::FromTokio;
use kindle_opendisplay::{Connection as Display, Event, paperwhite, render_status};
use serde::Deserialize;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::io::{AsyncRead, AsyncWrite};
use tokio::signal::unix::{SignalKind, signal};
use tokio_serial::{FlowControl, SerialStream};
use trouble_host::prelude::*;

#[gatt_server]
struct Server {
    display: DisplayService,
}

#[gatt_service(uuid = "2446")]
struct DisplayService {
    #[characteristic(uuid = "2446", read, write, write_without_response, notify)]
    command: (),
}

#[derive(Deserialize)]
struct Identity {
    name: String,
    address: String,
}

impl Identity {
    fn address(&self) -> Result<Address> {
        let bytes: Vec<_> = self
            .address
            .split(':')
            .map(|octet| {
                ensure!(octet.len() == 2, "invalid BLE address");
                Ok(u8::from_str_radix(octet, 16)?)
            })
            .collect::<Result<_>>()?;
        let mut bytes: [u8; 6] = bytes
            .try_into()
            .map_err(|_| anyhow::anyhow!("invalid BLE address"))?;
        ensure!(
            bytes[0] & 0xc0 == 0xc0,
            "expected a static random BLE address"
        );
        bytes.reverse();
        Ok(Address::random(bytes))
    }
}

#[derive(Deserialize)]
#[serde(default)]
struct Settings {
    opendisplay: bool,
    battery_advertising: bool,
    cpu_latency_us: i32,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            opendisplay: true,
            battery_advertising: true,
            cpu_latency_us: 0,
        }
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let (Some(transport), Some(identity), Some(output)) = (args.next(), args.next(), args.next())
    else {
        bail!(
            "usage: kindle-opendisplay <kindle-pw4|tcp:HOST:PORT> <device.json> <frame.raw> --experimental-display-only [--render]"
        );
    };
    ensure!(
        args.next()
            .is_some_and(|arg| arg == "--experimental-display-only"),
        "Rust control parity is pending; pass --experimental-display-only for isolated display testing"
    );
    let render = match args.next() {
        None => false,
        Some(arg) if arg == "--render" => true,
        Some(_) => bail!("unknown option"),
    };
    ensure!(args.next().is_none(), "unexpected argument");
    let identity = PathBuf::from(identity);
    let settings_path = identity.with_file_name("config.toml");
    let settings: Settings = match fs::read_to_string(&settings_path) {
        Ok(data) => toml::from_str(&data).context("invalid config.toml")?,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Settings::default(),
        Err(err) => return Err(err).context("read config.toml"),
    };
    ensure!(
        settings.opendisplay,
        "OpenDisplay is disabled in config.toml"
    );
    ensure!(
        matches!(settings.cpu_latency_us, 0 | 50),
        "cpu_latency_us must be 0 or 50"
    );
    let identity: Identity =
        serde_json::from_slice(&fs::read(identity)?).context("invalid BLE identity")?;
    ensure!(
        identity.name.starts_with("OD") && identity.name.len() <= 29,
        "BLE name must start with OD and fit the scan response"
    );
    let output = PathBuf::from(output);
    let transport = transport.to_str().context("invalid transport")?;
    if let Some(address) = transport.strip_prefix("tcp:") {
        ensure!(!render, "render requires the Paperwhite transport");
        let stream = tokio::net::TcpStream::connect(address).await?;
        return serve(stream, &identity, &output, false, false).await;
    }
    ensure!(transport == "kindle-pw4", "invalid transport");
    let _radio = paperwhite::Radio::acquire(settings.cpu_latency_us)
        .context("prepare Paperwhite Bluetooth controller")?;
    let serial = SerialStream::open(
        &tokio_serial::new(paperwhite::UART, paperwhite::BAUD_RATE)
            .flow_control(FlowControl::Hardware),
    )
    .context("open Paperwhite Bluetooth UART")?;
    serve(
        serial,
        &identity,
        &output,
        settings.battery_advertising,
        render,
    )
    .await
}

async fn serve(
    stream: impl AsyncRead + AsyncWrite + Unpin,
    identity: &Identity,
    output: &Path,
    battery: bool,
    render: bool,
) -> Result<()> {
    let (reader, writer) = tokio::io::split(stream);
    let transport =
        SerialTransport::<NoopRawMutex, _, _>::new(FromTokio::new(reader), FromTokio::new(writer));
    let controller: ExternalController<_, 10> = ExternalController::new(transport);
    let mut resources: HostResources<DefaultPacketPool, 1, 2> = HostResources::new();
    let stack = trouble_host::new(controller, &mut resources)
        .set_random_address(identity.address()?)
        .build();
    let mut runner = stack.runner();
    let mut peripheral = stack.peripheral();
    let server = Server::new_with_config(GapConfig::Peripheral(PeripheralConfig {
        name: &identity.name,
        appearance: &appearance::power_device::GENERIC_POWER_DEVICE,
    }))
    .map_err(|e| anyhow::anyhow!("configure GATT: {e:?}"))?;
    let mut term = signal(SignalKind::terminate())?;
    let gatt = async {
        let mut announced = false;
        loop {
            let (data, scan) = advertising::packets(&identity.name, battery);
            let advertisement = peripheral
                .advertise(
                    &Default::default(),
                    Advertisement::ConnectableScannableUndirected {
                        adv_data: &data,
                        scan_data: &scan,
                    },
                )
                .await
                .map_err(|e| anyhow::anyhow!("start BLE advertising: {e:?}"))?;
            if !announced {
                eprintln!("Kindle BLE advertising started");
                announced = true;
            }
            if let Ok(connection) =
                tokio::time::timeout(Duration::from_secs(30), advertisement.accept()).await
            {
                let connection = connection
                    .map_err(|e| anyhow::anyhow!("accept BLE connection: {e:?}"))?
                    .with_attribute_server(&server)
                    .map_err(|e| anyhow::anyhow!("attach GATT server: {e:?}"))?;
                if let Err(error) = receive(&server, &connection, output, render).await {
                    eprintln!("OpenDisplay connection ended: {error:#}");
                }
            }
        }
        #[allow(unreachable_code)]
        Ok(())
    };
    tokio::select! {
        result = runner.run() => result.map_err(|e| anyhow::anyhow!("Bluetooth HCI: {e:?}")),
        result = gatt => result,
        _ = term.recv() => Ok(()),
        result = tokio::signal::ctrl_c() => result.context("wait for interrupt"),
    }
}

async fn receive(
    server: &Server<'_>,
    connection: &GattConnection<'_, '_, DefaultPacketPool>,
    output: &Path,
    render: bool,
) -> Result<()> {
    let command = server.display.command;
    let mut display = Display::default();
    loop {
        let GattConnectionEvent::Gatt { event } = (match connection.next().await {
            GattConnectionEvent::Disconnected { .. } => return Ok(()),
            event => event,
        }) else {
            continue;
        };
        let events = match event {
            GattEvent::Write(write) if write.handle() == command.handle => {
                let events = write.with_data(|offset, data| {
                    if offset == 0 {
                        let limit = usize::from(connection.raw().att_mtu()).saturating_sub(3);
                        display.receive(data, limit, advertising::temperature())
                    } else {
                        Vec::new()
                    }
                });
                if let Ok(reply) = write.accept_unprocessed() {
                    reply.send().await;
                }
                events
            }
            event => {
                if let Ok(reply) = event.accept() {
                    reply.send().await;
                }
                continue;
            }
        };
        for event in events {
            let data = match event {
                Event::Notify(data) => data,
                Event::Render(frame) => {
                    let output = output.to_path_buf();
                    let result =
                        tokio::task::spawn_blocking(move || finish_frame(&output, &frame, render))
                            .await
                            .context("join frame update")?;
                    if let Err(error) = &result {
                        eprintln!("Could not finish OpenDisplay image update: {error:#}");
                    }
                    render_status(result.is_ok()).to_vec()
                }
            };
            command
                .notify_raw(connection, &data, false)
                .await
                .map_err(|e| anyhow::anyhow!("send OpenDisplay notification: {e:?}"))?;
        }
    }
}

fn finish_frame(output: &Path, frame: &[u8], render: bool) -> Result<()> {
    let parent = output
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let mut staged = tempfile::NamedTempFile::new_in(parent)?;
    staged.write_all(frame)?;
    staged.persist(output)?;
    if render {
        paperwhite::render(frame)?;
    }
    Ok(())
}
