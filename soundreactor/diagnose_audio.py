# Audio input diagnostic - checks what your microphone/stereo mix is actually capturing.
# Run from D:\Claude\soundreactor\ with: python diagnose_audio.py
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import sounddevice as sd
import librosa


def list_devices():
    print("\nAVAILABLE AUDIO INPUT DEVICES:")
    print("-" * 60)
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            marker = " <-- likely stereo mix" if any(
                k in d['name'].lower() for k in ['stereo', 'mix', 'loopback', 'wave', 'what u hear']
            ) else ""
            print(f"  [{i:2d}] {d['name']}  (SR={int(d['default_samplerate'])}){marker}")
    print()


def record_and_compare(mp3_path: str, device_index=None, duration=6.0, sr=22050):
    print(f"\nRecording {duration}s from device {device_index or 'default'}...")
    audio = sd.rec(
        int(duration * sr), samplerate=sr, channels=1,
        dtype='float32', device=device_index
    )
    sd.wait()
    audio = audio.ravel()

    rms = np.sqrt(np.mean(audio ** 2))
    peak = np.max(np.abs(audio))
    print(f"  RMS level : {rms:.4f}  (should be > 0.01 for audible audio)")
    print(f"  Peak level: {peak:.4f}  (should be > 0.05 for good signal)")

    if rms < 0.001:
        print("  !! SIGNAL TOO QUIET - microphone/stereo mix may not be capturing audio")
        return

    # Load the MP3 and compare spectral shape
    print(f"\nLoading reference MP3: {mp3_path}")
    ref_y, _ = librosa.load(mp3_path, sr=sr, mono=True, duration=duration)

    # Compute mel spectrograms for both
    live_mel = librosa.feature.melspectrogram(y=audio,  sr=sr, n_mels=64)
    ref_mel  = librosa.feature.melspectrogram(y=ref_y,  sr=sr, n_mels=64)

    live_db  = librosa.power_to_db(live_mel, ref=np.max).mean(axis=1)
    ref_db   = librosa.power_to_db(ref_mel,  ref=np.max).mean(axis=1)

    # Cosine similarity of average mel profiles
    dot   = np.dot(live_db, ref_db)
    denom = np.linalg.norm(live_db) * np.linalg.norm(ref_db)
    sim   = dot / denom if denom > 0 else 0

    print(f"  Spectral similarity to MP3: {sim:.3f}")
    if sim > 0.95:
        print("  GOOD - spectral profiles match (same audio source)")
    elif sim > 0.85:
        print("  OK - similar but not identical (different recording conditions)")
    else:
        print("  !! LOW - spectral profiles are very different")
        print("     The live audio sounds different from your MP3 recordings.")
        print("     Possible causes:")
        print("     - Wrong input device selected (not capturing TV audio)")
        print("     - MP3 recorded from different source (phone mic vs loopback)")
        print("     - Sample rate mismatch")

    # Save the live recording for inspection
    out_path = "diagnose_live_recording.wav"
    import soundfile as sf
    sf.write(out_path, audio, sr)
    print(f"\n  Saved live recording to: {out_path}")
    print("  Listen to this file to confirm it contains the TV audio.")


def main():
    list_devices()

    db_path = Path("sounds_db")
    files   = sorted([
        f for f in db_path.glob("*")
        if f.suffix.lower() in {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
    ])

    if not files:
        print("No audio files in sounds_db/")
        input("Press Enter to close...")
        return

    print(f"Reference files in sounds_db:")
    for i, f in enumerate(files):
        print(f"  [{i}] {f.name}")

    try:
        idx = int(input("\nWhich reference file to compare against? [0]: ") or "0")
    except ValueError:
        idx = 0

    mp3_path = str(files[idx])

    device_str = input("\nEnter device number to test (or press Enter for default): ").strip()
    device_index = int(device_str) if device_str else None

    print(f"\nMake sure your TV/show audio is playing NOW.")
    input("Press Enter to start 6-second recording...")

    try:
        import soundfile
        has_soundfile = True
    except ImportError:
        has_soundfile = False
        print("(pip install soundfile to save the recording for inspection)")

    record_and_compare(mp3_path, device_index)

    if not has_soundfile:
        print("\nInstall soundfile to save live recording: pip install soundfile")

    input("\nPress Enter to close...")


if __name__ == "__main__":
    main()
