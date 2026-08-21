import os
import json
import time
import logging
import threading
import customtkinter as ctk
from PIL import Image, ImageDraw

from app.audio_player import AudioPlayer
from app.ws_client import ParentWebSocketClient
from app.notifier import AlertNotifier

logger = logging.getLogger("parent.gui")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ParentDashboardApp(ctk.CTk):
    def __init__(self, config_path: str):
        super().__init__()

        self.config_path = config_path
        self.config = self._load_config()

        self.title("BABY MONITOR - Parent Receiver Dashboard")
        self.geometry("500x700")
        self.resizable(False, False)

        # Core services
        self.player: AudioPlayer = None
        self.ws_client: ParentWebSocketClient = None
        self.notifier: AlertNotifier = None

        self.baby_online = False
        self.last_latency_ms = 0.0

        self._build_ui()
        self._init_core()

        # Regular UI timer update loop
        self.after(100, self._ui_update_loop)

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self.on_window_close)

    def _load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading parent config: {e}")
        return {}

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving parent config: {e}")

    def _build_ui(self):
        # Header
        self.header_label = ctk.CTkLabel(
            self, text="BABY MONITOR DASHBOARD", font=ctk.CTkFont(size=22, weight="bold")
        )
        self.header_label.pack(pady=15)

        # Main Monitor Card
        self.card_frame = ctk.CTkFrame(self, border_width=1, border_color="#333333")
        self.card_frame.pack(fill="x", padx=20, pady=10)

        # Status Line
        self._add_info_row(self.card_frame, 0, "Status:", "OFFLINE", "#FF3333", "status_val")
        self._add_info_row(self.card_frame, 1, "Microphone:", "Disconnected", "#AAAAAA", "mic_val")
        self._add_info_row(self.card_frame, 2, "Audio:", "IDLE", "#AAAAAA", "audio_val")
        self._add_info_row(self.card_frame, 3, "Latency:", "--- ms", "#AAAAAA", "latency_val")
        self._add_info_row(self.card_frame, 4, "Connection:", "Disconnected", "#AAAAAA", "conn_val")

        # Audio Level Signal Bar
        self.signal_label = ctk.CTkLabel(self.card_frame, text="Live Audio Stream Level:", font=ctk.CTkFont(weight="bold"))
        self.signal_label.pack(anchor="w", padx=15, pady=(10, 2))

        self.signal_bar = ctk.CTkProgressBar(self.card_frame, height=12)
        self.signal_bar.pack(fill="x", padx=15, pady=(0, 15))
        self.signal_bar.set(0.0)

        # Alert Banner
        self.alert_banner = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=14, weight="bold"), text_color="#00FF66"
        )
        self.alert_banner.pack(pady=5)

        # Audio Controls Box
        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.pack(fill="x", padx=20, pady=10)

        # Mute / Listen Buttons
        self.btn_subframe = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.btn_subframe.pack(fill="x", padx=10, pady=10)

        self.mute_btn = ctk.CTkButton(
            self.btn_subframe, text="MUTE", fg_color="#CC0000", command=self._toggle_mute
        )
        self.mute_btn.pack(side="left", expand=True, padx=5)

        self.listen_btn = ctk.CTkButton(
            self.btn_subframe, text="Listen Mode: ON", fg_color="#00AA44", command=self._toggle_listen
        )
        self.listen_btn.pack(side="right", expand=True, padx=5)

        # Volume Slider
        self.vol_label = ctk.CTkLabel(
            self.controls_frame,
            text=f"Volume: {int(self.config.get('volume', 0.7) * 100)}%",
            font=ctk.CTkFont(weight="bold")
        )
        self.vol_label.pack(anchor="w", padx=15, pady=(5, 2))

        self.vol_slider = ctk.CTkSlider(
            self.controls_frame, from_=0.0, to=1.0, command=self._on_volume_change
        )
        self.vol_slider.set(self.config.get("volume", 0.7))
        self.vol_slider.pack(fill="x", padx=15, pady=(0, 10))

        # Microphone Gain Boost (Səs Gücləndirici 1x - 10x)
        current_gain = self.config.get("playback_gain", 4.0)
        self.gain_label = ctk.CTkLabel(
            self.controls_frame,
            text=f"🔊 Microphone Boost (Səs Gücü): {current_gain:.1f}x",
            font=ctk.CTkFont(weight="bold")
        )
        self.gain_label.pack(anchor="w", padx=15, pady=(5, 2))

        self.gain_slider = ctk.CTkSlider(
            self.controls_frame, from_=1.0, to=10.0, number_of_steps=90, command=self._on_gain_change
        )
        self.gain_slider.set(current_gain)
        self.gain_slider.pack(fill="x", padx=15, pady=(0, 15))

        # Switches
        self.vad_alert_switch = ctk.CTkSwitch(
            self, text="Baby Sound Alert & Notification", command=self._toggle_alert_switch
        )
        self.vad_alert_switch.pack(pady=10)
        if self.config.get("voice_detection_alert", True):
            self.vad_alert_switch.select()

        # Action Buttons
        self.bottom_btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_btn_frame.pack(fill="x", padx=20, pady=10)

        self.reconnect_btn = ctk.CTkButton(
            self.bottom_btn_frame, text="Reconnect Now", command=self._force_reconnect
        )
        self.reconnect_btn.pack(side="left", expand=True, padx=5)

        self.settings_btn = ctk.CTkButton(
            self.bottom_btn_frame, text="Settings", fg_color="#333333", command=self._open_settings
        )
        self.settings_btn.pack(side="right", expand=True, padx=5)

    def _add_info_row(self, parent, row_idx, label_text, val_text, val_color, attr_name):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=15, pady=4)

        lbl = ctk.CTkLabel(frame, text=label_text, font=ctk.CTkFont(weight="bold"))
        lbl.pack(side="left")

        val = ctk.CTkLabel(frame, text=val_text, text_color=val_color, font=ctk.CTkFont(weight="bold"))
        val.pack(side="right")

        setattr(self, attr_name, val)

    def _init_core(self):
        self.player = AudioPlayer(
            sample_rate=self.config.get("sample_rate", 16000),
            channels=self.config.get("channels", 1)
        )
        self.player.volume = self.config.get("volume", 0.7)
        self.player.playback_gain = self.config.get("playback_gain", 1.5)
        self.player.is_muted = self.config.get("is_muted", False)
        self.player.listen_enabled = self.config.get("listen_enabled", True)

        self.notifier = AlertNotifier(cooldown_sec=self.config.get("alert_cooldown_sec", 10.0))

        self.ws_client = ParentWebSocketClient(
            server_url=self.config.get("server_url", "ws://127.0.0.1:8000/ws/stream"),
            device_id=self.config.get("device_id", "parent_room_pc_01"),
            device_token=self.config.get("device_token", "secure_token_parent_room_43210"),
            on_audio_frame=self._handle_audio_frame,
            on_status_update=self._handle_status_update,
            on_latency_update=self._handle_latency_update
        )

        self.player.start()
        self.ws_client.start()

    def _handle_audio_frame(self, pcm_bytes: bytes):
        if self.player:
            self.player.push_pcm_frame(pcm_bytes)

    def _handle_status_update(self, event: dict):
        def _update():
            evt_type = event.get("event")
            if evt_type == "connection_state":
                state = event.get("state")
                if state == "CONNECTED":
                    self.conn_val.configure(text="Excellent", text_color="#00FF66")
                elif state == "CONNECTING":
                    self.conn_val.configure(text="Connecting...", text_color="#FFCC00")
                else:
                    self.conn_val.configure(text="Disconnected", text_color="#FF3333")
                    self.status_val.configure(text="OFFLINE", text_color="#FF3333")
                    self.mic_val.configure(text="Disconnected", text_color="#AAAAAA")
                    self.audio_val.configure(text="IDLE", text_color="#AAAAAA")

            elif evt_type == "baby_status":
                self.baby_online = event.get("baby_online", False)
                if self.baby_online:
                    self.status_val.configure(text="ONLINE", text_color="#00FF66")
                    self.mic_val.configure(text="Connected", text_color="#00FF66")
                    self.audio_val.configure(text="RECEIVING", text_color="#00FF66")
                else:
                    self.status_val.configure(text="BABY PC OFFLINE", text_color="#FF9900")
                    self.mic_val.configure(text="Disconnected", text_color="#AAAAAA")
                    self.audio_val.configure(text="IDLE", text_color="#AAAAAA")

        self.after(0, _update)

    def _handle_latency_update(self, rtt_ms: float):
        self.last_latency_ms = rtt_ms
        def _update():
            self.latency_val.configure(text=f"{int(rtt_ms)} ms", text_color="#00FF66" if rtt_ms < 250 else "#FFCC00")
        self.after(0, _update)

    def _ui_update_loop(self):
        if self.player:
            level = self.player.current_level
            self.signal_bar.set(level / 100.0)

            # Trigger alert if sound level exceeds threshold
            alert_threshold = self.config.get("alert_threshold", 40.0)
            if level >= alert_threshold and self.config.get("voice_detection_alert", True):
                self.alert_banner.configure(text=f"⚠️ BABY SOUND DETECTED ({level:.1f}%)", text_color="#FF3333")
                self.notifier.trigger_baby_sound_alert(level)
            elif level < 5.0:
                self.alert_banner.configure(text="")

        self.after(100, self._ui_update_loop)

    def _toggle_mute(self):
        self.player.is_muted = not self.player.is_muted
        self.config["is_muted"] = self.player.is_muted
        if self.player.is_muted:
            self.mute_btn.configure(text="UNMUTE", fg_color="#555555")
        else:
            self.mute_btn.configure(text="MUTE", fg_color="#CC0000")
        self._save_config()

    def _toggle_listen(self):
        self.player.listen_enabled = not self.player.listen_enabled
        self.config["listen_enabled"] = self.player.listen_enabled
        if self.player.listen_enabled:
            self.listen_btn.configure(text="Listen Mode: ON", fg_color="#00AA44")
        else:
            self.listen_btn.configure(text="Listen Mode: OFF", fg_color="#555555")
        self._save_config()

    def _on_volume_change(self, val: float):
        self.player.volume = val
        self.vol_label.configure(text=f"Volume: {int(val * 100)}%")
        self.config["volume"] = val
        self._save_config()

    def _on_gain_change(self, val: float):
        if self.player:
            self.player.playback_gain = val
        self.gain_label.configure(text=f"🔊 Microphone Boost (Səs Gücü): {val:.1f}x")
        self.config["playback_gain"] = val
        self._save_config()

    def _toggle_alert_switch(self):
        is_on = bool(self.vad_alert_switch.get())
        self.config["voice_detection_alert"] = is_on
        self._save_config()

    def _force_reconnect(self):
        if self.ws_client:
            self.ws_client.stop()
            self.ws_client.start()

    def _open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Parent Monitor Settings")
        dialog.geometry("400x320")
        dialog.grab_set()

        lbl_url = ctk.CTkLabel(dialog, text="Server WebSocket URL:")
        lbl_url.pack(anchor="w", padx=20, pady=(15, 2))

        entry_url = ctk.CTkEntry(dialog, width=350)
        entry_url.insert(0, self.config.get("server_url", "ws://127.0.0.1:8000/ws/stream"))
        entry_url.pack(padx=20, pady=5)

        lbl_thresh = ctk.CTkLabel(dialog, text="Alert Volume Threshold (%):")
        lbl_thresh.pack(anchor="w", padx=20, pady=(10, 2))

        slider_thresh = ctk.CTkSlider(dialog, from_=10.0, to=90.0)
        slider_thresh.set(self.config.get("alert_threshold", 40.0))
        slider_thresh.pack(fill="x", padx=20, pady=5)

        lbl_gain = ctk.CTkLabel(dialog, text=f"🔊 Playback Gain (Səs gücü): {self.config.get('playback_gain', 1.5):.1f}x")
        lbl_gain.pack(anchor="w", padx=20, pady=(10, 2))

        slider_gain = ctk.CTkSlider(dialog, from_=0.5, to=4.0, number_of_steps=35)
        slider_gain.set(self.config.get("playback_gain", 1.5))
        slider_gain.pack(fill="x", padx=20, pady=(0, 5))

        def _on_gain_slide(val):
            lbl_gain.configure(text=f"🔊 Playback Gain (Səs gücü): {val:.1f}x")

        slider_gain.configure(command=_on_gain_slide)

        def _save_dialog():
            self.config["server_url"] = entry_url.get()
            self.config["alert_threshold"] = slider_thresh.get()
            gain_val = slider_gain.get()
            self.config["playback_gain"] = gain_val
            if self.player:
                self.player.playback_gain = gain_val
            self._save_config()
            dialog.destroy()
            self._force_reconnect()

        btn_save = ctk.CTkButton(dialog, text="Save & Reconnect", command=_save_dialog)
        btn_save.pack(pady=20)

    def on_window_close(self):
        if self.player:
            self.player.stop()
        if self.ws_client:
            self.ws_client.stop()
        self.destroy()
