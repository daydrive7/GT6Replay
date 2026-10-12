# Testing

Run `python -m unittest discover -s tests -v` before building. Automated coverage includes numeric and name sorting, missing-result ordering, stable driver selection after sorting/reloading, shared race timing, retired-car disappearance, pan, pointer-centered zoom, orbit, malformed archive headers, decrypted metadata boundaries, cache identity, and telemetry parsing/recording.

The initial local integration check uses one user-provided native replay with multiple drivers. That replay is not committed or bundled. Automated fixtures are synthetic. Broad compatibility with other replay versions, event modes, and corrupted real exports remains unverified.

Before expanding compatibility, test additional offline/online races, time trials, late joiners, long events, multiple car counts, and savedata regions. Check 100/125/150/200% display scaling, small screens, keyboard navigation, long driver/car names, seek/loop at the end, exports, and read-only installation folders. Test new decoder implementations against independently verified motion rather than accepting plausible-looking paths.

Run the packaged executable with `--verify-playback INPUT REPORT` for a local integration check. Network access is forbidden during that check. Reports/screenshots are local artifacts and must not be committed when they contain private replay data.

CI tests the source on Windows and builds/audits the distributable. Unsigned-binary reputation and SmartScreen behavior require a separate distribution check.

## Independent decoder development

Install `requirements-decoder.txt` before running the development tests. New coverage checks bit ordering and stream bounds, PFD versions 3/4, encrypted-chunk integrity, padding and cipher counters across batch boundaries, consecutive chunks, read-only imports, seek-table corruption, absolute transforms, and motion-comparison failures. All committed fixtures are synthetic and use test keys.

For complete candidate output, run `python scripts/compare_decoders.py candidate.gt6r reference.gt6r --report comparison.json`. The comparator requires the same decrypted replay fingerprint, frame count, frame clock, and driver slots. It checks every recorded frame, including driver presence. Quaternion signs are equivalent; orientation differences are reported as angles. Gear and lap must match exactly. Position, velocity, orientation, and RPM tolerances are explicit in the report and can be overridden on the command line. A mismatch exits with code 1; incompatible input exits with code 2.

Private integration checks currently establish byte-for-byte decryption of one original five-chunk export, matching parameters for all 32 encoding slots, and exact position/velocity/orientation for 721 car transforms at 94 seek checkpoints. Packet locations for those transform checks come from the reference decoder. This is component validation, not a passing independent full-race decode. Reference inputs, game-dependent research tools, keys, packet-location lists, and personal reports are not committed.
