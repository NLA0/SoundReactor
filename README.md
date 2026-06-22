# SoundReactor
python script which reacts to specific sounds and takes an action; can be used to lower volume on TV ads on PC using on a Shazam-like algorythm based on a sound database yuou record yourself from the TV app. 
General schema:
soundreactor/               ← project root folder (name it whatever you like)
│
├── main.py                 ← goes here (root)
│
├── config.json             ← auto-created on first run
├── soundreactor.log        ← auto-created on first run
│
├── core/                   ← create this subfolder
│   ├── __init__.py         ← empty file, required!
│   ├── config.py
│   ├── fingerprint.py
│   ├── detector.py
│   └── actions.py
│
├── ui/                     ← create this subfolder
│   ├── __init__.py         ← empty file, required!
│   └── app.py
│
└── sounds_db/              ← create this subfolder (put your MP3s here)

The two __init__.py files are important — they tell Python that core/ and ui/ are packages. You can create them as completely empty files.
Install python (v3 or higher)
pip install librosa sounddevice numpy pycaw comtypes win10toast scipy

How to run it: 
cd D:\Claude\soundreactor
python main.py
Or make a shortcut on desktop with Target ex. C:\Users\pinad\AppData\Local\Microsoft\WindowsApps\python.exe d:\claude\soundreactor\main.py and Start in: d:\claude\soundreactor
Optional: create scheduler job if you want it to start at boot time. 

Note: To adjust input_device in config.py and config.json you can use "input_device": None,        # None = system default or use the following script to find the number of your device:
D:\Claude\soundreactor>python diagnose_audio.py
AVAILABLE AUDIO INPUT DEVICES:
------------------------------------------------------------
  [ 0] Microsoft Sound Mapper - Input  (SR=44100)
  [ 1] Mic/Line/Instr 1 (CONNECT 6)  (SR=44100)
  [ 2] Mix A (CONNECT 6)  (SR=44100) <-- likely stereo mix    <>>>>>>> for this device use : "input_device": 2,
  ....etc

  
