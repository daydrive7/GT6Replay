# Testing

Run `python -m unittest discover -s tests -v` before building. Automated coverage includes numeric and name sorting, missing-result ordering, stable driver selection after sorting/reloading, shared race timing, retired-car disappearance, pan, pointer-centered zoom, orbit, malformed archive headers, decrypted metadata boundaries, cache identity, and telemetry parsing/recording.

The initial local integration check uses one user-provided native replay with multiple drivers. That replay is not committed or bundled. Automated fixtures are synthetic. Broad compatibility with other replay versions, event modes, and corrupted real exports remains unverified.

Before expanding compatibility, test additional offline/online races, time trials, late joiners, long events, multiple car counts, and savedata regions. Check 100/125/150/200% display scaling, small screens, keyboard navigation, long driver/car names, seek/loop at the end, exports, and read-only installation folders. Test new decoder implementations against independently verified motion rather than accepting plausible-looking paths.

Run the packaged executable with `--verify-playback INPUT REPORT` for a local integration check. Network access is forbidden during that check. Reports/screenshots are local artifacts and must not be committed when they contain private replay data.

CI tests the source on Windows and builds/audits the distributable. Unsigned-binary reputation and SmartScreen behavior require a separate distribution check.
