# 0.2.0 development

- Separate GT6Replay Decoder desktop program and command-line executable.
- Independent decoder build, packaging, and executable checks.
- Viewer Decoder menu and shared local key-file configuration.
- Encrypted race-metadata import using the independent savedata reader.
- Decrypted RPLY and race-report exports, with original files protected.
- Version-115 seek/parameter readers, absolute-transform readers, and accuracy comparison tools.

Full snapshot and compressed-frame decoding remain unfinished. This development utility cannot produce a full-motion `.gt6r` archive. Protected data requires a user-supplied key configuration. No game engine code, assets, savedata keys, original examples, or personal recordings are distributed. The published 0.1.0 release is unchanged.

Corresponding Qt/PySide source archives are release assets alongside the Windows ZIP. Checksums are provided for the application and source archives. The Windows executable is unsigned.
