# Live audio diagnostic - shows fingerprint scores in real time WITHOUT triggering actions.
# Run from D:\Claude\soundreactor\ with: python diagnose_live.py
# Play your TV/show audio and watch the scores. Press Ctrl+C to stop.
import sys
import time
import logging
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

sys.path.insert(0, str(Path(__file__).parent))

from core.config import Config
from core.fingerprint import (
    FingerprintDatabase, FingerprintMatcher,
    _match_against_table, MIN_ALIGNED, MIN_COHERENCE
)

SAMPLE_RATE    = 22050
CHUNK_DURATION = 6.0
OVERLAP        = 0.5


def main():
    config = Config("config.json")
    db     = FingerprintDatabase(config.sounds_db_path, SAMPLE_RATE)
    count  = db.load_all()
    print(f"\nLoaded {count} sound(s): {db.list_sounds()}")
    print(f"Thresholds: MIN_ALIGNED={MIN_ALIGNED}  MIN_COHERENCE={MIN_COHERENCE}")
    print(f"Chunk: {CHUNK_DURATION}s\n")
    print(f"{'Sound':<20}  {'Aligned':>8}  {'Coherence':>10}  {'TotHits':>8}  {'Match?':>7}")
    print("-" * 60)
    print("Listening... (play your TV audio now, Ctrl+C to stop)\n")

    chunk_size = int(CHUNK_DURATION * SAMPLE_RATE)
    hop_size   = int(chunk_size * (1 - OVERLAP))
    buffer     = np.zeros(chunk_size, dtype=np.float32)

    import sounddevice as sd

    def audio_callback(indata, frames, time_info, status):
        nonlocal buffer
        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()
        buffer = np.roll(buffer, -len(mono))
        buffer[-len(mono):] = mono

    device = config.get("audio", "input_device")
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        device=device,
        dtype="float32",
        blocksize=hop_size,
        callback=audio_callback,
    )

    last_print = time.time()
    stream.start()
    try:
        while True:
            time.sleep(0.1)
            now = time.time()
            if now - last_print < CHUNK_DURATION * (1 - OVERLAP):
                continue
            last_print = now

            chunk = buffer.copy()
            any_match = False
            for sid in db.list_sounds():
                fp = db.get(sid)
                if fp is None:
                    continue
                score, offset, aligned, coherence = _match_against_table(
                    chunk, SAMPLE_RATE, fp.landmark_table
                )
                tot   = int(aligned / coherence) if coherence > 0 else 0
                would_match = aligned >= MIN_ALIGNED and coherence >= MIN_COHERENCE
                marker = "  <-- MATCH" if would_match else ""
                print(f"{sid:<20}  {aligned:>8}  {coherence:>10.3f}  {tot:>8}  "
                      f"{'YES' if would_match else 'no':>7}{marker}")
                any_match = any_match or would_match
            if any_match:
                print()  # blank line to separate match events

    except KeyboardInterrupt:
        stream.stop()
        print("\nStopped.")


if __name__ == "__main__":
    main()
