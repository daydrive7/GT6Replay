# 0.2.0 Beta

- Separate GT6Replay Decoder desktop program and command-line executable.
- Independent decoder build, packaging, and executable checks.
- Viewer Decoder menu and shared local key-file configuration.
- Local savedata decryption and race-metadata decoding using the independent reader.
- Decrypted RPLY and race-report exports, with original files protected.
- Version-115 seek/parameter readers, absolute-transform readers, and accuracy comparison tools.

Course and car identifiers are displayed as IDs; a name catalogue is not included. Full snapshot and compressed-frame decoding remain unfinished, so this beta cannot convert an original replay into a full-motion `.gt6r` archive. Existing decoded archives still support offline motion playback.

Protected data requires a user-supplied key configuration and the matching `PARAM.PFD`. No game engine code, assets, savedata keys, original examples, or personal recordings are distributed. The published 0.1.0 release remains the stable release.

Automated validation covers 68 tests, independent and combined Windows builds, package audits, and executable checks without Python on PATH. Real-replay coverage is limited; broader replay compatibility needs further testing.

Download `GT6Replay-0.2.0-beta.1-windows-x64.zip` for the viewer with the included decoder, or `GT6ReplayDecoder-0.2.0-beta.1-windows-x64.zip` for the standalone desktop and command-line utilities. Extract the whole ZIP before running an executable. A separate Python installation is not required.

Corresponding Qt/PySide source archives are release assets alongside the Windows ZIP. Checksums are provided for the application and source archives. The Windows executable is unsigned.
