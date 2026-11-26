# /// script
# dependencies = ["bumble==0.0.236"]
# ///
"""Exercise the Rust receiver over H4, GAP, and GATT without Kindle hardware."""

import asyncio
import hmac
import json
import sys
import tempfile
import zlib
from contextlib import suppress
from pathlib import Path

from bumble import hci
from bumble.att import ATT_Error
from bumble.controller import Controller
from bumble.core import UUID
from bumble.device import Device, Peer
from bumble.link import LocalLink
from bumble.transport.common import PacketParser
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ADDRESS = "C2:00:00:00:00:02"
FRAME_BYTES = 1072 // 8 * 1448
KEY = bytes(range(32))
CONTEXT = b"kindle-control-v1\0"


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
    (directory / "control.key").write_text(KEY.hex())
    frame_path = directory / "frame.raw"
    server = await asyncio.start_server(transport, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        receiver = await asyncio.create_subprocess_exec(
            str(binary),
            f"tcp:127.0.0.1:{port}",
            str(identity),
            str(frame_path),
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
        await authenticated_control(peer)
    finally:
        await connection.disconnect()


async def authenticated_control(peer):
    uuids = [UUID(f"884cc76{i}-ea3a-4b7b-a8bd-114c4e5342ae") for i in range(4)]
    (service,) = await peer.discover_services(uuids[:1])
    challenge, request, response = await peer.discover_characteristics(
        uuids[1:], service
    )

    async def expect_denied(operation):
        try:
            await operation
        except ATT_Error as error:
            assert error.error_code == 8, error
        else:
            raise AssertionError("unauthenticated control was accepted")

    await expect_denied(peer.read_value(response))
    nonce = await peer.read_value(challenge)
    assert len(nonce) == 16
    header = CONTEXT + nonce + b"\x89"
    key = hmac.digest(KEY, b"kindle-control command request encryption", "sha256")
    packet = b"\x89" + AESGCM(key).encrypt(nonce[:12], b"id", header)
    await peer.write_value(request, packet, with_response=True)
    key = hmac.digest(KEY, b"kindle-control response encryption", "sha256")
    sealed = await peer.read_value(response)
    assert json.loads(AESGCM(key).decrypt(nonce[:12], sealed, header)) == {
        "error": "disabled"
    }
    await expect_denied(peer.write_value(request, packet, with_response=True))

    nonce = await peer.read_value(challenge)
    header = CONTEXT + nonce + b"\xc0"
    packet = b"\xc0" + hmac.digest(KEY, b"request\0" + header, "sha256")[:16]
    await peer.write_value(request, packet, with_response=True)
    sealed = await peer.read_value(response)
    # This transport intentionally has no Paperwhite sensors.
    assert AESGCM(key).decrypt(nonce[:12], sealed, header) == b"null"


async def main():
    with tempfile.TemporaryDirectory() as directory:
        await asyncio.wait_for(run(Path(sys.argv[1]).resolve(), Path(directory)), 30)


if __name__ == "__main__":
    asyncio.run(main())
