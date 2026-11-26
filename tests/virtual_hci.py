# /// script
# dependencies = ["bumble==0.0.236"]
# ///
"""Exercise the Rust receiver over H4, GAP, and GATT without Kindle hardware."""

import asyncio
import json
import sys
import tempfile
import zlib
from contextlib import suppress
from pathlib import Path

from bumble import hci
from bumble.controller import Controller
from bumble.core import UUID
from bumble.device import Device, Peer
from bumble.link import LocalLink
from bumble.transport.common import PacketParser

ADDRESS = "C2:00:00:00:00:02"
FRAME_BYTES = 1072 // 8 * 1448


class Sink:
    def __init__(self, writer):
        self.writer = writer

    def on_packet(self, packet):
        self.writer.write(packet)


async def run(binary, directory):
    link = LocalLink()
    peripheral_controller = Controller("receiver", link=link)
    central_controller = Controller("client", link=link)
    central = Device.with_hci(
        "OpenDisplay test client",
        hci.Address("C2:00:00:00:00:01"),
        central_controller,
        central_controller,
    )
    await central.power_on()

    async def transport(reader, writer):
        peripheral_controller.set_packet_sink(Sink(writer))
        parser = PacketParser(peripheral_controller)
        try:
            with suppress(ConnectionResetError):
                while data := await reader.read(4096):
                    parser.feed_data(data)
        finally:
            writer.close()
            with suppress(ConnectionResetError):
                await writer.wait_closed()

    identity = directory / "device.json"
    identity.write_text(json.dumps({"name": "ODTest", "address": ADDRESS}))
    frame_path = directory / "frame.raw"
    server = await asyncio.start_server(transport, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        receiver = await asyncio.create_subprocess_exec(
            str(binary),
            f"tcp:127.0.0.1:{port}",
            str(identity),
            str(frame_path),
            "--experimental-display-only",
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            status = await receiver.stderr.readline()
            assert status == b"Kindle BLE advertising started\n", status
            for _ in range(2):
                await transfer(central, frame_path)
        finally:
            if receiver.returncode is None:
                receiver.terminate()
            _, log = await receiver.communicate()
            if log:
                sys.stderr.buffer.write(log)
        assert receiver.returncode == 0, receiver.returncode


async def transfer(central, frame_path):
    connection = await central.connect(hci.Address(ADDRESS))
    try:
        peer = Peer(connection)
        await peer.request_mtu(185)
        uuid = UUID.from_16_bits(0x2446)
        (service,) = await peer.discover_services([uuid])
        (command,) = await peer.discover_characteristics([uuid], service)
        responses = asyncio.Queue()
        await peer.subscribe(command, responses.put_nowait)

        async def send(opcode, payload=b""):
            await peer.write_value(
                command, bytes((0, opcode)) + payload, with_response=True
            )
            return await responses.get()

        config = await send(0x40)
        assert config[:6] == b"\x00\x40\x00\x00\x85\x00", config
        assert len(config) == 139
        frame = bytes((0xAA, 0x55)) * (FRAME_BYTES // 2)
        assert await send(0x70, FRAME_BYTES.to_bytes(4, "little")) == b"\x00\x70"
        compressed = zlib.compress(frame)
        for offset in range(0, len(compressed), 100):
            assert await send(0x71, compressed[offset : offset + 100]) == b"\x00\x71"
        assert await send(0x72) == b"\x00\x72"
        assert await responses.get() == b"\x00\x73"
        assert frame_path.read_bytes() == frame
    finally:
        await connection.disconnect()


async def main():
    with tempfile.TemporaryDirectory() as directory:
        await asyncio.wait_for(run(Path(sys.argv[1]).resolve(), Path(directory)), 30)


if __name__ == "__main__":
    asyncio.run(main())
