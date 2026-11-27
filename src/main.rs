mod actions;
mod advertising;
mod control;
mod frontlight;
mod launcher;
mod settings;
mod setup;
mod sleep;
mod touch;
mod update;

use actions::Actions;
use anyhow::{Context, Result, bail, ensure};
use bt_hci_serial::SerialTransport;
use control::Session;
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embedded_io_adapters::tokio_1::FromTokio;
use kindle_opendisplay::{Connection as Display, Event, paperwhite, render_status};
use serde::Deserialize;
use settings::Settings;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};
use tokio::io::{AsyncRead, AsyncWrite};
use tokio::signal::unix::{SignalKind, signal};
use tokio_serial::{FlowControl, SerialStream};
use trouble_host::att::{AttClient, AttErrorCode, AttReq};
use trouble_host::prelude::*;

type Response = heapless::Vec<u8, 512>;

struct Controls {
    challenge: Characteristic<[u8; 16]>,
    request: Characteristic<()>,
    response: Characteristic<Response>,
}

fn control_uuid(index: u8) -> u128 {
    0x884cc760_ea3a_4b7b_a8bd_114c4e5342ae | (u128::from(index) << 96)
}

struct Gatt<'a> {
    server: AttributeServer<'a, NoopRawMutex, DefaultPacketPool, 32, 1>,
    display: Option<Characteristic<()>>,
    controls: Option<Controls>,
}

impl<'a> Gatt<'a> {
    fn new(
        name: &'a str,
        show_display: bool,
        response_store: &'a mut [u8; 512],
        controls: bool,
    ) -> Self {
        use CharacteristicProp::{Notify, Read, Write, WriteWithoutResponse};

        let mut table = AttributeTable::new();
        let mut gap = table.add_service(Service::new(service::GAP));
        gap.add_characteristic_ro(characteristic::DEVICE_NAME, name)
            .build();
        gap.add_characteristic_ro(characteristic::APPEARANCE, &0u16)
            .build();
        gap.build();
        let display = show_display.then(|| {
            let mut service = table.add_service(Service::new(0x2446u16));
            let display = service
                .add_characteristic_small(
                    0x2446u16,
                    [Read, Write, WriteWithoutResponse, Notify],
                    (),
                )
                .build();
            service.build();
            display
        });
        let controls = controls.then(|| {
            let mut service = table.add_service(Service::new(control_uuid(0)));
            let challenge = service
                .add_characteristic_small(control_uuid(1), [Read], [0u8; 16])
                .build();
            let request = service
                .add_characteristic_small(control_uuid(2), [Write], ())
                .build();
            let response = service
                .add_characteristic(control_uuid(3), [Read], Response::new(), response_store)
                .build();
            service.build();
            Controls {
                challenge,
                request,
                response,
            }
        });
        Self {
            server: AttributeServer::new(table),
            display,
            controls,
        }
    }
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

// Keep the HCI and GATT futures on the main thread. A separate I/O worker
// avoids the current-thread scheduler's idle polling observed on Lab126 4.1.15.
#[tokio::main(flavor = "multi_thread", worker_threads = 1)]
async fn main() -> Result<()> {
    let mut args = std::env::args_os();
    let invocation = args.next();
    match invocation
        .as_deref()
        .and_then(|path| Path::new(path).file_name())
        .and_then(|name| name.to_str())
    {
        Some("start") => {
            let code = launcher::launch(args).await?;
            std::process::exit(code);
        }
        Some("frontlight") => {
            let code = frontlight::forced_command().await?;
            std::process::exit(code);
        }
        _ => {}
    }
    let mut args = args.peekable();
    match args.peek().and_then(|arg| arg.to_str()) {
        Some("--install") => return setup::install(args.skip(1)),
        Some("--provision") => {
            ensure!(args.count() == 1, "--provision takes no arguments");
            return setup::provision(Path::new(setup::DIRECTORY));
        }
        Some("--setting") => {
            args.next();
            let feature = args.next();
            let result = match (feature.as_deref().and_then(|arg| arg.to_str()), args.next()) {
                (Some(feature), None) => setup::setting(feature),
                _ => Err(anyhow::anyhow!("--setting requires one feature")),
            };
            match result {
                Ok(enabled) => std::process::exit(i32::from(!enabled)),
                Err(error) => {
                    eprintln!("Invalid OpenDisplay configuration: {error:#}");
                    std::process::exit(2);
                }
            }
        }
        Some("--launch") => {
            let code = launcher::launch(args.skip(1)).await?;
            std::process::exit(code);
        }
        _ => {}
    }
    if args.peek().is_some_and(|arg| arg == "--version") {
        println!("kindle-opendisplay {}", update::VERSION);
        return Ok(());
    }
    if args.peek().is_some_and(|arg| arg == "--supervisor-version") {
        println!("1");
        return Ok(());
    }
    if args.peek().is_some_and(|arg| arg == "--supervise") {
        ensure!(args.count() == 1, "--supervise takes no arguments");
        return sleep::supervise().await;
    }
    if args.peek().is_some_and(|arg| arg == "--idle-inhibited") {
        let directory = Path::new(setup::DIRECTORY);
        let settings = Settings::load(directory)?;
        let opendisplay_at_boot =
            settings.autostart && settings.opendisplay && directory.join("autostart").is_file();
        let inhibited = Path::new(settings::PREVENT_SLEEP).is_file()
            || opendisplay_at_boot
            || (settings.stay_awake_on_external_power
                && advertising::external_power() == Some(true));
        std::process::exit(if inhibited { 0 } else { 1 });
    }
    let (Some(transport), Some(identity), Some(output)) = (args.next(), args.next(), args.next())
    else {
        bail!(
            "usage: kindle-opendisplay <kindle-pw4|tcp:HOST:PORT> <device.json> <frame.raw> [--render] [--autostart] [--control-key-file PATH]"
        );
    };
    let mut render = false;
    let mut autostart = false;
    let mut key_path = None;
    while let Some(flag) = args.next() {
        match flag.to_str() {
            Some("--render") => render = true,
            Some("--autostart") => autostart = true,
            Some("--control-key-file") => {
                key_path = Some(PathBuf::from(
                    args.next().context("missing control key path")?,
                ))
            }
            _ => bail!("unknown option"),
        }
    }
    let identity = PathBuf::from(identity);
    let directory = identity.parent().context("invalid identity path")?;
    let settings = Settings::load(directory)?;
    if autostart && !settings.autostart {
        return Ok(());
    }
    paperwhite::set_full_refresh_every(settings.full_refresh_every);
    let key = if settings.controls {
        let explicit = key_path.is_some();
        match fs::read_to_string(key_path.unwrap_or_else(|| directory.join("control.key"))) {
            Ok(data) => {
                let mut key = [0; 32];
                hex::decode_to_slice(data.trim(), &mut key).context("invalid control key")?;
                Some(key)
            }
            Err(error) if !explicit && error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(error).context("read control key"),
        }
    } else {
        None
    };
    let identity: Identity =
        serde_json::from_slice(&fs::read(identity)?).context("invalid BLE identity")?;
    ensure!(
        identity.name.starts_with("OD") && identity.name.len() <= 29,
        "BLE name must start with OD and fit the scan response"
    );
    let address = identity.address()?;
    let output = PathBuf::from(output);
    let transport = transport.to_str().context("invalid transport")?;
    let on_device = transport == "kindle-pw4";
    let config = ReceiverConfig {
        name: &identity.name,
        address,
        output: &output,
        settings: &settings,
        key: key.as_ref(),
        on_device,
        render,
    };
    if let Some(address) = transport.strip_prefix("tcp:") {
        ensure!(!render, "render requires the Paperwhite transport");
        let stream = tokio::net::TcpStream::connect(address).await?;
        return serve(stream, config).await;
    }
    ensure!(on_device, "invalid transport");
    let _radio = paperwhite::Radio::acquire(settings.cpu_latency_us)
        .context("prepare Paperwhite Bluetooth controller")?;
    let serial = SerialStream::open(
        &tokio_serial::new(paperwhite::UART, paperwhite::BAUD_RATE)
            .flow_control(FlowControl::Hardware),
    )
    .context("open Paperwhite Bluetooth UART")?;
    serve(serial, config).await
}

struct ReceiverConfig<'a> {
    name: &'a str,
    address: Address,
    output: &'a Path,
    settings: &'a Settings,
    key: Option<&'a [u8; 32]>,
    on_device: bool,
    render: bool,
}

async fn serve(
    stream: impl AsyncRead + AsyncWrite + Unpin,
    config: ReceiverConfig<'_>,
) -> Result<()> {
    let (reader, writer) = tokio::io::split(stream);
    let transport =
        SerialTransport::<NoopRawMutex, _, _>::new(FromTokio::new(reader), FromTokio::new(writer));
    let controller: ExternalController<_, 10> = ExternalController::new(transport);
    let mut resources: HostResources<DefaultPacketPool, 1, 2> = HostResources::new();
    let stack = trouble_host::new(controller, &mut resources)
        .set_random_address(config.address)
        .build();
    let mut runner = stack.runner();
    let mut peripheral = stack.peripheral();
    let mut response_store = [0u8; 512];
    let gatt_server = Gatt::new(
        config.name,
        config.settings.opendisplay,
        &mut response_store,
        config.key.is_some(),
    );
    let mut actions = Actions::new(&config.settings.commands, config.on_device);
    let mut term = signal(SignalKind::terminate())?;
    let gatt = async {
        let mut announced = false;
        loop {
            let (data, scan) = advertising::packets(
                config.name,
                config.on_device && config.settings.battery_advertising,
                config.settings.opendisplay,
            );
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
                    .with_attribute_server(&gatt_server.server)
                    .map_err(|e| anyhow::anyhow!("attach GATT server: {e:?}"))?;
                let session_lock = if config.on_device && config.settings.sleep_after_seconds != 0 {
                    let file = fs::OpenOptions::new()
                        .create(true)
                        .append(true)
                        .open(sleep::SESSION_LOCK)?;
                    match file.try_lock_shared() {
                        Ok(()) => Some(file),
                        Err(std::fs::TryLockError::WouldBlock) => continue,
                        Err(error) => return Err(error).context("lock OpenDisplay session"),
                    }
                } else {
                    None
                };
                if let Err(error) = receive(&gatt_server, &connection, &config, &mut actions).await
                {
                    eprintln!("OpenDisplay connection ended: {error:#}");
                }
                if let Some(lock) = session_lock {
                    lock.set_modified(SystemTime::now())?;
                }
            }
        }
        #[allow(unreachable_code)]
        Ok(())
    };
    tokio::select! {
        result = runner.run() => result.map_err(|e| anyhow::anyhow!("Bluetooth HCI: {e:?}")),
        result = gatt => result,
        _ = touch::listen(config.on_device && config.render && config.settings.opendisplay && config.settings.frontlight_double_tap) => Ok(()),
        _ = term.recv() => Ok(()),
        result = tokio::signal::ctrl_c() => result.context("wait for interrupt"),
    }
}

async fn receive(
    gatt: &Gatt<'_>,
    connection: &GattConnection<'_, '_, DefaultPacketPool>,
    config: &ReceiverConfig<'_>,
    actions: &mut Actions<'_>,
) -> Result<()> {
    let mut display = Display::default();
    let mut session = config.key.map(Session::new);
    if let Some(handles) = &gatt.controls {
        connection
            .set(&handles.challenge, &[0; 16])
            .map_err(|error| anyhow::anyhow!("clear prior nonce: {error:?}"))?;
        clear_response(connection, handles)?;
    }
    loop {
        let GattConnectionEvent::Gatt { event } = (match connection.next().await {
            GattConnectionEvent::Disconnected { .. } => return Ok(()),
            event => event,
        }) else {
            continue;
        };
        let events = match event {
            GattEvent::Write(write)
                if gatt
                    .display
                    .is_some_and(|command| command.handle == write.handle()) =>
            {
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
            other => {
                if let (Some(handles), Some(session)) = (&gatt.controls, &mut session) {
                    control_event(other, handles, session, actions, connection).await?;
                } else if let Ok(reply) = other.accept() {
                    reply.send().await;
                }
                continue;
            }
        };
        let command = gatt.display.context("missing display characteristic")?;
        for event in events {
            let data = match event {
                Event::Notify(data) => data,
                Event::Render(frame) => {
                    let output = config.output.to_path_buf();
                    let render = config.render;
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

async fn control_event(
    event: GattEvent<'_, '_, DefaultPacketPool>,
    handles: &Controls,
    session: &mut Session<'_>,
    actions: &mut Actions<'_>,
    connection: &GattConnection<'_, '_, DefaultPacketPool>,
) -> Result<()> {
    let reply = match event {
        GattEvent::Read(read) if read.handle() == handles.challenge.handle => {
            if matches!(
                read.payload().incoming(),
                AttClient::Request(AttReq::Read { .. })
            ) {
                clear_response(connection, handles)?;
                let nonce = session.challenge()?;
                connection
                    .set(&handles.challenge, &nonce)
                    .map_err(|error| anyhow::anyhow!("set control nonce: {error:?}"))?;
                read.accept()
            } else {
                read.reject(AttErrorCode::INVALID_OFFSET)
            }
        }
        GattEvent::Read(read) if read.handle() == handles.response.handle => {
            if session.response().is_some() {
                read.accept()
            } else {
                read.reject(AttErrorCode::INSUFFICIENT_AUTHORISATION)
            }
        }
        GattEvent::Write(write) if write.handle() == handles.request.handle => {
            let authenticated = write.with_data(|offset, data| {
                ensure!(offset == 0, "unexpected control write offset");
                session.authenticate(data)
            });
            if let Ok(request) = authenticated {
                let data = serde_json::to_vec(&actions.perform(&request).await)?;
                session.respond(&request, &data)?;
                let response =
                    Response::from_slice(session.response().context("missing control response")?)
                        .map_err(|_| anyhow::anyhow!("control response too long"))?;
                connection
                    .set(&handles.response, &response)
                    .map_err(|error| anyhow::anyhow!("set control response: {error:?}"))?;
                write.accept_unprocessed()
            } else {
                write.reject(AttErrorCode::INSUFFICIENT_AUTHORISATION)
            }
        }
        event => event.accept(),
    };
    reply
        .map_err(|error| anyhow::anyhow!("GATT control reply: {error:?}"))?
        .send()
        .await;
    Ok(())
}

fn clear_response(
    connection: &GattConnection<'_, '_, DefaultPacketPool>,
    handles: &Controls,
) -> Result<()> {
    connection
        .set(&handles.response, &Response::new())
        .map_err(|error| anyhow::anyhow!("clear prior control response: {error:?}"))
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
