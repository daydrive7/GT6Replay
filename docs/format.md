# Decoded replay format

`.gt6r` is a NumPy NPZ container with three arrays:

- `motion`: float32, shape `(frames, drivers, 13)`.
- `metadata`: scalar JSON string.
- `replay`: scalar JSON string containing race metadata and entrants.

Motion columns are `x,y,z,vx,vy,vz,qx,qy,qz,qw,rpm,gear,lap`. Positions are metres; velocity is metres per second. The frame clock is 60 Hz. A completely absent driver row uses NaNs and is not drawn. Present rows must have finite values. Speed is the magnitude of velocity converted to km/h.

Metadata format is `gt6-native-motion-v1`, with `native_sha256`, `fps`, `frame_count`, `columns`, and unique `slots` in the range 0–31. The replay metadata's fingerprint and total frame count must match. Gear 0 denotes reverse; 15 denotes neutral. The lap field is the recorded counter, not an inferred number of completed laps.

The viewer rejects motion arrays exceeding 512 MiB, metadata arrays exceeding 1 MiB, and race metadata exceeding 8 MiB. Array dimensions and byte lengths are verified before allocation; pickled objects are not accepted.

An external decoder accepts `--input PATH --output PATH` and must create this format. The viewer validates the output before moving it into its cache. This interface does not grant rights to distribute a decoder or the input game data.
