# Security

Only configure external decoders you trust: the decoder is an executable, not a data file. GT6Replay does not fetch or install decoders.

Decoded archives are loaded without Python pickle support. Array headers and size limits are checked before motion allocation. Input paths are not passed through a shell. The release audit rejects game binaries, savedata, private replay files, and machine-specific defaults.

Report security issues through the repository's private vulnerability-reporting facility when available. Avoid attaching private replays or credentials to public issues. The initial release has not had an independent security audit.
