# TOBS — Tap Onto Both Sources

A **cross-platform (Windows + macOS)** desktop app that taps into a
**USB-connected GoPro Hero 8** (in Webcam mode) and an **ORDRO EP8 streaming
over its own Wi-Fi**, shows both live feeds side-by-side with a **visible
timestamp burned into the image**, and records each camera to your local disk as
**MP4** or **MKV**.

Built with Python + OpenCV + Tkinter.

---

## What it does

- Two sources per session: a **USB webcam** (by device index) or a **network
  stream** (RTSP/HTTP URL) — pick either per panel.
- Live side-by-side preview of both cameras.
- A running `YYYY-MM-DD HH:MM:SS` timestamp is drawn onto every frame — so it is
  visible both in the preview **and** in the saved recordings.
- Per-camera **Record**, **Snapshot**, plus a combined **Record (split + audio)**
  that writes **both cameras side-by-side in one frame together with microphone
  audio into a single MP4/MKV file**.
- Pick a **microphone** from the toolbar to mux live audio into the combined file.
- Auto-reconnect if a camera briefly drops off.
- Files are written to a `recordings/` folder next to the app.

---

## 1. Prerequisites

- **Windows 10/11 or macOS**, with Python 3.10+ (`python --version` /
  `python3 --version`).
- The GoPro must appear as a **webcam**; the ORDRO is used over **Wi-Fi** as a
  stream URL. See camera-specific setup below.

### GoPro Hero 8 (USB Webcam mode)

The Hero 8 does **not** show up as a plain USB webcam by itself. You need:

1. Update the camera to the latest firmware using the **GoPro Quik** app.
2. Install the **GoPro Webcam** desktop utility (Windows & macOS):
   https://gopro.com/en/us/info/gopro-webcam
3. Connect the Hero 8 via USB-C. A camera icon appears in the menu bar
   (macOS) / system tray (Windows) when the utility detects it.
4. Choose **Start** (or it auto-starts). This creates a virtual camera named
   **"GoPro Webcam"** that this app can select from the **USB device** dropdown.

> Tip: If the GoPro shows up but the feed is black, quit any other app using it
> (Zoom, Teams, QuickTime) and click **Rescan devices** in TOBS.

### ORDRO EP8 over its own Wi-Fi (network stream)

The EP8 broadcasts a **Wi-Fi hotspot** and streams live video over it — you
connect by URL instead of USB:

1. Turn on Wi-Fi on the EP8 (via its menu or the ORDRO/companion app).
2. On your computer, **join the EP8's Wi-Fi hotspot** (SSID/password are in the
   camera menu or its manual). Your machine now shares the camera's network.
3. Find the camera's **stream URL**. It's typically an RTSP or HTTP URL on the
   camera's gateway IP, for example:
   - `rtsp://192.168.1.254/xxxx`
   - `rtsp://192.168.42.1/live`
   - `http://192.168.1.254:8080/?action=stream` (MJPEG)
   The exact host/path depends on the firmware. **Confirm it plays in VLC**
   (`File → Open Network Stream`) before using it here.
4. In TOBS, paste that URL into the ORDRO panel's **Wi-Fi URL** box and click
   **Connect** (leave its USB device blank).

> Tip: `rtsp://` streams are requested over TCP automatically for reliability.
> If you only get audio/black video, the path is wrong — re-check it in VLC.

---

## 2. Install

### macOS

```bash
cd /Users/calvinperumalla/git/TOBS
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> If you hit `ModuleNotFoundError: _tkinter` on Homebrew Python, install the Tk
> bindings: `brew install python-tk@3.13` (match your Python version), then
> recreate the venv.

### Windows (PowerShell)

```powershell
cd path\to\TOBS
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Tkinter ships with the standard python.org Windows installer. `pygrabber` is
> installed automatically on Windows to show friendly camera names.

---

## 3. Run

```bash
python main.py
```

The first time, the OS may ask for **Camera permission** — allow it
(macOS: System Settings → Privacy & Security → Camera).

### Using the app

1. Click **↻ Rescan devices** if USB cameras were plugged in after launch.
2. **GoPro panel** → pick "GoPro Webcam" from the **USB device** dropdown.
   **ORDRO panel** → paste its **Wi-Fi URL** (leave USB device blank).
3. Click **Connect** on each panel to start the live preview.
4. Pick the output **Format** (mp4 or mkv) in the toolbar.
5. Per-camera capture: click **● Record** on a panel (video-only), or
   **Snapshot** for a single timestamped still.
6. Combined capture: choose a **Microphone** in the toolbar, then click
   **● Record (split + audio)**. This burns both camera feeds side-by-side into
   **one** frame and muxes the mic audio into a **single** file
   (`recordings/combined_*.mp4`). Leave the microphone on **(no audio)** to write
   the split video without sound.

Recordings and snapshots are saved to the `recordings/` folder.

---

## Project layout

```
main.py                 # entry point
requirements.txt
src/tobs/
  app.py                # Tkinter GUI (dual view, controls)
  camera.py             # threaded capture + recorder
  devices.py            # USB video device discovery
  audio.py              # microphone discovery
  recorder.py           # combined split-view video + audio muxer (PyAV)
  overlay.py            # timestamp burn-in
```

---

## Troubleshooting

- **A camera isn't listed** — for USB, make sure it's in webcam mode and click
  **Rescan devices** (only devices that return a frame are shown). For the
  ORDRO, it won't appear in the USB list at all — use the **Wi-Fi URL** box.
- **Wi-Fi stream won't connect** — confirm your computer is joined to the EP8's
  hotspot and that the **exact URL plays in VLC** first. Try TCP by keeping the
  `rtsp://` scheme (the app requests RTSP-over-TCP automatically).
- **Both dropdowns show the same device** — the app defaults them to different
  indices when two are found; otherwise pick manually.
- **Recording won't start** — a valid live frame is required first; connect and
  wait for the preview, then record.
- **Choppy or low fps** — USB bandwidth and Wi-Fi signal both matter. Move
  closer to the camera, reduce distance/interference, or use a different USB
  port/hub.

---

## Notes & limitations

- Per-camera recordings are **video-only** (no audio) via OpenCV's `VideoWriter`.
- The combined **Record (split + audio)** file carries audio: it is encoded with
  PyAV (bundled ffmpeg, H.264 video + AAC audio) and needs a selected microphone
  for sound. `av` and `sounddevice` install from `requirements.txt`; on macOS the
  OS also prompts for **Microphone** permission the first time.
- The timestamp reflects your computer's local clock at capture time.
- USB device index → camera-name mapping is best-effort (macOS via
  `system_profiler`, Windows via `pygrabber`); use the name hint plus a quick
  connect to confirm which is which. Wi-Fi cameras are identified by their URL.