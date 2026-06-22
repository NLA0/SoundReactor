import pycaw
print("pycaw version:", getattr(pycaw, "__version__", "unknown"))

from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
print("AudioUtilities methods:", [m for m in dir(AudioUtilities) if not m.startswith("_")])

speakers = AudioUtilities.GetSpeakers()
print("GetSpeakers() type:", type(speakers))
print("GetSpeakers() attributes:", [m for m in dir(speakers) if not m.startswith("_")])

input("\nPress Enter to close...")
