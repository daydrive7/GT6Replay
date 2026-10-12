# GT6Replay Decoder

GT6Replay Decoder is a separate desktop program and command-line utility. It can be built without building the viewer. The 0.2.0 Beta viewer package also includes it under `Decoder/` and opens it through **Tools → Replay decoder**.

**This beta exports decrypted RPLY data and race reports. It cannot yet produce full-motion `.gt6r` archives.** Course and car identifiers are displayed as IDs; a name catalogue is not included.

## Desktop program

Run `GT6ReplayDecoder.exe` and keep `_internal` alongside it. Choose an original replay export folder or a decrypted `.rply` file. **Inspect** previews race results. Select **Decrypted replay** or **Race report**, choose an output outside the original save folder, and select **Export**.

Encrypted exports require the matching `PARAM.PFD` and a local savedata key configuration. **Choose key file** validates that configuration and remembers its location for both the decoder and GT6Replay. The program does not include default keys. Configuration values are not copied into settings, reports, or program packages.

The key file is JSON with `portability_key` and `secure_file_id`, each a 32-character hexadecimal value. Supply a configuration you are entitled to use. Test configurations in the automated suite contain invented values. `GT6REPLAY_KEY_FILE` overrides the selected location; `--keys PATH` overrides both for a CLI operation.

GT6Replay can use the same configuration to read race metadata directly from an encrypted export. A matching decoded archive still enables motion playback; otherwise the viewer shows race results and states that motion is unavailable.

## Command line

```powershell
.\GT6ReplayDecoderCLI.exe --capabilities
.\GT6ReplayDecoderCLI.exe --input "D:\MyReplay" --keys "D:\my-keys.json" --inspect
.\GT6ReplayDecoderCLI.exe --input "D:\MyReplay" --keys "D:\my-keys.json" --output "D:\Exports\race.rply" --format rply
.\GT6ReplayDecoderCLI.exe --input "D:\Exports\race.rply" --output "D:\Exports\race.json" --format report
```

The CLI returns 0 on success, 1 on input/export failure, 2 for invalid arguments, and 3 for unsupported full-motion conversion. Existing outputs require `--overwrite`. Original savedata files are never overwritten. No console connection or external service is used during inspection/export.

The viewer's external motion-decoder interface still accepts `--input` and `--output`. The included utility reports `motion_archive: false`; it must not be used as a working full-motion converter. A requested `.gt6r` output returns a clear error without creating an archive.

## Independent build

Requires Python 3.13 on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_decoder.ps1
```

The command installs `requirements-decoder-build.txt`, preserves dependency notices and matching Qt/PySide source archives, builds both decoder executables, audits the result, and runs executable checks against synthetic protected savedata. The output is `dist/GT6ReplayDecoder/`. No existing viewer executable, private replay, private research tool, or game installation is needed.

For source use, install `requirements-decoder.txt`, then run `python src/decoder_program.py` for the desktop window or `python src/decoder_program.py --cli --help` for CLI usage. `scripts/build.ps1` builds both programs and places the decoder in the viewer package.

Use `-DistributionPath dist-dev` to preserve an existing build. `-SkipInstall` is for an environment with the pinned dependencies already installed. Building may download development dependencies and corresponding source; running the installed utility is local. Preserve `LICENSE`, `THIRD_PARTY.md`, all notices, and the matching source archives when publishing binaries.
