# Fingerprint diagnostic - tests matching against your MP3 files directly.
# Run from D:\Claude\soundreactor\ with: python diagnose_fingerprint.py
import sys
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

sys.path.insert(0, str(Path(__file__).parent))

from core.fingerprint import (
    _spectrogram_db, _find_peaks, _build_landmarks,
    _build_landmark_table, _match_against_table,
    MIN_ALIGNED, MIN_COHERENCE, HOP_LENGTH,
    FAN_OUT, MAX_PEAKS_PER_SEC, TIME_DELTA_MAX,
    PEAK_NEIGHBORHOOD, MIN_DB_ABOVE_FLOOR,
)

SAMPLE_RATE   = 22050
CHUNK_SECONDS = 6
OVERLAP       = 0.5


def diagnose_file(mp3_path: str):
    import librosa
    path = Path(mp3_path)
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return

    print(f"\n{'='*65}")
    print(f"File: {path.name}")
    y, sr = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    print(f"Duration: {len(y)/sr:.1f}s   Sample rate: {sr}Hz")

    print(f"\nBuilding reference fingerprint...")
    S_db   = _spectrogram_db(y, sr)
    peaks  = _find_peaks(S_db, sr)
    lms    = _build_landmarks(peaks)
    table, _ = _build_landmark_table(y, sr)

    print(f"  Peaks found    : {len(peaks)}")
    print(f"  Landmarks built: {len(lms)}")
    print(f"  Unique hashes  : {len(table)}")

    if len(peaks) == 0:
        print("\n  !! NO PEAKS FOUND - audio may be silent or too quiet")
        print("  Fix: lower MIN_DB_ABOVE_FLOOR in fingerprint.py")
        input("\nPress Enter to close...")
        return

    if len(lms) == 0:
        print("\n  !! NO LANDMARKS - peaks exist but no pairs formed")
        print(f"  Fix: increase TIME_DELTA_MAX (currently {TIME_DELTA_MAX})")
        input("\nPress Enter to close...")
        return

    chunk_size = int(CHUNK_SECONDS * sr)
    hop_size   = int(chunk_size * (1 - OVERLAP))

    print(f"\nMatching {CHUNK_SECONDS}s chunks against reference")
    print(f"(need aligned>={MIN_ALIGNED}, coherence>={MIN_COHERENCE}):\n")
    print(f"  {'Time':>6}  {'Peaks':>6}  {'Lmarks':>7}  {'TotHits':>8}  {'Aligned':>8}  {'Coherence':>10}  {'Result':>7}")
    print(f"  {'-'*62}")

    passed = 0
    total  = 0
    for start in range(0, len(y) - chunk_size, hop_size):
        chunk   = y[start: start + chunk_size]
        t_sec   = start / sr
        c_S     = _spectrogram_db(chunk, sr)
        c_peaks = _find_peaks(c_S, sr)
        c_lms   = _build_landmarks(c_peaks)
        score, offset, aligned, coherence = _match_against_table(chunk, sr, table)
        tot = int(aligned / coherence) if coherence > 0 else 0
        ok  = "PASS" if (aligned >= MIN_ALIGNED and coherence >= MIN_COHERENCE) else "fail"
        if ok == "PASS":
            passed += 1
        total += 1
        print(f"  {t_sec:>5.1f}s  {len(c_peaks):>6}  {len(c_lms):>7}  "
              f"{tot:>8}  {aligned:>8}  {coherence:>10.3f}  {ok:>7}")

    print(f"\n  Passed: {passed}/{total} chunks ({100*passed//total}%)")
    print(f"\n{'='*65}")
    print("DIAGNOSIS:")

    if passed == total:
        print("  All chunks matched perfectly.")
    elif passed >= total * 0.75:
        print(f"  Good match rate ({passed}/{total}). System should work reliably.")
        print("  The failed chunks are likely silence or transitions - that is normal.")
    elif passed > 0:
        print(f"  Partial match ({passed}/{total}). May miss some detections.")
        print("  Consider lowering MIN_ALIGNED or MIN_COHERENCE slightly.")
    else:
        print("  No chunks matched. Checking which threshold is blocking...\n")
        chunk = y[0: chunk_size]
        score, offset, aligned, coherence = _match_against_table(chunk, sr, table)
        tot = int(aligned / coherence) if coherence > 0 else 0
        print(f"  First chunk: aligned={aligned} (need>={MIN_ALIGNED}), "
              f"coherence={coherence:.3f} (need>={MIN_COHERENCE}), hits={tot}")
        print(f"\n  Suggested fixes (edit core/fingerprint.py):")
        if aligned < MIN_ALIGNED:
            print(f"    -> Lower MIN_ALIGNED   from {MIN_ALIGNED} to {max(3, aligned - 1)}")
        if coherence < MIN_COHERENCE:
            print(f"    -> Lower MIN_COHERENCE from {MIN_COHERENCE} to {max(0.05, round(coherence * 0.8, 2))}")
        if tot < 10:
            print(f"    -> Raise  FAN_OUT      from {FAN_OUT} to {FAN_OUT + 10}")
        if len(peaks) < 20:
            print(f"    -> Lower  MIN_DB_ABOVE_FLOOR from {MIN_DB_ABOVE_FLOOR} to {MIN_DB_ABOVE_FLOOR - 5}")
        print(f"    -> Raise chunk_duration in config.json to 6 or 8 seconds")


def main():
    db_path = Path("sounds_db")
    files   = sorted([
        f for f in db_path.glob("*")
        if f.suffix.lower() in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
    ])
    if not files:
        print(f"No audio files found in {db_path}/")
        input("Press Enter to close...")
        sys.exit(1)

    print("SoundReactor Fingerprint Diagnostic")
    print("====================================")
    for i, f in enumerate(files):
        print(f"  [{i}] {f.name}")

    idx = 0
    if len(files) > 1:
        try:
            idx = int(input("\nWhich file? Enter number [0]: ") or "0")
        except ValueError:
            idx = 0

    diagnose_file(str(files[idx]))
    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
