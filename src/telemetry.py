"""GT6 SimulatorInterface decoder and UDP recorder, Python standard library only.

Protocol information: Nenkai/PDTools (MIT), SimulatorInterfaceClient.cs,
SimulatorPacket.cs and SimulatorInterfaceCryptorGT6.cs. Salsa20 is implemented
from its public algorithm. A capture is a schematic trace, not rendered GT6 video.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
from pathlib import Path
import socket
import struct
import threading
import time
from datetime import datetime, timezone

GT6_SEND_PORT = 33339
GT6_RECEIVE_PORT = 33340
GT6_PACKET_SIZE = 0x128
GT6_KEY = b"Simulator Interface Packet ver 0.0"[:32]
_MASK = 0xFFFFFFFF


def _rotl(value: int, bits: int) -> int:
    value &= _MASK
    return ((value << bits) | (value >> (32 - bits))) & _MASK


def salsa20_xor(data: bytes, key: bytes, nonce: bytes) -> bytes:
    """Salsa20/20 with a 256-bit key, 64-bit nonce, initial block counter zero."""
    if len(key) != 32 or len(nonce) != 8:
        raise ValueError("Salsa20 needs a 32-byte key and an 8-byte nonce")
    constants = struct.unpack("<4I", b"expand 32-byte k")
    words = struct.unpack("<8I", key)
    iv = struct.unpack("<2I", nonce)
    state = [
        constants[0],
        *words[:4],
        constants[1],
        *iv,
        0,
        0,
        constants[2],
        *words[4:],
        constants[3],
    ]
    output = bytearray(len(data))
    for offset in range(0, len(data), 64):
        x = state.copy()
        for _ in range(10):
            for a, b, c, d in (
                (0, 4, 8, 12),
                (5, 9, 13, 1),
                (10, 14, 2, 6),
                (15, 3, 7, 11),
                (0, 1, 2, 3),
                (5, 6, 7, 4),
                (10, 11, 8, 9),
                (15, 12, 13, 14),
            ):
                x[b] ^= _rotl(x[a] + x[d], 7)
                x[c] ^= _rotl(x[b] + x[a], 9)
                x[d] ^= _rotl(x[c] + x[b], 13)
                x[a] ^= _rotl(x[d] + x[c], 18)
        stream = struct.pack("<16I", *[(x[i] + state[i]) & _MASK for i in range(16)])
        for i in range(min(64, len(data) - offset)):
            output[offset + i] = data[offset + i] ^ stream[i]
        state[8] = (state[8] + 1) & _MASK
        if state[8] == 0:
            state[9] = (state[9] + 1) & _MASK
    return bytes(output)


def decrypt_packet(data: bytes) -> bytes:
    """Decrypt one encrypted 296-byte GT6 UDP packet and verify its signature."""
    if len(data) != GT6_PACKET_SIZE:
        raise ValueError(f"Expected {GT6_PACKET_SIZE} GT6 packet bytes; received {len(data)}")
    seed = struct.unpack_from(">I", data, 0x40)[0]
    nonce = struct.pack("<II", seed ^ 0xDEADBEAF, seed)
    clear = salsa20_xor(data, GT6_KEY, nonce)
    if clear[:4] != b"G6S0":
        raise ValueError(
            "Packet is not a recognized GT6 SimulatorInterface packet (G6S0 signature missing)"
        )
    return clear


def decode_packet(data: bytes, *, decrypted: bool = False) -> dict:
    """Decode GT6 big-endian numeric fields; controls are normalized to [0,1]."""
    clear = data if decrypted else decrypt_packet(data)
    if len(clear) != GT6_PACKET_SIZE or clear[:4] != b"G6S0":
        raise ValueError("Invalid clear GT6 SimulatorInterface packet")

    def floats(offset, count=1):
        values = struct.unpack_from(">" + "f" * count, clear, offset)
        return values[0] if count == 1 else values

    position = floats(4, 3)
    velocity = floats(0x10, 3)
    quaternion = floats(0x1C, 4)
    speed = floats(0x4C)
    rpm = floats(0x3C)
    if not all(math.isfinite(v) for v in (*position, *velocity, *quaternion, speed, rpm)):
        raise ValueError("GT6 packet contains non-finite motion fields")
    packet_id = struct.unpack_from(">I", clear, 0x70)[0]
    lap, total_laps = struct.unpack_from(">hh", clear, 0x74)
    flags = struct.unpack_from(">H", clear, 0x8E)[0]
    gear_bits = clear[0x90]
    return {
        "packet_id": packet_id,
        "x": position[0],
        "y": position[1],
        "z": position[2],
        "vx": velocity[0],
        "vy": velocity[1],
        "vz": velocity[2],
        "qx": quaternion[0],
        "qy": quaternion[1],
        "qz": quaternion[2],
        "qw": quaternion[3],
        "speed_kmh": speed * 3.6,
        "rpm": rpm,
        "throttle": clear[0x91] / 255.0,
        "brake": clear[0x92] / 255.0,
        "gear": gear_bits & 15,
        "suggested_gear": gear_bits >> 4,
        "lap": lap,
        "total_laps": total_laps,
        "car_code": struct.unpack_from(">i", clear, 0x124)[0],
        "flags": flags,
        "on_track": bool(flags & 1),
        "paused": bool(flags & 2),
        "loading": bool(flags & 4),
        "best_lap_ms": struct.unpack_from(">i", clear, 0x78)[0],
        "last_lap_ms": struct.unpack_from(">i", clear, 0x7C)[0],
        "time_of_day_ms": struct.unpack_from(">i", clear, 0x80)[0],
    }


class GT6TelemetryRecorder:
    """Nonblocking UI-friendly recorder. Only explicitly targeted IPv4 is accepted.

    `start()` binds before starting a daemon thread; `stop()` returns promptly.
    `status()` is inexpensive, while `snapshot()` copies recorded frames safely.
    Paused/loading packets are counted but omitted from frames. GT6 replay
    packets can lack the on-track flag and car code, so moving replay packets
    are recorded too; a running segment retains stationary frames.
    """

    def __init__(
        self,
        host: str,
        bind_host: str = "0.0.0.0",
        *,
        receive_port: int = GT6_RECEIVE_PORT,
        send_port: int = GT6_SEND_PORT,
        heartbeat_seconds: float = 5.0,
        max_frames: int = 1_000_000,
    ):
        self.host = str(ipaddress.IPv4Address(host.strip()))
        self.bind_host = str(ipaddress.IPv4Address(bind_host))
        self.receive_port = int(receive_port)
        self.send_port = int(send_port)
        self.heartbeat_seconds = max(0.5, float(heartbeat_seconds))
        self.max_frames = max(1, int(max_frames))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._sock = None
        self._frames = []
        self._error = None
        self._invalid = 0
        self._packets = 0
        self._discarded = 0
        self._lost = 0
        self._resets = 0
        self._started_at = None
        self._last_packet_at = None
        self._last_packet = None
        self._last_id = None
        self._last_active = False
        self._timeline = 0.0
        self._running = False

    def start(self):
        if self._thread is not None:
            raise RuntimeError(
                "This recorder already started; create a new recorder for another capture"
            )
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.bind_host, self.receive_port))
            sock.settimeout(0.25)
        except Exception:
            sock.close()
            raise
        self._sock = sock
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="GT6-UDP-recorder", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.6)
        with self._lock:
            self._running = False
        return self.status()

    def _run(self):
        last_heartbeat = -math.inf
        sock = self._sock
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_seconds:
                    sock.sendto(b"A", (self.host, self.send_port))
                    last_heartbeat = now
                try:
                    raw, address = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                if address[0] != self.host:
                    continue
                try:
                    frame = decode_packet(raw)
                except ValueError:
                    with self._lock:
                        self._invalid += 1
                    continue
                with self._lock:
                    self._packets += 1
                    self._last_packet_at = time.monotonic()
                    self._last_packet = frame
                    moving = frame["speed_kmh"] > 0.1 or any(
                        abs(frame[key]) > 0.02 for key in ("vx", "vy", "vz")
                    )
                    active = (
                        not frame["paused"]
                        and not frame["loading"]
                        and (frame["on_track"] or moving or self._last_active)
                    )
                    current_id = frame["packet_id"]
                    delta = 1 if self._last_id is None else (current_id - self._last_id) & _MASK
                    if self._last_id is not None and delta == 0:
                        self._discarded += 1
                        continue
                    # A small backward move is an out-of-order datagram. A large
                    # backward move denotes a reset/new replay, kept as a segment.
                    if delta > 0x80000000:
                        backward = (self._last_id - current_id) & _MASK
                        if backward < 120:
                            self._discarded += 1
                            continue
                        self._resets += 1
                        delta = 1
                    if self._last_active and active and self._frames:
                        self._timeline += delta / 60.0
                        self._lost += max(0, delta - 1)
                    elif active and self._frames:
                        self._timeline += 1.0 / 60.0
                    self._last_id = current_id
                    self._last_active = active
                    if not active:
                        continue
                    frame["time_seconds"] = round(self._timeline, 6)
                    frame["segment"] = self._resets
                    if len(self._frames) >= self.max_frames:
                        self._error = f"Capture reached {self.max_frames:,} frames; stop and save this recording"
                        self._stop.set()
                    else:
                        self._frames.append(frame)
        except OSError as exc:
            if not self._stop.is_set():
                with self._lock:
                    self._error = str(exc)
        except Exception as exc:
            with self._lock:
                self._error = f"Recorder failed: {exc}"
        finally:
            sock.close()
            with self._lock:
                self._running = False

    def status(self) -> dict:
        with self._lock:
            ago = (
                None
                if self._last_packet_at is None
                else max(0, time.monotonic() - self._last_packet_at)
            )
            return {
                "running": self._running,
                "host": self.host,
                "frames": len(self._frames),
                "packets": self._packets,
                "invalid_packets": self._invalid,
                "discarded_packets": self._discarded,
                "lost_packets": self._lost,
                "segments": self._resets + (1 if self._frames else 0),
                "duration_seconds": self._timeline,
                "last_packet_seconds_ago": ago,
                "error": self._error,
                "started_at": self._started_at,
                "last_packet": None if self._last_packet is None else dict(self._last_packet),
            }

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            frames = [dict(frame) for frame in self._frames[max(0, int(since)) :]]
        return {
            "schema": "gt6-pc-trace-1",
            "source": "GT6 SimulatorInterface UDP capture",
            "host": self.host,
            "created_utc": self._started_at,
            "fps": 60,
            "frames": frames,
            "capabilities": {
                "position": True,
                "orientation": True,
                "telemetry": True,
                "game_graphics": False,
                "all_cars": False,
            },
        }

    def save(self, path: str | Path):
        path = Path(path)
        document = self.snapshot()
        if not document["frames"]:
            raise ValueError("No active GT6 frames have been captured yet")
        # Atomic replacement avoids leaving a partial user-facing file.
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(
            json.dumps(document, separators=(",", ":"), allow_nan=False), encoding="utf-8"
        )
        temp.replace(path)
        return path


def _main():
    parser = argparse.ArgumentParser(
        description="Record GT6 UDP motion data for a PC schematic replay"
    )
    parser.add_argument("host", help="PS3 IPv4 address; 127.0.0.1 for local RPCS3")
    parser.add_argument("output", type=Path, help="Output JSON trace")
    parser.add_argument(
        "--seconds",
        type=float,
        default=0,
        help="Stop after this many wall-clock seconds; 0 waits for Ctrl+C",
    )
    args = parser.parse_args()
    recorder = GT6TelemetryRecorder(args.host).start()
    deadline = time.monotonic() + args.seconds if args.seconds > 0 else math.inf
    print(f"Listening on UDP {GT6_RECEIVE_PORT}. Play the GT6 replay; Ctrl+C stops the capture.")
    try:
        while recorder.status()["running"] and time.monotonic() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()
    if recorder.status()["error"]:
        print(recorder.status()["error"])
    if not recorder.status()["frames"]:
        parser.exit(
            1, "No active frames captured. Check the target IP and play an unpaused GT6 replay.\n"
        )
    recorder.save(args.output)
    print(f"Saved {recorder.status()['frames']} frames to {args.output}")


if __name__ == "__main__":
    _main()
