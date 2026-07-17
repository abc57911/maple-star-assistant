MapleStar

Usage:
1. Extract the zip file to a normal folder.
2. Run MapleStar.exe.
3. Keep MapleStory Worlds in the foreground when using automation.
4. Settings are saved to settings.json next to MapleStar.exe.

Notes:
- RB function is disabled by default. Enable it in the GUI when needed.
- HP and MP potion keys, thresholds, and cooldowns can be changed in the GUI.
- HP/MP automation only runs when the target game window is in the foreground and the HUD is detected.
- A 100% potion threshold does not trigger while the bar is already full.
- Experience efficiency uses on-screen EXP text with Pixel OCR primary and PaddleOCR fallback, and keeps the last trusted result during temporary OCR failures.
- When experience efficiency is paused and enabled again, the next sample resumes from the last trusted statistics.
- Level-up ETA is shown as h:mm:ss. Values below one hour are shown as 00:mm:ss.
- If the GUI does not open, check startup_error.log in the same folder.
- This package is intended for Windows.
