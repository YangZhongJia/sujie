<p align="center">
  <a href="README.md">简体中文</a> | <a href="README_EN.md">English</a>
</p>

<div align="center">
  <img src="assets/sujie.png" alt="Sujie icon" width="92">
  <h1>Sujie</h1>
  <p><strong>One click on a floating ball — screenshot, annotate, record — and it appears on your other computer.</strong></p>
  <p>Direct LAN transfer · Original quality · No sign-in · No cloud involved</p>
  <p>
    <img src="https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10/11">
    <img src="https://img.shields.io/badge/Network-LAN%20only-43853D" alt="LAN only">
    <img src="https://img.shields.io/badge/version-1.2.0-e94f37" alt="v1.2.0">
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  </p>
</div>

---

## Why Sujie

If you work on more than one computer — a desktop plus a laptop, an office machine plus a home machine — you know these moments:

- What you need is on the desktop while you are on the laptop. **Send it over WeChat?** That means logging in, grabbing your phone, and the image gets compressed;
- Want to send a how-to demo to another computer? **Copy it to a USB stick?** By the third copy you have lost track of the file;
- Cloud drives? Upload, walk over, download again — waiting for a dozens-of-MB recording is nobody's idea of fun.

**Sujie compresses all of that into one second**: click the floating ball on this computer, and the screenshot (or recording, or any file) lands in the other computer's "Pictures\Sujie" folder — original quality, LAN speed, and not a single account required.

| | WeChat / QQ file transfer | Cloud drive | **Sujie** |
| --- | :-: | :-: | :-: |
| Original quality | Compressed | Depends on your plan | **PNG originals, untouched** |
| Sign-in / phone QR scan | Yes | Yes | **Not needed** |
| Speed | Limited by internet bandwidth | Upload, then download | **Direct LAN transfer** |
| Send to many computers at once | One by one | Each downloads separately | **Delivered simultaneously** |
| Recipient is offline | Fails | Wait for sync | **Auto-retry queue** |
| Where data travels | Tencent's servers | Cloud servers | **Stays inside your LAN** |

## Screenshots

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/images/ball-desktop.png" alt="Floating ball on the desktop" width="440"><br>
      <sub>A floating ball always on your desktop — click to capture</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/images/radial-menu.png" alt="Four-direction radial menu" width="440"><br>
      <sub>Long-press for the radial menu: capture / record / pin / history</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/images/editor.png" alt="Screenshot editor" width="440"><br>
      <sub>Pen, arrow, rectangle, text, mosaic — annotate, then send</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/images/pin.png" alt="Pin a screenshot on screen" width="440"><br>
      <sub>Pin: keep a screenshot on top while you work</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/images/settings-receivers.png" alt="Receiver settings" width="440"><br>
      <sub>Scan the LAN, configure multiple receiver computers at once</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/images/history.png" alt="Recent history" width="440"><br>
      <sub>Everything you sent, one list, resend anytime</sub>
    </td>
  </tr>
</table>

## Features

### 1. One ball does everything

No shortcuts to memorize, no window to hunt for. The ball sits in a corner: **single-click** captures with the current mode (active window / current monitor / full screen / region); **long-press** opens the four-direction radial menu — flick toward an action and release. In the way? Drag it to any edge or hide it and use the global hotkey.

<div align="center">
  <img src="docs/images/radial-menu.png" alt="Radial menu" width="420">
</div>

### 2. Capture → annotate → send, in one flow

Every capture opens the editor: pen, arrow, rectangle, circle, text, mosaic, with undo/redo. Hit "Send" and it is delivered to **all** receiver computers at once. Don't want to send? `Ctrl+C` copies it, `Ctrl+S` saves it locally, or pin it to the screen.

<div align="center">
  <img src="docs/images/editor.png" alt="Screenshot editor" width="480">
</div>

### 3. You decide what happens after capture

Settings → Capture → "After-capture action", four modes:

| Mode | Best for |
| --- | --- |
| Open editor (default) | Annotate or blur before sending |
| **Send directly** | Maximum speed: click → arrives instantly |
| **Copy to clipboard** | Paste elsewhere, purely local |
| **Pin to screen** | Keep a reference visible while you work |

Plus global hotkeys `Ctrl+Alt+S` (capture) and `Ctrl+Alt+R` (record) — hands never leave the keyboard.

<div align="center">
  <img src="docs/images/settings-capture.png" alt="Capture settings" width="420">
</div>

### 4. Not just screenshots: recording, pinning, any file

- **Screen recording**: bundled ffmpeg — monitor / full screen / window / region, with optional microphone narration; sent automatically when you stop;
- **Pin**: keep a screenshot above everything, zoom with the wheel, drag it around — perfect for copying reference material;
- **Send any file**: right-click the ball → "Send file…". Documents, archives, installers — receivers keep the **original filename**.

### 5. Many receivers at once, nothing lost while offline

Configure once, deliver to N computers. One of them is off? Failed items wait in the outbox and are re-sent automatically when it comes back online — computers that already received the file **never get it twice**. Each receiver can have its own shared key.

### 6. Recent history

Every screenshot, recording, and file you sent lives in "History": with thumbnails, open original, open folder, and one-click resend. Clearing history never touches your original files.

## Get started in 30 seconds

1. Install the same installer on two Windows computers connected to the same LAN;
2. **Pick a work mode**: first launch asks; change anytime via the Start-menu shortcuts ("Screenshot only", "Receive only", "Both", "Change work mode"), or the receiver tray menu;
3. On the sending computer: Settings → Receivers → "Scan LAN" → double-click a device → Save;
4. Click the floating ball. Done.

Which mode to pick:

| Mode | What this computer does | What you see |
| --- | --- | --- |
| Screenshot only | Sends screenshots, recordings, files | Floating ball + tray icon |
| Receive only | Quietly receives files, never captures | Tray icon only |
| Both | Sends and receives | Floating ball + tray icon |

Received files land in "Pictures\Sujie", sorted into dated folders. Click the tray icon to open them.

## Typical use cases

- **Two-machine work**: take notes on the laptop while the desktop crunches; screenshot the result on the desktop and it is on the laptop in a second;
- **Bug reports / debugging**: record the repro steps, they appear on your colleague's computer directly — no cloud upload, no link sharing; annotate the error dialog with a red arrow and fire away;
- **Remote help for family**: install the receiver on your parents' computer; start/stop a recording with `Ctrl+Alt+R` and walk them through it;
- **Working from a reference**: pin the mockup in a corner, zoom to fit, and compare as you build;
- **Moving small files**: one config file, one document — right-click → Send file beats shared folders and cloud drives.

## Quick reference

| Action | Result |
| --- | --- |
| Click the floating ball | Capture with the current mode, run the after-capture action |
| `Ctrl` + `Alt` + `S` | Global hotkey: capture (works anywhere) |
| `Ctrl` + `Alt` + `R` | Start / stop screen recording |
| Long-press, flick up | Capture |
| Long-press, flick left | Start recording; click the ball again to stop and send |
| Long-press, flick right | Pin the current screen (pin to top) |
| Long-press, flick down | Open recent history |
| Right-click → Send file… | Send any file to all receivers, original filename kept |
| In the editor: `Ctrl+C` / `Ctrl+S` | Copy result to clipboard / save locally |

## Network & privacy

Sujie **transfers directly inside your LAN**: no cloud, no public relay, no accounts. The installer adds firewall rules for private networks (TCP 8765 for files, UDP 8766 for discovery).

Traffic uses HTTP and is not encrypted; the shared key is for receiver authentication. Use it on LANs you trust, and do not forward the receiver port to the internet.

## FAQ

**Installed but no floating ball?**
This computer is in "Receive only" mode, which lives in the tray and shows no ball by design. Open the Start-menu shortcut "Change work mode" (or the receiver tray icon → "Work mode") and switch to "Screenshot only" or "Both".

**Receiver gets nothing?**
Make sure both computers are on the same LAN and Windows network profile is "Private". On the sender: Settings → Receivers → "Scan" or "Test connection" — failures show the reason.

**Where do received files go?**
"Pictures\Sujie" by default, in dated folders. Change the folder from the receiver tray menu.

**Do images get compressed?**
No. Screenshots travel as PNG originals; recordings and files as raw bytes.

**The other computer is offline?**
Failed items wait in the outbox (open it from the tray menu) and are re-sent when it comes back — already-served receivers are never double-sent.

**Is there a file size limit?**
The receiver default is 2048 MB per file, adjustable in receiver settings.

**Can one sender serve many computers?**
Yes, no limit on receivers. Two machines can also send in both directions ("Both" mode).

## Changelog

**v1.2.0** (2026-10-24)
- Global capture hotkey `Ctrl+Alt+S`; four after-capture actions (editor / send / copy / pin)
- Editor gained "Copy to clipboard" and "Save locally"
- New "Send file…": any file type to multiple computers, original filenames kept
- History supports files; fixed screenshots not appearing in history
- Stability fixes: occasional multi-target upload hangs, concurrent receiver writes overwriting each other, settings dialog freezing during connection tests, clearing history deleting original recordings, wrong recording area when a secondary monitor sits left of the primary

**v1.1.x** (2026-10-23)
- Screen recording (region / window / monitor / full screen, bundled ffmpeg)
- Long-press radial menu, screen pinning, recent history
- New UI design, first-launch mode picker

**v1.0**
- Floating-ball capture, annotation editor, multi-target LAN sending, offline retry

## Build from source

Windows, Python 3.10+, and Inno Setup 6 are required.

```powershell
python -m pip install PySide6 Pillow PyInstaller imageio-ffmpeg
powershell -NoProfile -ExecutionPolicy Bypass -File tools\package.ps1
```

The installer is written to `dist\installer\`. The build script prepares the recording component from `imageio-ffmpeg`; ffmpeg is large and not committed to the repository.

## License

No open-source license has been added yet. The public repository does not imply permission to copy, modify, or distribute.
