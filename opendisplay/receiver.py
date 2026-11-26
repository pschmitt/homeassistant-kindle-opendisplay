"""Experimental OpenDisplay BLE receiver with a file-backed frame sink."""

import argparse
import asyncio
import binascii
import fcntl
import logging
import mmap
import os
import signal
import struct
import tempfile
import time
import zlib
from contextlib import contextmanager, nullcontext
from pathlib import Path

WIDTH, HEIGHT = 1072, 1448
FRAME_BYTES = (WIDTH // 8) * HEIGHT
KINDLE_TRANSPORT = "serial:/dev/ttymxc2,115200,rtscts"
ADVERTISEMENT_PREFIX = b"\x02\x01\x06\x03\x03\x46\x24\x11\xff"
PIXELS = tuple(
    bytes(255 if value & (128 >> bit) else 0 for bit in range(8))
    for value in range(256)
)
LOG = logging.getLogger(__name__)


def manufacturer_data():
    temperature = 130  # OpenDisplay's 25 °C fallback when no SoC sensor is exposed.
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            if (zone / "type").read_text().strip() == "imx_thermal_zone":
                millicelsius = int((zone / "temp").read_text())
                temperature = max(0, min(255, round(millicelsius / 500 + 80)))
                break
        except (OSError, ValueError):
            continue
    return b"\x46\x24" + bytes(11) + bytes((temperature, 0, 0))


def render_pw4(frame):
    """Draw one portrait frame in the 8-bit mode configured by Inkwell."""
    stride = int(Path("/sys/class/graphics/fb0/stride").read_text())
    with open("/dev/fb0", "r+b", buffering=0) as framebuffer:
        mode = bytearray(160)
        fcntl.ioctl(framebuffer, 0x4600, mode)
        width, height, _, _, x, y, depth, grayscale = struct.unpack_from("=8I", mode)
        (rotation,) = struct.unpack_from("=I", mode, 136)
        if (width, height, x, depth, grayscale, rotation) != (
            WIDTH,
            HEIGHT,
            0,
            8,
            1,
            3,
        ) or stride < width:
            raise OSError("Unexpected PW4 framebuffer geometry or pixel format")
        with mmap.mmap(framebuffer.fileno(), (y + height) * stride) as pixels:
            row_bytes = width // 8
            for row in range(height):
                packed = frame[row * row_bytes : (row + 1) * row_bytes]
                start = (y + row) * stride
                pixels[start : start + width] = b"".join(
                    PIXELS[value] for value in packed
                )

        marker = int.from_bytes(os.urandom(4), "little") | 0x80000000
        # PW4 EPDC update struct: region, GC16 waveform, full update, marker, ambient temperature.
        update = struct.pack("=8I", 0, 0, width, height, 2, 1, marker, 0x1000) + bytes(
            48
        )
        fcntl.ioctl(framebuffer, 0x4050462E, update)
        fcntl.ioctl(framebuffer, 0xC008462F, bytearray(struct.pack("=II", marker, 0)))


@contextmanager
def kindle_radio():
    """Hold the PW4 UART clock and prepare the controller for cold HCI."""
    driver = Path("/sys/bus/platform/drivers/imx-uart")
    uart = "2034000.serial"
    power = Path("/sys/bus/platform/devices/bt_pwr_ctrl/btenable")
    sleep = Path("/proc/bluetooth/sleep")
    clock = sleep / "uart_clk"
    wake = sleep / "btwake"

    with open("/run/opendisplay-ble.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if power.read_text().strip() != "disabled" or not (driver / uart).exists():
            raise RuntimeError(
                "Expected an idle PW4 Bluetooth controller and a bound UART"
            )

        with open("/dev/cpu_dma_latency", "wb", buffering=0) as latency:
            latency.write(struct.pack("=i", 0))
            clock.write_text("1\n")
            try:
                (driver / "unbind").write_text(uart)
                (driver / "bind").write_text(uart)
                power.write_text("1\n")
                time.sleep(0.5)
                wake.write_text("0\n")
                time.sleep(0.5)
                yield
            finally:
                if not (driver / uart).exists():
                    (driver / "bind").write_text(uart)
                wake.write_text("1\n")
                power.write_text("0\n")
                clock.write_text("0\n")


def display_config():
    system = bytes((0, 0, 1, 0, 255)) + bytes(15) + b"\xff\xff"
    manufacturer = bytes(22)
    power = bytes(30)
    display = struct.pack("<BB6H", 0, 0, 0, WIDTH, HEIGHT, 0, 0, 0)
    display += bytes((0, 255, 255, 255, 255, 255, 0, 0, 3, 255))
    display += b"\xff" * 7 + bytes(15)
    body = (
        b"\x00\x00\x01"
        + b"\x00\x01"
        + system
        + b"\x00\x02"
        + manufacturer
        + b"\x00\x04"
        + power
        + b"\x00\x20"
        + display
    )
    crc = binascii.crc_hqx(body, 0xFFFF)
    return body + struct.pack("<H", crc)


class Transfer:
    def __init__(self, compressed):
        self.frame = bytearray()
        self.decoder = zlib.decompressobj() if compressed else None

    def add(self, data):
        available = FRAME_BYTES - len(self.frame)
        if self.decoder is not None:
            data = self.decoder.decompress(data, available + 1)
            if self.decoder.unused_data:
                raise ValueError("Trailing compressed frame data")
        if len(data) > available:
            raise ValueError("Frame exceeds the configured display size")
        self.frame.extend(data)

    def complete(self):
        return len(self.frame) == FRAME_BYTES and (
            self.decoder is None or self.decoder.eof
        )


class Receiver:
    def __init__(self, output, render=None):
        self.output = output
        self.render = render
        self.frames = {}

    def disconnect(self, connection):
        self.frames.pop(connection, None)

    def receive(self, connection, packet, payload_limit):
        if len(packet) < 2:
            return
        command = packet[:2]
        data = packet[2:]
        if command == b"\x00\x40" and not data:
            config = display_config()
            remaining = config
            for index in range(len(config)):
                header = command + struct.pack("<H", index)
                if index == 0:
                    header += struct.pack("<H", len(config))
                size = payload_limit - len(header)
                if size <= 0:
                    raise ValueError("ATT payload too short for configuration")
                yield header + remaining[:size]
                remaining = remaining[size:]
                if not remaining:
                    return
        elif command == b"\x00\x43" and not data:
            yield command + b"\x01\x00\x07" + b"0000000"
        elif command == b"\x00\x44" and not data:
            yield command + manufacturer_data()
        elif command == b"\x00\x70":
            self.disconnect(connection)
            if data and (
                len(data) < 4 or int.from_bytes(data[:4], "little") != FRAME_BYTES
            ):
                yield self.reject(command)
                return
            transfer = Transfer(compressed=bool(data))
            try:
                if data[4:]:
                    transfer.add(data[4:])
            except (ValueError, zlib.error):
                yield self.reject(command)
                return
            self.frames[connection] = transfer
            yield command
        elif command == b"\x00\x71":
            transfer = self.frames.get(connection)
            try:
                if transfer is None or not data:
                    raise ValueError("Missing frame or chunk")
                transfer.add(data)
            except (ValueError, zlib.error):
                self.disconnect(connection)
                yield self.reject(command)
            else:
                yield command
        elif command == b"\x00\x72":
            transfer = self.frames.pop(connection, None)
            if transfer is None or not transfer.complete():
                yield self.reject(command)
                return
            frame = transfer.frame
            yield command
            try:
                self.save_frame(frame)
                if self.render is not None:
                    self.render(frame)
            except OSError:
                LOG.exception("Could not finish OpenDisplay image update")
                yield b"\x00\x74"
            else:
                LOG.info(
                    "Received %d-byte OpenDisplay frame%s",
                    len(frame),
                    " and refreshed the panel" if self.render else "",
                )
                yield b"\x00\x73"
        else:
            yield self.reject(command)

    @staticmethod
    def reject(command):
        return bytes((0xFF, command[1], 0, 0))

    def save_frame(self, frame):
        with tempfile.NamedTemporaryFile(
            dir=self.output.parent, delete=False
        ) as staged:
            path = Path(staged.name)
            try:
                staged.write(frame)
                staged.close()
                os.replace(path, self.output)
            finally:
                path.unlink(missing_ok=True)


async def serve(transport, device_config, output, render=None):
    from bumble.core import UUID
    from bumble.device import Device
    from bumble.gatt import Characteristic, CharacteristicValue, Service
    from bumble.hci import HCI_LE_Set_Advertising_Data_Command
    from bumble.transport import open_transport

    receiver = Receiver(output, render)
    uuid = UUID.from_16_bits(0x2446)
    async with await open_transport(transport) as hci:
        device = Device.from_config_file_with_hci(device_config, hci.source, hci.sink)
        name = device.name.encode()
        if not name.startswith(b"OD") or len(name) > 29:
            raise ValueError("BLE name must start with OD and fit in the scan response")

        async def write(connection, packet):
            for response in receiver.receive(
                connection, packet, connection.att_mtu - 3
            ):
                await device.notify_subscriber(connection, characteristic, response)

        @device.on(Device.EVENT_CONNECTION)
        def connected(connection):
            @connection.on(connection.EVENT_DISCONNECTION)
            def disconnected(_reason):
                receiver.disconnect(connection)

        properties = Characteristic.Properties
        characteristic = Characteristic(
            uuid,
            properties.READ
            | properties.WRITE
            | properties.WRITE_WITHOUT_RESPONSE
            | properties.NOTIFY,
            Characteristic.READABLE | Characteristic.WRITEABLE,
            CharacteristicValue(read=lambda _connection: b"", write=write),
        )
        device.add_services([Service(uuid, [characteristic])])
        device.advertising_data = ADVERTISEMENT_PREFIX + manufacturer_data()
        device.scan_response_data = bytes((len(name) + 1, 0x09)) + name
        await device.power_on()
        await device.start_advertising(auto_restart=True)
        LOG.info("OpenDisplay BLE advertising started")
        while not hci.source.terminated.done():
            done, _ = await asyncio.wait([hci.source.terminated], timeout=30)
            if done:
                break
            data = ADVERTISEMENT_PREFIX + manufacturer_data()
            if data != device.advertising_data:
                device.advertising_data = data
                if device.legacy_advertiser and not device.connections:
                    await device.send_sync_command(
                        HCI_LE_Set_Advertising_Data_Command(advertising_data=data)
                    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "transport", help="Bumble HCI transport, or 'kindle-pw4' for guarded PW4 setup"
    )
    parser.add_argument("device_config", help="Bumble device configuration JSON")
    parser.add_argument(
        "output", type=Path, help="Destination for the raw packed monochrome frame"
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Refresh the PW4 panel after receiving a frame",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    radio = kindle_radio if args.transport == "kindle-pw4" else nullcontext
    transport = KINDLE_TRANSPORT if args.transport == "kindle-pw4" else args.transport
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        with radio():
            asyncio.run(
                serve(
                    transport,
                    args.device_config,
                    args.output,
                    render_pw4 if args.render else None,
                )
            )
    except KeyboardInterrupt:
        pass
