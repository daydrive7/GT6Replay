"""Compare complete decoded replay archives by driver slot and recorded frame."""

from pathlib import Path
import argparse
import json
import sys
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from native_motion import load_native_replay


def orientation_error(candidate, reference):
    candidate = candidate.astype(np.float64)
    reference = reference.astype(np.float64)
    norms = np.linalg.norm(candidate, axis=1) * np.linalg.norm(reference, axis=1)
    if np.any(norms <= 0) or not np.isfinite(norms).all():
        raise ValueError("Present driver frames must have nonzero, finite quaternions.")
    dots = np.abs(np.sum(candidate * reference, axis=1))
    cosine = np.divide(dots, norms, out=np.zeros_like(dots), where=norms > 0)
    return 2 * np.arccos(np.clip(cosine, 0, 1))


def compare(
    candidate,
    reference,
    position_tolerance=0.001,
    velocity_tolerance=0.001,
    orientation_tolerance=0.0001,
    rpm_tolerance=0.1,
):
    if any(
        not np.isfinite(v) or v < 0
        for v in (position_tolerance, velocity_tolerance, orientation_tolerance, rpm_tolerance)
    ):
        raise ValueError("Comparison tolerances must be finite and non-negative.")
    for field in ("native_sha256", "frame_count", "fps"):
        if candidate.metadata[field] != reference.metadata[field]:
            raise ValueError(f"Archives disagree on {field}.")
    candidate_slots, reference_slots = candidate.metadata["slots"], reference.metadata["slots"]
    if set(candidate_slots) != set(reference_slots):
        raise ValueError("Archives contain different driver slots.")
    report = {
        "passed": True,
        "frame_count": reference.metadata["frame_count"],
        "driver_count": len(reference_slots),
        "drivers": [],
    }
    tolerances = {
        "position_metres": position_tolerance,
        "velocity_metres_per_second": velocity_tolerance,
        "orientation_radians": orientation_tolerance,
        "rpm": rpm_tolerance,
        "gear": 0,
        "lap": 0,
    }
    report["tolerances"] = tolerances
    for slot in sorted(reference_slots):
        actual = candidate.motion[:, candidate_slots.index(slot), :]
        expected = reference.motion[:, reference_slots.index(slot), :]
        actual_present = np.isfinite(actual).all(axis=1)
        expected_present = np.isfinite(expected).all(axis=1)
        visibility_errors = np.flatnonzero(actual_present != expected_present)
        present = actual_present & expected_present
        a, b = actual[present].astype(np.float64), expected[present].astype(np.float64)
        differences = {
            "position_metres": np.linalg.norm(a[:, :3] - b[:, :3], axis=1),
            "velocity_metres_per_second": np.linalg.norm(a[:, 3:6] - b[:, 3:6], axis=1),
            "orientation_radians": orientation_error(a[:, 6:10], b[:, 6:10]),
            "rpm": np.abs(a[:, 10] - b[:, 10]),
            "gear": np.abs(a[:, 11] - b[:, 11]),
            "lap": np.abs(a[:, 12] - b[:, 12]),
        }
        driver = {
            "slot": slot,
            "present_frames_compared": int(present.sum()),
            "visibility_mismatches": int(len(visibility_errors)),
            "first_visibility_mismatch_frame": (
                int(visibility_errors[0]) if len(visibility_errors) else None
            ),
            "fields": {},
        }
        frame_ids = np.flatnonzero(present)
        for name, errors in differences.items():
            # Identical float32 quaternions must not acquire acos rounding error.
            if name == "orientation_radians":
                identical = np.all(a[:, 6:10] == b[:, 6:10], axis=1) | np.all(
                    a[:, 6:10] == -b[:, 6:10], axis=1
                )
                errors[identical] = 0
            wrong = np.flatnonzero(errors > tolerances[name])
            driver["fields"][name] = {
                "max_error": float(errors.max()) if len(errors) else 0.0,
                "rms_error": float(np.sqrt(np.mean(errors**2))) if len(errors) else 0.0,
                "mismatched_frames": int(len(wrong)),
                "first_mismatch_frame": int(frame_ids[wrong[0]]) if len(wrong) else None,
            }
            if len(wrong):
                report["passed"] = False
        if len(visibility_errors):
            report["passed"] = False
        report["drivers"].append(driver)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--position-tolerance", type=float, default=0.001)
    parser.add_argument("--velocity-tolerance", type=float, default=0.001)
    parser.add_argument("--orientation-tolerance", type=float, default=0.0001)
    parser.add_argument("--rpm-tolerance", type=float, default=0.1)
    args = parser.parse_args()
    try:
        report = compare(
            load_native_replay(args.candidate),
            load_native_replay(args.reference),
            args.position_tolerance,
            args.velocity_tolerance,
            args.orientation_tolerance,
            args.rpm_tolerance,
        )
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(2, f"Comparison could not run: {error}\n")
    document = json.dumps(report, indent=2, allow_nan=False)
    if args.report:
        args.report.write_text(document + "\n", encoding="utf-8")
    print(document)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
