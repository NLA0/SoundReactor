"""
Configuration management for SoundReactor.
Handles loading, saving, and validating config.json.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "audio": {
        "sample_rate": 22050,
        "chunk_duration": 2.0,       # seconds of audio per analysis window
        "overlap": 0.5,              # overlap fraction between windows
        "input_device": None,        # None = system default
        "channels": 1,
    },
    "fingerprinting": {
        "match_threshold": 0.25,     # 0–1, lower = looser matching
        "min_match_seconds": 5.0,    # must match for this long before triggering
        "cooldown_seconds": 86400.0,    # min seconds between repeated triggers
        "algorithm": "landmark",  # chromaprint | spectrogram
    },
    "sounds_db_path": "sounds_db",
    "rules": [],                     # list of SoundRule dicts
    "ui": {
        "theme": "dark",
        "log_lines": 200,
    },
}


class Config:
    def __init__(self, path: str = "config.json"):
        self.path = Path(path)
        self._data: Dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------ #
    #  I/O                                                                 #
    # ------------------------------------------------------------------ #

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data = self._deep_merge(DEFAULT_CONFIG, saved)
                log.info("Config loaded from %s", self.path)
            except Exception as e:
                log.warning("Could not load config (%s), using defaults.", e)
                self._data = dict(DEFAULT_CONFIG)
        else:
            self._data = dict(DEFAULT_CONFIG)
            self.save()
            log.info("Created default config at %s", self.path)

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            log.error("Failed to save config: %s", e)

    # ------------------------------------------------------------------ #
    #  Access helpers                                                       #
    # ------------------------------------------------------------------ #

    def get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value):
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()

    # ------------------------------------------------------------------ #
    #  Rules                                                               #
    # ------------------------------------------------------------------ #

    @property
    def rules(self) -> List[Dict]:
        return self._data.get("rules", [])

    def add_rule(self, rule: Dict):
        self._data.setdefault("rules", []).append(rule)
        self.save()

    def update_rule(self, index: int, rule: Dict):
        self._data["rules"][index] = rule
        self.save()

    def delete_rule(self, index: int):
        self._data["rules"].pop(index)
        self.save()

    # ------------------------------------------------------------------ #
    #  Audio / fingerprinting shortcuts                                    #
    # ------------------------------------------------------------------ #

    @property
    def sample_rate(self) -> int:
        return self.get("audio", "sample_rate", default=22050)

    @property
    def chunk_duration(self) -> float:
        return self.get("audio", "chunk_duration", default=2.0)

    @property
    def overlap(self) -> float:
        return self.get("audio", "overlap", default=0.5)

    @property
    def match_threshold(self) -> float:
        return self.get("fingerprinting", "match_threshold", default=0.65)

    @property
    def min_match_seconds(self) -> float:
        return self.get("fingerprinting", "min_match_seconds", default=3.0)

    @property
    def cooldown_seconds(self) -> float:
        return self.get("fingerprinting", "cooldown_seconds", default=30.0)

    @property
    def sounds_db_path(self) -> Path:
        return Path(self.get("sounds_db_path", default="sounds_db"))

    # ------------------------------------------------------------------ #
    #  Utilities                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = Config._deep_merge(result[k], v)
            else:
                result[k] = v
        return result
