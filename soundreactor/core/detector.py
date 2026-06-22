"""
SoundDetector - the main detection engine.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional

import numpy as np

from core.config import Config
from core.fingerprint import FingerprintDatabase, FingerprintMatcher, MatchResult
from core.actions import execute_action

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

class RuleEngine:
    def __init__(self, config: Config):
        self.config = config
        self._consecutive: Dict[str, float] = defaultdict(float)
        self._last_trigger_time: Dict[str, float] = {}
        # Tracks which "trigger_once" rules have already fired this session
        self._fired_once: set = set()

    def process(self, result: Optional[MatchResult], chunk_duration: float):
        fired = []
        now   = time.monotonic()

        all_rule_sound_ids = {
            r.get("sound_id") for r in self.config.rules if r.get("enabled", True)
        }

        matched_id = result.sound_id if result else None

        for sid in all_rule_sound_ids:
            if sid != matched_id:
                if self._consecutive[sid] > 0:
                    log.debug("Consecutive reset for '%s'", sid)
                self._consecutive[sid] = 0.0

        if result is None:
            return fired

        self._consecutive[matched_id] += chunk_duration
        log.debug("Consecutive match '%s': %.1fs (similarity=%.2f)",
                  matched_id, self._consecutive[matched_id], result.similarity)

        for rule in self.config.rules:
            if not rule.get("enabled", True):
                continue
            if rule.get("sound_id") != matched_id:
                continue

            rule_key    = rule.get("name", matched_id)
            trigger_once = rule.get("trigger_once", False)

            # Skip if already fired this session
            if trigger_once and rule_key in self._fired_once:
                log.debug("Rule '%s' already fired this session, skipping.", rule_key)
                continue

            min_secs = rule.get("min_match_seconds", self.config.min_match_seconds)
            cooldown = rule.get("cooldown_seconds",  self.config.cooldown_seconds)

            last_trigger = self._last_trigger_time.get(rule_key, 0)
            consecutive  = self._consecutive[matched_id]

            # For trigger_once rules, ignore cooldown (it only fires once anyway)
            cooldown_ok = trigger_once or (now - last_trigger) >= cooldown

            if consecutive >= min_secs and cooldown_ok:
                log.info("Rule '%s' triggered! (consecutive=%.1fs, similarity=%.2f%s)",
                         rule_key, consecutive, result.similarity,
                         ", ONCE" if trigger_once else "")
                for action in rule.get("actions", []):
                    execute_action(action, matched_id, result.similarity)
                self._last_trigger_time[rule_key] = now
                self._consecutive[matched_id] = 0.0
                if trigger_once:
                    self._fired_once.add(rule_key)
                fired.append(rule_key)

        return fired

    def reset_once_rules(self):
        """Call this to allow trigger_once rules to fire again (e.g. on restart)."""
        self._fired_once.clear()


# ---------------------------------------------------------------------------
# Audio capture - captures at device native rate, resamples properly
# ---------------------------------------------------------------------------

class AudioCapture:
    def __init__(
        self,
        target_sample_rate: int,
        chunk_duration: float,
        overlap: float,
        device=None,
        callback: Optional[Callable] = None,
    ):
        self.target_sr      = target_sample_rate
        self.chunk_duration = chunk_duration
        self.overlap        = overlap
        self.device         = device
        self.callback       = callback
        self._stream        = None
        self._running       = False

        import sounddevice as sd
        if device is not None:
            try:
                dev_info = sd.query_devices(device)
                self.device_sr = int(dev_info['default_samplerate'])
            except Exception:
                self.device_sr = target_sample_rate
        else:
            try:
                dev_info = sd.query_devices(kind='input')
                self.device_sr = int(dev_info['default_samplerate'])
            except Exception:
                self.device_sr = target_sample_rate

        log.info("Device native SR: %d, target SR: %d", self.device_sr, self.target_sr)

        self.chunk_size = int(chunk_duration * self.target_sr)
        self.hop_size   = int(self.chunk_size * (1 - overlap))
        self.device_hop = int(self.hop_size * self.device_sr / self.target_sr)
        self._buffer    = np.zeros(self.chunk_size, dtype=np.float32)

    def start(self):
        import sounddevice as sd
        self._running = True
        self._stream  = sd.InputStream(
            samplerate=self.device_sr,
            channels=1,
            device=self.device,
            dtype="float32",
            blocksize=self.device_hop,
            callback=self._sd_callback,
        )
        self._stream.start()
        log.info("Audio capture started (device SR=%d, target SR=%d, chunk=%.1fs)",
                 self.device_sr, self.target_sr, self.chunk_duration)

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _sd_callback(self, indata, frames, time_info, status):
        if status:
            log.debug("sounddevice status: %s", status)
        mono = indata[:, 0] if indata.ndim > 1 else indata.ravel()
        if self.device_sr != self.target_sr:
            try:
                import librosa
                mono = librosa.resample(mono, orig_sr=self.device_sr,
                                        target_sr=self.target_sr)
            except Exception:
                target_len = int(len(mono) * self.target_sr / self.device_sr)
                mono = np.interp(
                    np.linspace(0, len(mono) - 1, target_len),
                    np.arange(len(mono)), mono
                ).astype(np.float32)
        n = len(mono)
        self._buffer = np.roll(self._buffer, -n)
        self._buffer[-n:] = mono
        if self.callback:
            self.callback(self._buffer.copy())


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

class SoundDetector:
    def __init__(self, config: Config):
        self.config      = config
        self.db          = FingerprintDatabase(config.sounds_db_path,
                                               sample_rate=config.sample_rate)
        self.matcher     = FingerprintMatcher(
            algorithm=config.get("fingerprinting", "algorithm", default="landmark")
        )
        self.rule_engine = RuleEngine(config)
        self._capture: Optional[AudioCapture] = None
        self._running    = False

        self.on_match:      Optional[Callable[[MatchResult], None]] = None
        self.on_rule_fired: Optional[Callable[[str, MatchResult], None]] = None
        self.on_status:     Optional[Callable[[str], None]] = None

        self.total_chunks_processed = 0
        self.total_matches          = 0
        self.total_rules_fired      = 0

    def start(self):
        if self._running:
            return
        log.info("Loading fingerprint database...")
        count = self.db.load_all()
        self._emit_status(f"Loaded {count} sound(s) in database.")

        device = self.config.get("audio", "input_device")
        self._capture = AudioCapture(
            target_sample_rate=self.config.sample_rate,
            chunk_duration=self.config.chunk_duration,
            overlap=self.config.overlap,
            device=device,
            callback=self._on_audio_chunk,
        )
        self._running = True
        self._capture.start()
        self._emit_status("Listening...")

    def stop(self):
        self._running = False
        if self._capture:
            self._capture.stop()
            self._capture = None
        self._emit_status("Stopped.")

    def reload_database(self):
        self.db.load_all()
        self._emit_status(f"Database reloaded: {len(self.db)} sound(s).")

    def _on_audio_chunk(self, audio: np.ndarray):
        if not self._running:
            return
        self.total_chunks_processed += 1
        try:
            live_audio, live_chroma, live_mel = self.matcher.compute_live_features(
                audio, self.config.sample_rate
            )
        except Exception as e:
            log.debug("Feature extraction error: %s", e)
            return
        if len(self.db) == 0:
            return
        result = self.matcher.best_match(
            live_audio, live_chroma, live_mel, self.db,
            self.config.match_threshold,
            sample_rate=self.config.sample_rate,
        )
        if result:
            self.total_matches += 1
            if self.on_match:
                self.on_match(result)
        fired = self.rule_engine.process(result, self.config.chunk_duration)
        for rule_name in fired:
            self.total_rules_fired += 1
            if self.on_rule_fired and result:
                self.on_rule_fired(rule_name, result)

    def _emit_status(self, msg: str):
        log.info(msg)
        if self.on_status:
            self.on_status(msg)

    def list_audio_devices(self):
        try:
            import sounddevice as sd
            return sd.query_devices()
        except Exception as e:
            log.error("Could not list audio devices: %s", e)
            return []
