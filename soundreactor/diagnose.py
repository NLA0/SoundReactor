import sys, traceback

try:
    from core.config import Config
    print("Config OK")
    c = Config("config.json")
    print("Config instance OK")
    from core.fingerprint import FingerprintDatabase, FingerprintMatcher
    print("Fingerprint OK")
    from core.actions import execute_action
    print("Actions OK")
    from core.detector import SoundDetector
    print("Detector OK")
    from ui.app import SoundReactorApp
    print("App import OK")
    app = SoundReactorApp(c)
    print("App instance OK - window should appear")
except Exception as e:
    traceback.print_exc()

input("Press Enter to close...")
