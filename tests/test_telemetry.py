import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest

import telemetry


def encrypted_frame(packet_id=100, flags=1):
    clear = bytearray(296)
    clear[:4] = b"G6S0"
    struct.pack_into(">3f", clear, 4, 123.5, 4.25, -56.5)
    struct.pack_into(">3f", clear, 0x10, 5.0, 0.0, 25.0)
    struct.pack_into(">4f", clear, 0x1C, 0.0, 0.0, 0.0, 1.0)
    struct.pack_into(">f", clear, 0x3C, 6123.0)
    struct.pack_into(">f", clear, 0x4C, 30.0)
    struct.pack_into(">Ihh", clear, 0x70, packet_id, 2, 5)
    struct.pack_into(">H", clear, 0x8E, flags)
    clear[0x90:0x93] = bytes((0x43, 255, 128))
    struct.pack_into(">i", clear, 0x124, 777)
    seed = 0x01234567
    nonce = struct.pack("<II", seed ^ 0xDEADBEAF, seed)
    stream = telemetry.salsa20_xor(bytes(296), telemetry.GT6_KEY, nonce)
    # The sent IV slot contains the clear nonce seed even though all bytes are
    # processed by the stream cipher; arrange the clear slot to achieve this.
    clear[0x40:0x44] = bytes(a ^ b for a, b in zip(struct.pack(">I", seed), stream[0x40:0x44]))
    raw = telemetry.salsa20_xor(bytes(clear), telemetry.GT6_KEY, nonce)
    return raw


class TelemetryTests(unittest.TestCase):
    def test_salsa20_known_zero_vector(self):
        expected = "9a97f65b9b4c721b960a672145fca8d4e32e67f9111ea979ce9c4826806aeee63de9c0da2bd7f91ebcb2639bf989c6251b29bf38d39a9bdce7c55f4b2ac12a39"
        self.assertEqual(telemetry.salsa20_xor(bytes(64), bytes(32), bytes(8)).hex(), expected)

    def test_big_endian_fields(self):
        frame = telemetry.decode_packet(encrypted_frame())
        self.assertEqual((frame["x"], frame["y"], frame["z"]), (123.5, 4.25, -56.5))
        self.assertEqual(frame["speed_kmh"], 108)
        self.assertEqual(frame["rpm"], 6123)
        self.assertEqual((frame["gear"], frame["suggested_gear"]), (3, 4))
        self.assertEqual((frame["lap"], frame["total_laps"], frame["car_code"]), (2, 5, 777))
        self.assertEqual(frame["throttle"], 1)
        self.assertAlmostEqual(frame["brake"], 128 / 255)

    def test_invalid_packets(self):
        for bad in (b"", bytes(296), bytes(300)):
            with self.assertRaises(ValueError):
                telemetry.decode_packet(bad)

    def test_udp_and_save(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        server.settimeout(2)
        receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receive_socket.bind(("127.0.0.1", 0))
        receive_port = receive_socket.getsockname()[1]
        receive_socket.close()
        heartbeats = []

        def send_packets():
            heartbeat, address = server.recvfrom(4096)
            heartbeats.append(heartbeat)
            # GT6 saved replay motion may set neither OnTrack nor car code.
            # Accept that motion after pause even with flags=0.
            packets = [(100, 1), (101, 1), (101, 1), (102, 3), (103, 0), (105, 0), (104, 0)]
            server.sendto(b"invalid", address)
            for packet_id, flags in packets:
                server.sendto(encrypted_frame(packet_id, flags), address)
            server.close()

        thread = threading.Thread(target=send_packets)
        thread.start()
        recorder = telemetry.GT6TelemetryRecorder(
            "127.0.0.1", receive_port=receive_port, send_port=server.getsockname()[1]
        ).start()
        deadline = time.monotonic() + 2
        while recorder.status()["packets"] < 7 and time.monotonic() < deadline:
            time.sleep(0.01)
        recorder.stop()
        thread.join(2)
        status = recorder.status()
        self.assertEqual(heartbeats, [b"A"])
        self.assertEqual(status["frames"], 4)
        self.assertEqual(status["invalid_packets"], 1)
        self.assertEqual(status["discarded_packets"], 2)
        self.assertEqual(status["lost_packets"], 1)
        times = [f["time_seconds"] for f in recorder.snapshot()["frames"]]
        self.assertEqual(times, [0, 0.016667, 0.033333, 0.066667])
        with tempfile.TemporaryDirectory() as directory:
            path = recorder.save(Path(directory) / "capture.json")
            document = json.loads(path.read_text())
            self.assertEqual(len(document["frames"]), 4)
            self.assertEqual(document["schema"], "gt6-pc-trace-1")


if __name__ == "__main__":
    unittest.main()
