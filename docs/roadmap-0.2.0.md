# 0.2.0 roadmap

The target is a free, maintainable local converter: open an original GT6 replay export, decode it on the PC, and play it without contacting a maintainer or running a conversion service.

| Priority | Feature | Acceptance criterion |
| --- | --- | --- |
| 1 | Independent decoder | Read original `REPLAY.N` files and reconstruct full recorded motion without game executables, translated instructions, emulator modules, or an external decoder executable. |
| 2 | Accuracy testing | Compare every frame and driver against reference output, verify visibility and timing, report numerical errors, and reject unsupported layouts. |
| 3 | Offline conversion | Convert with networking blocked, preserve original files, and write a validated `.gt6r` archive atomically. No PS3 is needed during conversion. |
| 4 | Open-source release | Publish the working decoder, synthetic test vectors, dependency notices, reproducible build instructions, and ordinary contribution paths. No private maintainer files may be required to build or run it. |
| 5 | Format documentation | Document savedata, headers, seek points, encoding parameters, snapshots, compressed updates, units, and compatibility limits. |

## Development status

- Implemented: bounded bit reader; PFD entry reader; independently written savedata decryption with supplied keys; consecutive-chunk assembly and fingerprints; version-115 seek index and version-49 encoding-parameter reader; absolute transform reader; full-archive comparison tool.
- Verified locally: one protected five-chunk export decrypts byte-for-byte to the reference; all 32 slot parameter sets match; 721 absolute transforms at 94 checkpoints match position, velocity, and orientation exactly.
- Remaining: independent traversal of complete snapshot packets, compressed updates and prediction state, all-driver frame assembly, RPM/gear/lap decoding, automatic protected-save configuration, viewer integration, additional real-replay coverage, and release packaging.

The checkpoint comparison uses the private reference decoder to identify transform packet boundaries. Those locations are not built into the independent reader. It is not an independent full replay conversion yet.

Encrypted `REPLAY.0–4` files also require `PARAM.PFD` from the same save export; a different number of chunks is valid. Keep `PARAM.SFO` for the export description. The final user interface should accept the whole folder and explain missing files directly.

The development savedata API accepts a key configuration. Test fixtures use invented keys, and local reference validation supplies its configuration outside the repository. Default configuration and its distribution need to be resolved before the promised ordinary-user workflow is complete. Requiring users to contact the maintainer for conversion is not an acceptable release substitute.

## Release gate

0.2.0 is ready only after all five acceptance criteria pass. A header reader, an absolute-checkpoint reader, plausible-looking motion, or an external-decoder adapter alone does not satisfy the independent-decoder requirement. Validate a complete race first, then expand coverage to other races and event modes before claiming broader compatibility.

Independent implementation reduces the need to distribute game code. It does not itself establish legal clearance. Maintain source provenance and dependency notices, and review the actual implementation and savedata handling before publication. This work is informed by format research; no formal clean-room process is claimed.
