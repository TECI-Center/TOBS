"""Tkinter GUI: dual camera view with timestamp overlay and recording."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

from .camera import CameraStream
from .devices import DeviceInfo, enumerate_devices

RECORDINGS_DIR = os.path.join(os.getcwd(), "recordings")
PREVIEW_W = 480
PREVIEW_H = 360
REFRESH_MS = 33  # ~30 fps preview


class CameraPanel(ttk.Frame):
    """One camera column: device picker, live preview, record/snapshot."""

    def __init__(self, master: tk.Widget, title: str, app: "App", hint: str = ""):
        super().__init__(master, padding=6)
        self.app = app
        self.title = title
        self.stream: CameraStream | None = None

        ttk.Label(self, text=title, font=("Helvetica", 13, "bold")).pack(pady=(0, 4))

        picker = ttk.Frame(self)
        picker.pack(fill="x")
        ttk.Label(picker, text="USB device:").pack(side="left")
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(
            picker, textvariable=self.device_var, state="readonly", width=28
        )
        self.device_combo.pack(side="left", fill="x", expand=True, padx=4)
        self.connect_btn = ttk.Button(picker, text="Connect", command=self.toggle_connect)
        self.connect_btn.pack(side="left")

        url_row = ttk.Frame(self)
        url_row.pack(fill="x", pady=(3, 0))
        ttk.Label(url_row, text="or Wi-Fi URL:").pack(side="left")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=4)

        if hint:
            ttk.Label(self, text=hint, foreground="#888888", wraplength=PREVIEW_W).pack(
                anchor="w", pady=(2, 0)
            )

        self.canvas = tk.Label(self, background="#111111", width=PREVIEW_W, height=PREVIEW_H)
        self.canvas.pack(pady=6)
        self._blank()

        controls = ttk.Frame(self)
        controls.pack(fill="x")
        self.record_btn = ttk.Button(
            controls, text="● Record", command=self.toggle_record, state="disabled"
        )
        self.record_btn.pack(side="left")
        self.snapshot_btn = ttk.Button(
            controls, text="Snapshot", command=self.take_snapshot, state="disabled"
        )
        self.snapshot_btn.pack(side="left", padx=4)

        self.status = ttk.Label(self, text="Not connected", foreground="#888888")
        self.status.pack(anchor="w", pady=(4, 0))

        self._imgtk: ImageTk.PhotoImage | None = None

    # -- device selection --------------------------------------------------
    def set_devices(self, devices: list[DeviceInfo]) -> None:
        values = [d.label for d in devices]
        self.device_combo["values"] = values
        self._devices = devices
        if values and not self.device_var.get():
            self.device_combo.current(0)

    def _selected_device(self) -> DeviceInfo | None:
        label = self.device_var.get()
        for d in getattr(self, "_devices", []):
            if d.label == label:
                return d
        return None

    def toggle_connect(self) -> None:
        if self.stream is None:
            self.connect()
        else:
            self.disconnect()

    def connect(self) -> None:
        url = self.url_var.get().strip()
        if url:
            source: int | str = url
        else:
            dev = self._selected_device()
            if dev is None:
                self.status.config(text="Pick a USB device or enter a URL", foreground="#cc6666")
                return
            source = dev.index
        self.stream = CameraStream(source=source, label=self.title)
        self.stream.start()
        self.connect_btn.config(text="Disconnect")
        self.record_btn.config(state="normal")
        self.snapshot_btn.config(state="normal")
        self.device_combo.config(state="disabled")
        self.url_entry.config(state="disabled")

    def disconnect(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream = None
        self.connect_btn.config(text="Connect")
        self.record_btn.config(text="● Record", state="disabled")
        self.snapshot_btn.config(state="disabled")
        self.device_combo.config(state="readonly")
        self.url_entry.config(state="normal")
        self.status.config(text="Not connected", foreground="#888888")
        self._blank()

    # -- recording ---------------------------------------------------------
    def toggle_record(self) -> None:
        if self.stream is None:
            return
        if self.stream.recording:
            self.stream.stop_recording()
            self.record_btn.config(text="● Record")
        else:
            path = self.stream.start_recording(RECORDINGS_DIR, self.app.container())
            if path:
                self.record_btn.config(text="■ Stop")

    def take_snapshot(self) -> None:
        if self.stream is not None:
            self.stream.snapshot(RECORDINGS_DIR)

    # -- rendering ---------------------------------------------------------
    def _blank(self) -> None:
        img = Image.new("RGB", (PREVIEW_W, PREVIEW_H), (17, 17, 17))
        self._imgtk = ImageTk.PhotoImage(img)
        self.canvas.config(image=self._imgtk)

    def update_preview(self) -> None:
        if self.stream is None:
            return
        frame = self.stream.latest_frame()
        if frame is None:
            self.status.config(text="Waiting for signal…", foreground="#cc9966")
            return

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        img.thumbnail((PREVIEW_W, PREVIEW_H))
        self._imgtk = ImageTk.PhotoImage(img)
        self.canvas.config(image=self._imgtk)

        rec = "  ●REC" if self.stream.recording else ""
        conn = "Live" if self.stream.connected else "Reconnecting…"
        color = "#66cc66" if self.stream.connected else "#cc9966"
        self.status.config(text=f"{conn}  {self.stream.fps:.0f} fps{rec}", foreground=color)


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=10)
        master.title("TOBS — Dual Camera Recorder")
        master.protocol("WM_DELETE_WINDOW", self.on_close)
        self.pack(fill="both", expand=True)

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="↻ Rescan devices", command=self.rescan).pack(side="left")
        ttk.Label(toolbar, text="Format:").pack(side="left", padx=(12, 2))
        self.format_var = tk.StringVar(value="mp4")
        ttk.Combobox(
            toolbar,
            textvariable=self.format_var,
            state="readonly",
            width=6,
            values=["mp4", "mkv"],
        ).pack(side="left")
        ttk.Button(toolbar, text="● Record Both", command=self.record_both).pack(side="left", padx=(12, 2))
        ttk.Button(toolbar, text="■ Stop Both", command=self.stop_both).pack(side="left")
        ttk.Label(toolbar, text=f"Saving to: {RECORDINGS_DIR}").pack(side="right")

        panels = ttk.Frame(self)
        panels.pack(fill="both", expand=True)
        self.left = CameraPanel(panels, "GoPro Hero 8", self)
        self.left.pack(side="left", fill="both", expand=True)
        ttk.Separator(panels, orient="vertical").pack(side="left", fill="y", padx=6)
        self.right = CameraPanel(
            panels,
            "ORDRO EP8",
            self,
            hint="Wi-Fi: join the EP8's hotspot, then paste its RTSP/HTTP stream URL above "
            "(e.g. rtsp://192.168.1.254/xxxx). Leave USB device blank when using Wi-Fi.",
        )
        self.right.pack(side="left", fill="both", expand=True)

        self.rescan()
        self._tick()

    def container(self) -> str:
        return self.format_var.get()

    def rescan(self) -> None:
        devices = enumerate_devices()
        self.left.set_devices(devices)
        self.right.set_devices(devices)
        # Default the two panels to different devices when possible.
        if len(devices) >= 2:
            self.left.device_combo.current(0)
            self.right.device_combo.current(1)

    def record_both(self) -> None:
        for panel in (self.left, self.right):
            if panel.stream is not None and not panel.stream.recording:
                panel.toggle_record()

    def stop_both(self) -> None:
        for panel in (self.left, self.right):
            if panel.stream is not None and panel.stream.recording:
                panel.toggle_record()

    def _tick(self) -> None:
        self.left.update_preview()
        self.right.update_preview()
        self.after(REFRESH_MS, self._tick)

    def on_close(self) -> None:
        self.left.disconnect()
        self.right.disconnect()
        self.master.destroy()


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
