"""
Audio fingerprinting - improved Shazam-style landmark fingerprinting.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)


def _require_librosa():
    try:
        import librosa
        return librosa
    except ImportError:
        raise ImportError("librosa is required. Install with: pip install librosa")


# ---------------------------------------------------------------------------
# Tuning parameters
# ---------------------------------------------------------------------------

N_FFT               = 4096
HOP_LENGTH          = 512
N_MELS              = 128

PEAK_NEIGHBORHOOD   = 20
MIN_DB_ABOVE_FLOOR  = 15
MAX_PEAKS_PER_SEC   = 15

FAN_OUT             = 15
TIME_DELTA_MIN      = 2
TIME_DELTA_MAX      = 100

N_FREQ_BANDS        = 32

MIN_ALIGNED         = 8
MIN_COHERENCE       = 0.20
OFFSET_BIN          = 2


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AudioFingerprint:
    sound_id: str
    file_path: str
    duration: float
    sample_rate: int
    landmark_table: Dict[int, List[int]]
    n_landmarks: int = 0
    sha256: str = ""

    def __post_init__(self):
        if not self.sha256 and self.landmark_table:
            h = hashlib.sha256(str(sorted(self.landmark_table.keys())).encode())
            self.sha256 = h.hexdigest()[:16]


@dataclass
class MatchResult:
    sound_id: str
    similarity: float
    matched_at_second: float
    algorithm: str
    aligned_landmarks: int = 0
    coherence: float = 0.0


# ---------------------------------------------------------------------------
# Spectrogram
# ---------------------------------------------------------------------------

def _spectrogram_db(y: np.ndarray, sr: int) -> np.ndarray:
    librosa = _require_librosa()
    S = librosa.feature.melspectrogram(
        y=y, sr=sr, n_fft=N_FFT, hop_length=HOP_LENGTH, n_mels=N_MELS
    )
    return librosa.power_to_db(S, ref=np.max)


# ---------------------------------------------------------------------------
# Peak picking
# ---------------------------------------------------------------------------

def _find_peaks(S_db: np.ndarray, sr: int = 22050) -> List[Tuple[int, int, float]]:
    """
    Return list of (time_frame, freq_bin, amplitude_db) for local maxima.
    """
    from scipy.ndimage import maximum_filter

    local_max = maximum_filter(S_db, size=PEAK_NEIGHBORHOOD)
    is_peak   = (S_db == local_max)

    noise_floor = np.median(S_db)
    is_peak    &= (S_db > noise_floor + MIN_DB_ABOVE_FLOOR)

    freq_bins, time_frames = np.where(is_peak)
    amplitudes = S_db[freq_bins, time_frames]

    peaks = sorted(
        zip(time_frames.tolist(), freq_bins.tolist(), amplitudes.tolist()),
        key=lambda p: p[0]
    )

    fps      = sr / HOP_LENGTH
    win_size = max(1, int(fps))
    filtered = []
    i = 0
    while i < len(peaks):
        window_end = peaks[i][0] + win_size
        chunk = [p for p in peaks[i:] if p[0] < window_end]
        chunk.sort(key=lambda p: -p[2])
        filtered.extend(chunk[:MAX_PEAKS_PER_SEC])
        i += len(chunk) if chunk else 1

    filtered.sort(key=lambda p: p[0])
    return filtered


# ---------------------------------------------------------------------------
# Landmark construction
# ---------------------------------------------------------------------------

def _quantise_freq(freq_bin: int) -> int:
    return int(freq_bin * N_FREQ_BANDS / N_MELS)


def _make_hash(f1_band: int, f2_band: int, dt: int) -> int:
    f1b = f1_band & 0x3F
    f2b = f2_band & 0x3F
    dtb = (dt - TIME_DELTA_MIN) & 0x7F
    return (f1b << 13) | (f2b << 7) | dtb


def _build_landmarks(peaks: List[Tuple[int, int, float]]) -> List[Tuple[int, int, int, int]]:
    landmarks = []
    n = len(peaks)
    for i, (t1, f1, _) in enumerate(peaks):
        f1b   = _quantise_freq(f1)
        count = 0
        for j in range(i + 1, n):
            t2, f2, _ = peaks[j]
            dt = t2 - t1
            if dt < TIME_DELTA_MIN:
                continue
            if dt > TIME_DELTA_MAX:
                break
            f2b = _quantise_freq(f2)
            landmarks.append((t1, f1b, f2b, dt))
            count += 1
            if count >= FAN_OUT:
                break
    return landmarks


def _build_landmark_table(y: np.ndarray, sr: int) -> Tuple[Dict[int, List[int]], int]:
    S_db      = _spectrogram_db(y, sr)
    peaks     = _find_peaks(S_db, sr)
    landmarks = _build_landmarks(peaks)

    table: Dict[int, List[int]] = {}
    for (t1, f1b, f2b, dt) in landmarks:
        h = _make_hash(f1b, f2b, dt)
        table.setdefault(h, []).append(t1)

    log.debug("Fingerprint: %d peaks, %d landmarks, %d unique hashes",
              len(peaks), len(landmarks), len(table))
    return table, len(landmarks)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match_against_table(
    live_y: np.ndarray,
    sr: int,
    ref_table: Dict[int, List[int]],
) -> Tuple[float, float, int, float]:
    """
    Returns (score, offset_seconds, aligned_count, coherence).
    """
    S_db      = _spectrogram_db(live_y, sr)
    peaks     = _find_peaks(S_db, sr)
    landmarks = _build_landmarks(peaks)

    if not landmarks:
        return 0.0, 0.0, 0, 0.0

    offset_hist: Dict[int, int] = {}
    total_matching = 0

    for (t1, f1b, f2b, dt) in landmarks:
        h = _make_hash(f1b, f2b, dt)
        if h not in ref_table:
            continue
        for ref_t1 in ref_table[h]:
            offset_bin = round((ref_t1 - t1) / OFFSET_BIN)
            offset_hist[offset_bin] = offset_hist.get(offset_bin, 0) + 1
            total_matching += 1

    if not offset_hist or total_matching == 0:
        return 0.0, 0.0, 0, 0.0

    best_bin, best_count = max(offset_hist.items(), key=lambda x: x[1])
    coherence  = best_count / total_matching
    offset_sec = max(0.0, best_bin * OFFSET_BIN * HOP_LENGTH / sr)
    score      = min(1.0, best_count / (MIN_ALIGNED * 2))

    log.debug("  aligned=%d  total_matching=%d  coherence=%.2f  offset=%.1fs",
              best_count, total_matching, coherence, offset_sec)

    return score, offset_sec, best_count, coherence


# ---------------------------------------------------------------------------
# Fingerprint builder
# ---------------------------------------------------------------------------

class FingerprintBuilder:
    SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate

    def build(self, file_path) -> AudioFingerprint:
        librosa = _require_librosa()
        path    = Path(file_path)
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported format: {path.suffix}")

        log.info("Building fingerprint for: %s", path.name)
        y, sr = librosa.load(str(path), sr=self.sample_rate, mono=True)
        table, n = _build_landmark_table(y, sr)

        return AudioFingerprint(
            sound_id=path.stem,
            file_path=str(path),
            duration=len(y) / sr,
            sample_rate=sr,
            landmark_table=table,
            n_landmarks=n,
        )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

CACHE_FILE = ".fingerprint_cache_v3.pkl"


class FingerprintDatabase:
    def __init__(self, db_path, sample_rate: int = 22050):
        self.db_path     = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        self.builder     = FingerprintBuilder(sample_rate)
        self._fingerprints: Dict[str, AudioFingerprint] = {}
        self._cache_path = self.db_path / CACHE_FILE
        self._load_cache()

    def load_all(self) -> int:
        count = 0
        for f in self.db_path.iterdir():
            if f.suffix.lower() in FingerprintBuilder.SUPPORTED_EXTENSIONS:
                try:
                    self._ensure_fingerprint(f)
                    count += 1
                except Exception as e:
                    log.warning("Skipping %s: %s", f.name, e)
        self._save_cache()
        log.info("Loaded %d fingerprints from %s", count, self.db_path)
        return count

    def add_file(self, file_path) -> AudioFingerprint:
        fp = self.builder.build(Path(file_path))
        self._fingerprints[fp.sound_id] = fp
        self._save_cache()
        return fp

    def remove(self, sound_id: str):
        self._fingerprints.pop(sound_id, None)
        self._save_cache()

    def get(self, sound_id: str) -> Optional[AudioFingerprint]:
        return self._fingerprints.get(sound_id)

    def list_sounds(self) -> List[str]:
        return list(self._fingerprints.keys())

    def __len__(self):
        return len(self._fingerprints)

    def _ensure_fingerprint(self, path: Path):
        sid      = path.stem
        existing = self._fingerprints.get(sid)
        if existing:
            try:
                if (os.path.getmtime(existing.file_path) == os.path.getmtime(path)
                        and hasattr(existing, "landmark_table")
                        and existing.landmark_table):
                    return
            except Exception:
                pass
        self._fingerprints[sid] = self.builder.build(path)

    def _load_cache(self):
        if self._cache_path.exists():
            try:
                with open(self._cache_path, "rb") as f:
                    self._fingerprints = pickle.load(f)
                log.debug("Cache loaded (%d entries)", len(self._fingerprints))
            except Exception as e:
                log.warning("Cache load failed (%s), rebuilding.", e)
                self._fingerprints = {}

    def _save_cache(self):
        try:
            with open(self._cache_path, "wb") as f:
                pickle.dump(self._fingerprints, f)
        except Exception as e:
            log.warning("Could not save cache: %s", e)


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

class FingerprintMatcher:
    def __init__(self, algorithm: str = "landmark"):
        self.algorithm = algorithm

    def compute_live_features(self, audio: np.ndarray, sample_rate: int):
        return audio, np.array([]), np.array([])

    def best_match(
        self,
        live_audio: np.ndarray,
        live_chroma,
        live_mel,
        database: FingerprintDatabase,
        threshold: float = 0.20,
        sample_rate: int = 22050,
    ) -> Optional[MatchResult]:
        best = None
        for sid in database.list_sounds():
            fp = database.get(sid)
            if fp is None:
                continue

            score, offset_sec, aligned, coherence = _match_against_table(
                live_audio, sample_rate, fp.landmark_table
            )

            log.debug("[%s] score=%.2f aligned=%d coherence=%.2f",
                      sid, score, aligned, coherence)

            if aligned >= MIN_ALIGNED and coherence >= MIN_COHERENCE:
                result = MatchResult(
                    sound_id=sid,
                    similarity=score,
                    matched_at_second=offset_sec,
                    algorithm="landmark",
                    aligned_landmarks=aligned,
                    coherence=coherence,
                )
                if best is None or aligned > best.aligned_landmarks:
                    best = result

        return best
