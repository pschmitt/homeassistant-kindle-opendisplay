"""Experimental OpenDisplay BLE receiver with a file-backed frame sink."""

import argparse
import asyncio
import binascii
import fcntl
import os
import signal
import struct
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

WIDTH, HEIGHT = 1072, 1448
FRAME_BYTES = (WIDTH // 8) * HEIGHT
KINDLE_TRANSPORT = "serial:/dev/ttymxc2,115200,rtscts"


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
            raise RuntimeError("Expected an idle PW4 Bluetooth controller and a bound UART")

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
    display = struct.pack("<BB6H", 0, 0, 0, WIDTH, HEIGHT, 0, 0, 0)
    display += bytes((0, 255, 255, 255, 255, 255, 0, 0, 0, 255))
    display += b"\xff" * 7 + bytes(15)
    body = b"\x00\x00\x01\x00\x20" + display
    crc = binascii.crc_hqx(body, 0xFFFF)
    return body + struct.pack("<H", crc)


class Receiver:
    def __init__(self, output):
        self.output = output
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
            yield command + b"\x00\x01\x05local"
        elif command == b"\x00\x70" and not data:
            self.frames[connection] = bytearray()
            yield command
        elif command == b"\x00\x71":
            frame = self.frames.get(connection)
            if frame is not None and data and len(frame) + len(data) <= FRAME_BYTES:
                frame.extend(data)
                yield command
            else:
                self.disconnect(connection)
                yield self.reject(command)
        elif command == b"\x00\x72":
            frame = self.frames.pop(connection, None)
            if frame is None or len(frame) != FRAME_BYTES:
                yield self.reject(command)
                return
            yield command
            try:
                self.save_frame(frame)
            except OSError:
                yield b"\x00\x74"
            else:
                yield b"\x00\x73"
        else:
            yield self.reject(command)

    @staticmethod
    def reject(command):
        return bytes((0xFF, command[1], 0, 0))

    def save_frame(self, frame):
        with tempfile.NamedTemporaryFile(dir=self.output.parent, delete=False) as staged:
            path = Path(staged.name)
            try:
                staged.write(frame)
                staged.close()
                os.replace(path, self.output)
            finally:
                path.unlink(missing_ok=True)


async def serve(transport, device_config, output):
    from bumble.core import UUID
    from bumble.device import Device
    from bumble.gatt import Characteristic, CharacteristicValue, Service
    from bumble.transport import open_transport

    receiver = Receiver(output)
    uuid = UUID.from_16_bits(0x2446)
    async with await open_transport(transport) as hci:
        device = Device.from_config_file_with_hci(device_config, hci.source, hci.sink)

        async def write(connection, packet):
            for response in receiver.receive(connection, packet, connection.att_mtu - 3):
                await device.notify_subscriber(connection, characteristic, response)

        @device.on(Device.EVENT_CONNECTION)
        def connected(connection):
            @connection.on(connection.EVENT_DISCONNECTION)
            def disconnected(_reason):
                receiver.disconnect(connection)

        properties = Characteristic.Properties
        characteristic = Characteristic(
            uuid,
            properties.READ | properties.WRITE | properties.WRITE_WITHOUT_RESPONSE | properties.NOTIFY,
            Characteristic.READABLE | Characteristic.WRITEABLE,
            CharacteristicValue(read=lambda _connection: b"", write=write),
        )
        device.add_services([Service(uuid, [characteristic])])
        device.advertising_data = b"\x02\x01\x06\x03\x03\x46\x24\x09\x09ODKindle"
        await device.power_on()
        await device.start_advertising(auto_restart=True)
        await hci.source.terminated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", help="Bumble HCI transport, or 'kindle-pw4' for guarded PW4 setup")
    parser.add_argument("device_config", help="Bumble device configuration JSON")
    parser.add_argument("output", type=Path, help="Destination for the raw packed monochrome frame")
    args = parser.parse_args()
    radio = kindle_radio if args.transport == "kindle-pw4" else nullcontext
    transport = KINDLE_TRANSPORT if args.transport == "kindle-pw4" else args.transport
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    with radio():
        asyncio.run(serve(transport, args.device_config, args.output))
