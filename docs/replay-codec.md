# GT6 replay codec: verified structure

This document describes the independent reader under development. It does not describe a completed full-motion decoder. Offsets below are relative to the joined, decrypted `RPLY` data unless stated otherwise. Multi-byte replay fields use big-endian order; packed fields are read most-significant bit first.

## Savedata container

An original export contains consecutive `REPLAY.N` chunks starting at zero. A protected export also requires `PARAM.PFD` from that export. The chunk count is not fixed at five. `PARAM.SFO` contains optional display metadata.

PFD versions 3 and 4 use a big-endian header and a filename-indexed record table. The table dimensions begin at byte 96, followed by bucket indices and 272-byte file records. Relevant record fields are the filename at byte 8, wrapped key material at byte 80, content HMAC at byte 144, and original size at byte 264. Validate dimensions, filenames, duplicate entries, and chunk membership before reading data.

Protected chunks use a savedata key configuration, HMAC-SHA1 integrity checking, a CBC-wrapped file key, and AES block processing with a block-index mask. The encrypted size rounds the recorded size up to 16 bytes. Check integrity before decryption and discard padding after decryption. The independently written reader never writes into the export. The construction and PFD layout are described in [flatz's pfdtool implementation](https://github.com/bucanero/pfd_sfo_tools/blob/master/pfdtool/src/pfd.c) and [container definitions](https://github.com/bucanero/pfd_sfo_tools/blob/master/pfdtool/src/pfd_internal.h); no pfdtool code is bundled.

## Replay header and index

| Byte offset | Field | Verified value or interpretation |
| --- | --- | --- |
| `0x000` | Magic | `RPLY` |
| `0x008` | Replay version, u32 | 115 |
| `0x010` | Three protocol versions, u32 | 21, 17, 49 |
| `0x240` | Entrant-table capacity, u32 | Up to 32 slots |
| `0x244` | Entrant-table offset, u32 | Absolute byte offset |
| `0x248` | Recorded frame count, u32 | 60 Hz clock |
| `0x264` | Encoding-parameter block, u32 | Absolute byte offset |
| `0x282` | Entrant-table record stride, u16 | Bytes |
| `0x288` | Active-driver mask, u32 | Header metadata |
| `0x28C` | Seek-point count, u32 | Includes terminal entry |
| `0x294` | Seek-table offset, u32 | Absolute byte offset |

Each seek entry consists of two u32 values: byte offset and frame number. The first frame is zero and the terminal frame is the recorded count. Both byte and frame positions must increase. The terminal entry bounds the last segment; it is not another replay frame.

The entrant metadata reader is described by the MIT-licensed [PDTools replay definitions](https://github.com/Nenkai/PDTools/blob/master/PDTools.Structures/PS3/MReplayInfo.cs). It is separate from the motion codec.

## Per-slot encoding parameters

The block at `0x264` begins with an 8-bit slot count, followed by one parameter record for each slot. Version 49 has:

- Two 32-bit transform reference words.
- Four wheel parameter groups, each containing two reference words, a vector encoding record, and a scalar encoding record.
- Two 6-bit control widths.
- Fourteen vector encoding records and fourteen scalar encoding records, interleaved according to `SlotEncoding.read`.

A vector record contains a 6-bit width and six float32 coefficients. A scalar record contains a 6-bit width, two one-bit flags, and three float32 coefficients. Coefficient meanings are not yet fully documented; the current reader preserves them without inventing channel labels. Widths and flags must not be treated as arbitrary fixed byte lengths for compressed motion.

One version-49 slot parameter record occupies 5768 bits. All parameter records and their final bit position have been compared against the private reference on one real replay.

## Absolute transforms

At the beginning of an absolute car transform, the packed stream stores thirteen float32 values in this order:

1. Velocity: x, y, z.
2. Position: x, y, z.
3. Angular velocity: x, y, z.
4. Quaternion: x, y, z, w.

Position is in metres and velocity in metres per second. These records can begin at an unaligned bit position. Reject non-finite values and invalid quaternions. The absolute transform component matches the reference at all 94 checkpoints tested, covering 721 present-car transforms.

The independent reader cannot yet locate those car records by walking the entire snapshot format. Private validation obtains packet locations from the reference decoder; these locations are not part of the public implementation.

## Work still required

Document and implement snapshot envelopes, global and driver records, optional event records, car-state fields, wheel records, predictor state, compressed transform/scalar updates, and per-frame presence rules. RPM, gear, and lap need verified mappings. Compressed frames must consume the correct number of bits up to the next seek boundary; decoding only absolute transforms does not reconstruct a race.

The independently decoded `.gt6r` output must follow the [motion archive format](format.md). Keep private replays and reference tools out of the public test corpus; use synthetic vectors for portable regression tests.
