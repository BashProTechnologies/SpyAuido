import os
import json
import logging
import threading
import tkinter as tk
from typing import Dict, Any, Optional
import customtkinter as ctk
from PIL import Image, ImageDraw

from app.audio_recorder import AudioRecorder
from app.ws_client import WebSocketClient
from app.autostart import set_autostart, is_autostart_enabled

logger = logging.getLogger("baby.gui")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class BabyMonitorApp(ctk.CTk):
    def __init__(self, config_path: str):
        super().__init__()

        self.config_path = config_path
        self.config = self._load_config()

        self.title("BABY MONITOR - Baby Room Client")
        self.geometry("450x550")
        self.resizable(False, False)

        # Audio & Network core
        self.recorder: Optional[AudioRecorder] = None
        self.ws_client: Optional[WebSocketClient] = None
        self.is_testing = False

        # System tray
        self.tray_icon = None

        self._build_ui()
        self._init_core()

        # Handle window close (minimize to tray if requested)
        self.protocol("WM_DELETE_WINDOW", self.on_window_close)

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        return {}

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def _build_ui(self):
        # Header
        self.header_label = ctk.CTkLabel(
            self, text="BABY ROOM MONITOR", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.header_label.pack(pady=15)

        # Status Frame
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.pack(fill="x", padx=20, pady=10)

        self.status_title = ctk.CTkLabel(self.status_frame, text="Status:", font=ctk.CTkFont(weight="bold"))
        self.status_title.grid(row=0, column=0, padx=10, pady=8, sticky="w")

        self.status_val = ctk.CTkLabel(self.status_frame, text="INITIALIZING", text_color="#FFCC00")
        self.status_val.grid(row=0, column=1, padx=10, pady=8, sticky="e")

        self.server_title = ctk.CTkLabel(self.status_frame, text="Server:", font=ctk.CTkFont(weight="bold"))
        self.server_title.grid(row=1, column=0, padx=10, pady=8, sticky="w")

        self.server_val = ctk.CTkLabel(self.status_frame, text="Connecting...", text_color="#AAAAAA")
        self.server_val.grid(row=1, column=1, padx=10, pady=8, sticky="e")

        # Microphone Selection Frame
        self.mic_frame = ctk.CTkFrame(self)
        self.mic_frame.pack(fill="x", padx=20, pady=10)

        self.mic_label = ctk.CTkLabel(self.mic_frame, text="Microphone Device:", font=ctk.CTkFont(weight="bold"))
        self.mic_label.pack(anchor="w", padx=10, pady=(8, 2))

        self.mic_devices = AudioRecorder.get_input_devices()
        dev_names = [f"[{d['index']}] {d['name']}" for d in self.mic_devices] if self.mic_devices else ["Default Microphone"]

        self.mic_optionmenu = ctk.CTkOptionMenu(
            self.mic_frame, values=dev_names, command=self._on_mic_selected
        )
        self.mic_optionmenu.pack(fill="x", padx=10, pady=(0, 10))

        # Audio Level Meter
        self.level_frame = ctk.CTkFrame(self)
        self.level_frame.pack(fill="x", padx=20, pady=10)

        self.level_label = ctk.CTkLabel(self.level_frame, text="Audio Level Meter:", font=ctk.CTkFont(weight="bold"))
        self.level_label.pack(anchor="w", padx=10, pady=(8, 2))

        self.progressbar = ctk.CTkProgressBar(self.level_frame)
        self.progressbar.pack(fill="x", padx=10, pady=(0, 10))
        self.progressbar.set(0.0)

        # Voice Detection Toggle
        self.vad_switch = ctk.CTkSwitch(
            self, text="Voice Activated Streaming (VAD)", command=self._on_vad_toggle
        )
        self.vad_switch.pack(pady=10)
        if self.config.get("mode") == "vad":
            self.vad_switch.select()

        # Action Buttons
        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.pack(fill="x", padx=20, pady=15)

        self.test_btn = ctk.CTkButton(
            self.btn_frame, text="Test Microphone", command=self._toggle_mic_test
        )
        self.test_btn.pack(side="left", expand=True, padx=5)

        self.stealth_btn = ctk.CTkButton(
            self.btn_frame, text="Hide to Tray", fg_color="#333333", command=self.hide_to_tray
        )
        self.stealth_btn.pack(side="right", expand=True, padx=5)

        # Settings Modal Trigger
        self.settings_btn = ctk.CTkButton(
            self, text="Settings & Autostart", fg_color="transparent", border_width=1, command=self._open_settings
        )
        self.settings_btn.pack(pady=5)

    def _init_core(self):
        # Audio Recorder setup
        self.recorder = AudioRecorder(
            sample_rate=self.config.get("sample_rate", 16000),
            channels=self.config.get("channels", 1),
            device_index=self.config.get("audio_device_index"),
            on_audio_frame=self._handle_audio_frame
        )
        self.recorder.vad.threshold_db = self.config.get("vad_threshold", 35.0)

        # WebSocket Client setup
        self.ws_client = WebSocketClient(
            server_url=self.config.get("server_url", "ws://127.0.0.1:8000/ws/stream"),
            device_id=self.config.get("device_id", "baby_room_pc_01"),
            device_token=self.config.get("device_token", "secure_token_baby_room_98765"),
            on_status_change=self._handle_ws_status_change
        )

        # Start Services safely
        mic_success = self.recorder.start()
        if not mic_success:
            self.status_val.configure(text="NO MICROPHONE", text_color="#FF3333")

        self.ws_client.start()

    def _handle_audio_frame(self, pcm_bytes: bytes, level: float, is_vad_active: bool):
        # Update progressbar level in main thread safe manner
        self.after(0, self._update_meter, level)

        # Send frame via WebSocket if connected
        if self.ws_client:
            self.ws_client.send_audio_frame(pcm_bytes)

    def _update_meter(self, level: float):
        self.progressbar.set(level / 100.0)

    def _handle_ws_status_change(self, status: str, desc: str):
        def _update():
            if status == "CONNECTED":
                self.status_val.configure(text="STREAMING", text_color="#00FF66")
                self.server_val.configure(text="Connected", text_color="#00FF66")
            elif status == "CONNECTING":
                self.status_val.configure(text="CONNECTING", text_color="#FFCC00")
                self.server_val.configure(text="Connecting...", text_color="#FFCC00")
            else:
                self.status_val.configure(text="OFFLINE", text_color="#FF3333")
                self.server_val.configure(text="Disconnected", text_color="#FF3333")

        self.after(0, _update)

    def _on_mic_selected(self, choice: str):
        try:
            dev_idx = int(choice.split("]")[0].replace("[", ""))
            self.recorder.set_device(dev_idx)
            self.config["audio_device_index"] = dev_idx
            self._save_config()
        except Exception as e:
            logger.error(f"Error setting mic device: {e}")

    def _on_vad_toggle(self):
        if self.vad_switch.get() == 1:
            self.recorder.mode = "vad"
            self.config["mode"] = "vad"
        else:
            self.recorder.mode = "continuous"
            self.config["mode"] = "continuous"
        self._save_config()

    def _toggle_mic_test(self):
        self.is_testing = not self.is_testing
        if self.is_testing:
            self.test_btn.configure(text="Stop Test", fg_color="#CC0000")
        else:
            self.test_btn.configure(text="Test Microphone", fg_color=["#3A7EBF", "#1F538D"])

    def _open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("400x380")
        dialog.grab_set()

        lbl_url = ctk.CTkLabel(dialog, text="Server WebSocket URL:")
        lbl_url.pack(anchor="w", padx=20, pady=(15, 2))

        entry_url = ctk.CTkEntry(dialog, width=350)
        entry_url.insert(0, self.config.get("server_url", "ws://127.0.0.1:8000/ws/stream"))
        entry_url.pack(padx=20, pady=5)

        autostart_var = ctk.BooleanVar(value=is_autostart_enabled())

        def _toggle_reg():
            set_autostart(autostart_var.get())
            self.config["autostart"] = autostart_var.get()
            self._save_config()

        chk = ctk.CTkCheckBox(dialog, text="Start on Windows Boot", variable=autostart_var, command=_toggle_reg)
        chk.pack(pady=10, padx=20, anchor="w")

        tray_icon_var = ctk.BooleanVar(value=self.config.get("show_tray_icon", False))
        chk_tray = ctk.CTkCheckBox(dialog, text="Show Icon in System Tray", variable=tray_icon_var)
        chk_tray.pack(pady=5, padx=20, anchor="w")

        lbl_thresh = ctk.CTkLabel(dialog, text="VAD Threshold Level:")
        lbl_thresh.pack(anchor="w", padx=20, pady=(10, 0))

        slider_thresh = ctk.CTkSlider(dialog, from_=10.0, to=80.0, number_of_steps=70)
        slider_thresh.set(self.config.get("vad_threshold", 35.0))
        slider_thresh.pack(fill="x", padx=20, pady=5)

        def _save_settings():
            new_url = entry_url.get()
            self.config["server_url"] = new_url
            if self.ws_client:
                self.ws_client.server_url = new_url
                self.ws_client.stop()
                self.ws_client.start()
            new_thresh = slider_thresh.get()
            self.recorder.vad.threshold_db = new_thresh
            self.config["vad_threshold"] = new_thresh
            self.config["show_tray_icon"] = tray_icon_var.get()
            self._save_config()
            dialog.destroy()

        btn_save = ctk.CTkButton(dialog, text="Save & Connect", command=_save_settings)
        btn_save.pack(pady=15)

    def hide_to_tray(self):
        self.withdraw()
        if self.config.get("show_tray_icon", False):
            if not self.tray_icon:
                self._create_tray_icon()
        else:
            if self.tray_icon:
                self.tray_icon.stop()
                self.tray_icon = None

    def _create_tray_icon(self):
        import pystray
        image = Image.new('RGB', (64, 64), color=(31, 83, 141))
        d = ImageDraw.Draw(image)
        d.ellipse([16, 16, 48, 48], fill=(0, 255, 102))

        menu = pystray.Menu(
            pystray.MenuItem("Show Baby Monitor", self.show_from_tray),
            pystray.MenuItem("Exit", self.quit_app)
        )
        self.tray_icon = pystray.Icon("BabyMonitor", image, "Baby Monitor", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_from_tray(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None
        self.deiconify()

    def on_window_close(self):
        self.hide_to_tray()

    def quit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        if self.recorder:
            self.recorder.stop()
        if self.ws_client:
            self.ws_client.stop()
        self.destroy()
