# GT6Replay

GT6Replay is a Windows viewer for decoded Gran Turismo 6 replays. It displays a track map, schematic 3D car motion, telemetry, and sortable race results. This branch develops 0.2.0; the published release remains 0.1.0.

## Supported inputs

- Decoded `.gt6r` files in the `gt6-native-motion-v1` format: offline playback of all recorded cars.
- GT6Replay JSON recordings: playback of a single car's telemetry.
- Decrypted RPLY version 115 files: race metadata and results.
- Original PS3 save folders: playback when a matching decoded file is available; encrypted race metadata can be read with a configured savedata key file.

**Full-motion conversion is not implemented yet.** The development package includes a standalone decoder utility for decrypted RPLY export and race reports. Opening an unconverted export provides race metadata, not car motion. The package includes no game executable, translated game code, savedata keys, game assets, or replay files. The viewer does not reproduce GT6's original graphics, sound, or replay cameras. Native accelerator and brake channels are not mapped.

## Use

Extract the Windows download and run `GT6Replay.exe`. Keep `_internal` beside the executable. A separate Python installation is not needed for the viewer.

Choose **Open replay** for a `.gt6r`, JSON, or decrypted RPLY file. **Open save folder** opens a savedata export. All cars are shown by default; selecting a driver highlights their car and shows their telemetry. Turn off **Show all cars** to focus on that driver.

- Left-drag pans; the mouse wheel zooms around the pointer.
- Right-drag orbits the 3D view.
- **Fit view** or double-click resets the camera.
- Space plays or pauses; Home restarts. Use the timeline and speed control to navigate.

Click any results header to sort. Position, times, gap, and laps sort numerically; missing values remain last. **Columns** or a right-click on the header selects visible columns. **Gap** is recorded race time minus the winner's race time. **Laps** is the highest recorded lap number, including an unfinished lap. Unclassified drivers have no recorded finish result.

**Record** and **PS3 FTP** are optional console tools. Enter your own console address. FTP only downloads savedata; recording uses UDP ports 33339 and 33340. Replay playback does not open a network connection.

## External decoders

**Tools → Replay decoder** opens the separate `GT6ReplayDecoder.exe` program included with development builds. It can also be downloaded or built on its own. **Tools → Choose savedata key file** shares the selected configuration with the utility and enables encrypted race-metadata imports. See the [decoder guide](docs/decoder.md) for desktop use, CLI arguments, and its independent build command.

Set `GT6REPLAY_DECODER` to a trusted decoder executable or Python script, or start `GT6Replay.exe --decoder PATH`. The viewer runs it with `--input PATH --output PATH`; it must produce a valid `.gt6r` file. Configuring a decoder allows the program to execute that tool. Python decoders need Python installed separately.

Decoded files are cached under the current user's application-data directory. Save exports are never modified. A cached file is attached to a save only when its recorded source-file hashes match the current export.

## Development

Requires Python 3.13. Install `requirements-decoder.txt` for development and tests, then run `python src/app.py`. Run tests with `python -m unittest discover -s tests -v`. `scripts/build.ps1` builds the Windows folder and checks the release contents; `scripts/package_release.py` prepares the ZIP and checksums.

`scripts/build_decoder.ps1` builds only the standalone decoder. `scripts/build.ps1` builds both programs and includes the decoder in the viewer folder. `scripts/package_release.py --decoder-only` packages the standalone utility separately. Development artifacts are labelled `0.2.0-dev`; the release workflow rejects development version strings.

The independent motion codec is being developed for 0.2.0. Its current container and absolute-transform readers do not yet convert a complete replay. See the [0.2.0 roadmap](docs/roadmap-0.2.0.md) and [replay codec documentation](docs/replay-codec.md). The released 0.1.0 viewer remains unchanged and still requires decoded motion or an external decoder.

See [testing](docs/testing.md), [file format](docs/format.md), [release review](docs/release-review.md), and [third-party notices](THIRD_PARTY.md). The first release has limited real-replay coverage; it does not claim support for every GT6 replay variant.

## License and affiliation

The application code is MIT-licensed. Runtime dependencies retain their own licenses. The Windows package uses replaceable Qt/PySide shared libraries; corresponding-source downloads and replacement instructions are in [THIRD_PARTY.md](THIRD_PARTY.md).

GT6Replay is an independent project, not affiliated with or endorsed by Sony Interactive Entertainment or Polyphony Digital. Gran Turismo and related names belong to their respective owners. No official logo is used.
