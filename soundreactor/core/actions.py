"""
Action execution subsystem.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any, Dict

log = logging.getLogger(__name__)
SYSTEM = platform.system()


# ---------------------------------------------------------------------------
# Volume control
# ---------------------------------------------------------------------------

class VolumeController:

    def get(self) -> int:
        try:
            if SYSTEM == "Windows":
                return self._win_get()
            elif SYSTEM == "Linux":
                return self._linux_get()
        except Exception as e:
            log.error("get volume failed: %s", e)
        return 50

    def set(self, level: int):
        level = max(0, min(100, int(level)))
        log.info("Setting volume to %d%%", level)
        try:
            if SYSTEM == "Windows":
                self._win_set(level)
            elif SYSTEM == "Linux":
                self._linux_set(level)
        except Exception as e:
            log.error("set volume failed: %s", e)

    def mute(self, state: bool):
        log.info("%s system audio", "Muting" if state else "Unmuting")
        try:
            if SYSTEM == "Windows":
                self._win_mute(state)
            elif SYSTEM == "Linux":
                self._linux_mute(state)
        except Exception as e:
            log.error("mute failed: %s", e)

    # ------------------------------------------------------------------
    # Windows helpers - three fallback layers
    # ------------------------------------------------------------------

    @staticmethod
    def _pycaw_interface():
        """Return IAudioEndpointVolume via pycaw EndpointVolume property."""
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        return speakers.EndpointVolume

    @staticmethod
    def _win_get() -> int:
        # Layer 1: pycaw
        try:
            return int(VolumeController._pycaw_interface().GetMasterVolumeLevelScalar() * 100)
        except Exception as e:
            log.debug("pycaw get failed: %s", e)

        # Layer 2: PowerShell + AudioDeviceCmdlets module
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-AudioDevice -Playback).Volume"],
                capture_output=True, text=True, timeout=3,
            )
            v = r.stdout.strip()
            if v:
                return int(float(v))
        except Exception as e:
            log.debug("PowerShell AudioDevice get failed: %s", e)

        # Layer 3: WScript volume keypress read (not reliable, just return 50)
        return 50

    @staticmethod
    def _win_set(level: int):
        # Layer 1: pycaw
        try:
            VolumeController._pycaw_interface().SetMasterVolumeLevelScalar(level / 100.0, None)
            log.debug("Volume set via pycaw")
            return
        except Exception as e:
            log.debug("pycaw set failed: %s", e)

        # Layer 2: PowerShell + AudioDeviceCmdlets
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Set-AudioDevice -PlaybackVolume {level}"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                log.debug("Volume set via PowerShell AudioDevice")
                return
            log.debug("PowerShell AudioDevice set failed: %s", r.stderr.strip())
        except Exception as e:
            log.debug("PowerShell AudioDevice set failed: %s", e)

        # Layer 3: nircmd (https://www.nirsoft.net/utils/nircmd.html)
        try:
            nircmd_level = int(level / 100.0 * 65535)
            r = subprocess.run(
                ["nircmd", "setsysvolume", str(nircmd_level)],
                capture_output=True, timeout=3,
            )
            if r.returncode == 0:
                log.debug("Volume set via nircmd")
                return
        except FileNotFoundError:
            log.debug("nircmd not found")
        except Exception as e:
            log.debug("nircmd failed: %s", e)

        log.error(
            "Could not set volume. Install one of:\n"
            "  pip install pycaw comtypes\n"
            "  PowerShell: Install-Module AudioDeviceCmdlets\n"
            "  Or download nircmd.exe and put it in PATH"
        )

    @staticmethod
    def _win_mute(state: bool):
        # Layer 1: pycaw
        try:
            VolumeController._pycaw_interface().SetMute(int(state), None)
            return
        except Exception as e:
            log.debug("pycaw mute failed: %s", e)

        # Layer 2: PowerShell
        try:
            val = "$true" if state else "$false"
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Set-AudioDevice -PlaybackMute {val}"],
                capture_output=True, timeout=5,
            )
        except Exception as e:
            log.debug("PowerShell mute failed: %s", e)


    # ------------------------------------------------------------------
    # Per-app volume (Windows Volume Mixer)
    # ------------------------------------------------------------------

    @staticmethod
    def _set_app_volume(process_name: str, level: int):
        """
        Set the Volume Mixer level for a specific process (e.g. chrome.exe).
        level is 0-100.
        """
        try:
            from pycaw.pycaw import AudioUtilities
            sessions = AudioUtilities.GetAllSessions()
            matched = 0
            for session in sessions:
                proc = session.Process
                if proc is None:
                    continue
                if process_name.lower() in proc.name().lower():
                    vol = session.SimpleAudioVolume
                    vol.SetMasterVolume(level / 100.0, None)
                    matched += 1
                    log.debug("Set %s (pid %d) volume to %d%%",
                              proc.name(), proc.pid, level)
            if matched == 0:
                log.warning("No running process matched '%s' in Volume Mixer", process_name)
            else:
                log.info("Set %d session(s) for '%s' to %d%%",
                         matched, process_name, level)
        except Exception as e:
            log.error("App volume set failed: %s", e)

    @staticmethod
    def _get_app_volume(process_name: str) -> int:
        """Get current Volume Mixer level for a process (0-100), or -1 if not found."""
        try:
            from pycaw.pycaw import AudioUtilities
            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                proc = session.Process
                if proc is None:
                    continue
                if process_name.lower() in proc.name().lower():
                    return int(session.SimpleAudioVolume.GetMasterVolume() * 100)
        except Exception as e:
            log.error("App volume get failed: %s", e)
        return -1

    # ------------------------------------------------------------------
    # Linux helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _linux_get() -> int:
        try:
            out = subprocess.check_output(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"], text=True)
            for part in out.split():
                if part.endswith("%"):
                    return int(part.rstrip("%"))
        except Exception:
            pass
        try:
            out = subprocess.check_output(["amixer", "sget", "Master"], text=True)
            for part in out.split():
                if part.startswith("[") and part.endswith("%]"):
                    return int(part[1:-2])
        except Exception:
            pass
        return 50

    @staticmethod
    def _linux_set(level: int):
        try:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                           check=True, capture_output=True)
            return
        except Exception:
            pass
        subprocess.run(["amixer", "sset", "Master", f"{level}%"],
                       check=True, capture_output=True)

    @staticmethod
    def _linux_mute(state: bool):
        val = "mute" if state else "unmute"
        try:
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", val],
                           check=True, capture_output=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------

class Notifier:
    def send(self, title: str, message: str):
        try:
            if SYSTEM == "Windows":
                self._win_notify(title, message)
            elif SYSTEM == "Linux":
                subprocess.Popen(["notify-send", title, message])
        except Exception as e:
            log.warning("Notification failed: %s", e)

    @staticmethod
    def _win_notify(title: str, message: str):
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(title, message, duration=5, threaded=True)
        except ImportError:
            log.debug("win10toast not installed, skipping notification")


# ---------------------------------------------------------------------------
# Action executor
# ---------------------------------------------------------------------------

_volume  = VolumeController()
_notifier = Notifier()


def execute_action(action: Dict[str, Any], sound_id: str, similarity: float):
    atype = action.get("type", "log_only")
    log.info("Executing action '%s' (triggered by '%s', similarity=%.2f)",
             atype, sound_id, similarity)
    try:
        if atype == "volume_set":
            _volume.set(action.get("level", 80))

        elif atype == "volume_up":
            _volume.set(_volume.get() + action.get("amount", 10))

        elif atype == "volume_down":
            _volume.set(_volume.get() - action.get("amount", 10))

        elif atype == "volume_mute":
            _volume.mute(action.get("mute", True))

        elif atype == "app_volume_set":
            proc  = action.get("process", "chrome.exe")
            level = action.get("level", 80)
            VolumeController._set_app_volume(proc, level)

        elif atype == "app_volume_up":
            proc   = action.get("process", "chrome.exe")
            amount = action.get("amount", 10)
            cur    = VolumeController._get_app_volume(proc)
            if cur >= 0:
                VolumeController._set_app_volume(proc, min(100, cur + amount))

        elif atype == "app_volume_down":
            proc   = action.get("process", "chrome.exe")
            amount = action.get("amount", 10)
            cur    = VolumeController._get_app_volume(proc)
            if cur >= 0:
                VolumeController._set_app_volume(proc, max(0, cur - amount))

        elif atype == "notify":
            _notifier.send(
                action.get("title", "SoundReactor"),
                action.get("message", f"Detected: {sound_id}"),
            )

        elif atype == "run_command":
            cmd = action.get("command", "")
            if cmd:
                subprocess.Popen(cmd, shell=True)

        elif atype == "http_request":
            import urllib.request
            url    = action.get("url", "")
            method = action.get("method", "GET").upper()
            body   = action.get("body", "").encode()
            req    = urllib.request.Request(url, data=body or None, method=method)
            for k, v in action.get("headers", {}).items():
                req.add_header(k, v)
            urllib.request.urlopen(req, timeout=5)
            log.info("HTTP %s %s -> OK", method, url)

        elif atype == "log_only":
            log.info("[log_only] Sound '%s' detected (similarity=%.2f)", sound_id, similarity)

        else:
            log.warning("Unknown action type: %s", atype)

    except Exception as e:
        log.error("Action '%s' raised an error: %s", atype, e)


# ---------------------------------------------------------------------------
# Action metadata for GUI
# ---------------------------------------------------------------------------

ACTION_TYPES = {
    "volume_set":  {"label": "Set Volume",           "params": [("level",   "int",  80,  "Volume % (0-100)")]},
    "volume_up":   {"label": "Volume Up",            "params": [("amount",  "int",  10,  "Amount to increase (%)")]},
    "volume_down": {"label": "Volume Down",          "params": [("amount",  "int",  10,  "Amount to decrease (%)")]},
    "volume_mute": {"label": "Mute / Unmute",        "params": [("mute",    "bool", True,"True = mute, False = unmute")]},
    "notify":      {"label": "Desktop Notification", "params": [("title",   "str",  "SoundReactor",   "Title"),
                                                                  ("message", "str",  "Sound detected!","Message")]},
    "run_command": {"label": "Run Command",          "params": [("command", "str",  "",   "Shell command")]},
    "http_request":{"label": "HTTP Request",         "params": [("url",     "str",  "http://", "URL"),
                                                                  ("method",  "str",  "GET",     "Method"),
                                                                  ("body",    "str",  "",        "Body")]},
    "app_volume_set":  {"label": "App Volume Set",
                        "params": [("process", "str", "chrome.exe", "Process name (e.g. chrome.exe)"),
                                   ("level",   "int", 80,           "Volume % (0-100)")]},
    "app_volume_up":   {"label": "App Volume Up",
                        "params": [("process", "str", "chrome.exe", "Process name (e.g. chrome.exe)"),
                                   ("amount",  "int", 10,           "Amount to increase (%)")]},
    "app_volume_down": {"label": "App Volume Down",
                        "params": [("process", "str", "chrome.exe", "Process name (e.g. chrome.exe)"),
                                   ("amount",  "int", 10,           "Amount to decrease (%)")]},
    "log_only":    {"label": "Log Only (test)",      "params": []},
}
