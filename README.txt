================================================
  Hand Gesture Scroll Controller — Mac
  Controls your Mac's scroll with your hand
================================================

WHAT IT DOES
------------
Open this app and hold your hand in front of your
webcam. A window shows your camera with glowing
hand-tracking lines drawn over your hand.

  Raise your hand above the middle → scroll UP
  Lower your hand below the middle → scroll DOWN
  Flick your hand quickly          → fast scroll (flick)
  Make a fist                      → pause scrolling
  Pinch (thumb + index)            → press Like (L key)
  No hand visible                  → scrolling stops

It controls the scroll of whichever window is currently
in focus on your Mac — so switch to Chrome/Safari/etc,
then wave your hand to scroll.

Press Q (or close the window) to quit.


OPTION A — Double-click App (Recommended)
------------------------------------------
For the easiest experience, build a proper Mac app
that you can drag to your Applications folder.

1. Make sure Python 3 is installed.
   → https://python.org  (download the latest version)

2. Double-click:  build_app.command

   If macOS says it can't be opened:
   → Right-click → Open → Open

3. Wait 3-5 minutes while it builds. When done,
   "Hand Scroll Controller.app" will appear on your
   Desktop with a Finder window.

4. Drag it to your Applications folder.

5. Double-click it any time to launch — no Terminal,
   no setup, just click and go.

Note: The first launch may ask for camera permission.
Click OK to allow it.


OPTION B — launch.command (Quick Start)
-----------------------------------------
If you'd rather skip the build step:

1. Make sure Python 3 is installed (https://python.org)

2. Double-click:  launch.command

   If macOS says it can't be opened:
   → Right-click → Open → Open

3. On first run it installs dependencies automatically
   (~1-2 min). Every launch after that is instant.


TIPS
----
- Use in a well-lit room — works best with good lighting
- Keep your hand clearly visible to the camera
- The glowing lines show what the app is tracking
- The colored zones on screen show where to put your hand
- "Dead zone" (middle area) = no scroll (hand at rest)
- Move your hand higher or lower for faster scroll speed


TROUBLESHOOTING
---------------
Camera not opening?
  → Make sure no other app (Zoom, FaceTime, etc.) is using it
  → Check System Settings → Privacy & Security → Camera
    and make sure Hand Scroll Controller is allowed

Hand not detected?
  → Improve lighting — face a window or turn on a lamp
  → Keep your full hand visible, fingers spread slightly

Scrolling jumpy?
  → Slow your hand movements down slightly
  → Stay within the camera frame

App won't launch after building?
  → Try running build_app.command again
  → Make sure you're using Python 3.10 or later


================================================
