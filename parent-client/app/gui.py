import os
import json
import time
import logging
import threading
from typing import List, Dict, Optional
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

        self.title("Bash Pro Tech & INTECHA - Central Audio Monitoring Dashboard")
        self.geometry("520x760")
        self.resizable(False, False)

        # Core services
        self.player: Optional[AudioPlayer] = None
        self.ws_client: Optional[ParentWebSocketClient] = None
        self.notifier: Optional[AlertNotifier] = None

        # Multi-Agent State
        self.known_agents: List[Dict] = []
        self.selected_agent_id: Optional[str] = None
        self.selected_agent_name: str = "Heç bir agent seçilməyib"
        self.selected_agent_online: bool = False
        self.last_latency_ms: float = 0.0

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
        # 1. Branding Header (Bash Pro Tech & INTECHA)
        self.header_frame = ctk.CTkFrame(self, fg_color="#1a1c23", corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 8))

        self.brand_title = ctk.CTkLabel(
            self.header_frame,
            text="Bash Pro Tech & INTECHA",
            font=ctk.CTkFont(family="Arial", size=22, weight="bold"),
            text_color="#38bdf8"
        )
        self.brand_title.pack(pady=(8, 2))

        self.brand_subtitle = ctk.CTkLabel(
            self.header_frame,
            text="Central Multi-Agent Audio Monitoring Platform",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        self.brand_subtitle.pack(pady=(0, 8))

        # 2. Agent Selector Frame (Dropdown as in user's design)
        self.agent_select_frame = ctk.CTkFrame(self, border_width=1, border_color="#334155")
        self.agent_select_frame.pack(fill="x", padx=15, pady=6)

        self.agent_label = ctk.CTkLabel(
            self.agent_select_frame,
            text="📡 Monitorinq Olunacaq Agent (Cihaz):",
            font=ctk.CTkFont(weight="bold", size=13)
        )
        self.agent_label.pack(anchor="w", padx=15, pady=(8, 4))

        self.agent_dropdown = ctk.CTkOptionMenu(
            self.agent_select_frame,
            values=["Gözlənilir: Agentlər axtarılır..."],
            command=self._on_agent_selected,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.agent_dropdown.pack(fill="x", padx=15, pady=(0, 10))

        # 3. Main Monitor Info Card
        self.card_frame = ctk.CTkFrame(self, border_width=1, border_color="#334155")
        self.card_frame.pack(fill="x", padx=15, pady=6)

        self._add_info_row(self.card_frame, "Aktiv Agent:", "Seçilməyib", "#94a3b8", "agent_val")
        self._add_info_row(self.card_frame, "Agent Statusu:", "OFFLINE", "#FF3333", "status_val")
        self._add_info_row(self.card_frame, "Səs Yayımı (Audio):", "IDLE", "#94a3b8", "audio_val")
        self._add_info_row(self.card_frame, "Server Gecikməsi (Ping):", "--- ms", "#94a3b8", "latency_val")
        self._add_info_row(self.card_frame, "Server Əlaqəsi:", "Qoşulur...", "#f59e0b", "conn_val")

        # Audio Level Signal Bar
        self.signal_label = ctk.CTkLabel(
            self.card_frame,
            text="Canlı Mikrofon Enerji Səviyyəsi (Live Level):",
            font=ctk.CTkFont(weight="bold", size=12)
        )
        self.signal_label.pack(anchor="w", padx=15, pady=(10, 2))

        self.signal_bar = ctk.CTkProgressBar(self.card_frame, height=14)
        self.signal_bar.pack(fill="x", padx=15, pady=(0, 12))
        self.signal_bar.set(0.0)

        # Alert Banner
        self.alert_banner = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=13, weight="bold"), text_color="#22c55e"
        )
        self.alert_banner.pack(pady=2)

        # 4. Audio Controls Frame
        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.pack(fill="x", padx=15, pady=6)

        # Mute / Listen Mode Buttons
        self.btn_subframe = ctk.CTkFrame(self.controls_frame, fg_color="transparent")
        self.btn_subframe.pack(fill="x", padx=10, pady=(8, 4))

        self.mute_btn = ctk.CTkButton(
            self.btn_subframe, text="MUTE", fg_color="#CC0000", command=self._toggle_mute, height=32
        )
        self.mute_btn.pack(side="left", expand=True, padx=5)

        self.listen_btn = ctk.CTkButton(
            self.btn_subframe, text="Listen Mode: ON", fg_color="#00AA44", command=self._toggle_listen, height=32
        )
        self.listen_btn.pack(side="right", expand=True, padx=5)

        # Master Volume Slider
        self.vol_label = ctk.CTkLabel(
            self.controls_frame,
            text=f"Əsas Səs Səviyyəsi (Volume): {int(self.config.get('volume', 0.7) * 100)}%",
            font=ctk.CTkFont(weight="bold")
        )
        self.vol_label.pack(anchor="w", padx=15, pady=(4, 2))

        self.vol_slider = ctk.CTkSlider(
            self.controls_frame, from_=0.0, to=1.0, command=self._on_volume_change
        )
        self.vol_slider.set(self.config.get("volume", 0.7))
        self.vol_slider.pack(fill="x", padx=15, pady=(0, 8))

        # Microphone Gain Boost (1.0x - 10.0x)
        current_gain = self.config.get("playback_gain", 4.0)
        self.gain_label = ctk.CTkLabel(
            self.controls_frame,
            text=f"🔊 Mikrofon Gücləndirici (Boost): {current_gain:.1f}x",
            font=ctk.CTkFont(weight="bold")
        )
        self.gain_label.pack(anchor="w", padx=15, pady=(2, 2))

        self.gain_slider = ctk.CTkSlider(
            self.controls_frame, from_=1.0, to=10.0, number_of_steps=90, command=self._on_gain_change
        )
        self.gain_slider.set(current_gain)
        self.gain_slider.pack(fill="x", padx=15, pady=(0, 10))

        # Alert switch
        self.vad_alert_switch = ctk.CTkSwitch(
            self, text="Səs Bildirişi & Xəbərdarlıq (Sound Alerts)", command=self._toggle_alert_switch
        )
        self.vad_alert_switch.pack(pady=4)
        if self.config.get("voice_detection_alert", True):
            self.vad_alert_switch.select()

        # 5. Bottom Navigation & Action Buttons
        self.bottom_btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_btn_frame.pack(fill="x", padx=15, pady=8)

        self.reconnect_btn = ctk.CTkButton(
            self.bottom_btn_frame, text="Yenidən Qoşul (Reconnect)", command=self._force_reconnect
        )
        self.reconnect_btn.pack(side="left", expand=True, padx=5)

        self.settings_btn = ctk.CTkButton(
            self.bottom_btn_frame, text="Tənzimləmələr (Settings)", fg_color="#334155", command=self._open_settings
        )
        self.settings_btn.pack(side="right", expand=True, padx=5)

    def _add_info_row(self, parent, label_text, val_text, val_color, attr_name):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=15, pady=3)

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
        self.player.playback_gain = self.config.get("playback_gain", 4.0)
        self.player.is_muted = self.config.get("is_muted", False)
        self.player.listen_enabled = self.config.get("listen_enabled", True)

        self.notifier = AlertNotifier(cooldown_sec=self.config.get("alert_cooldown_sec", 10.0))

        self.ws_client = ParentWebSocketClient(
            server_url=self.config.get("server_url", "ws://46.32.163.90:8000/ws/stream"),
            device_id=self.config.get("device_id", "parent_room_pc_01"),
            device_token=self.config.get("device_token", "secure_token_parent_room_43210"),
            on_audio_frame=self._handle_audio_frame,
            on_status_update=self._handle_status_update,
            on_agent_list_update=self._handle_agent_list_update,
            on_latency_update=self._handle_latency_update
        )

        self.player.start()
        self.ws_client.start()

    def _handle_audio_frame(self, pcm_bytes: bytes):
        if self.player:
            self.player.push_pcm_frame(pcm_bytes)

    def _handle_agent_list_update(self, agents: List[Dict]):
        """Called when server sends updated agent roster."""
        def _update():
            self.known_agents = agents
            dropdown_values = []
            agent_map = {}

            if not agents:
                dropdown_values = ["Qoşulu agent yoxdur"]
            else:
                for a in agents:
                    dev_id = a.get("device_id")
                    dev_name = a.get("device_name") or dev_id
                    is_online = a.get("is_online", False)
                    status_icon = "🟢" if is_online else "🔴"
                    display_text = f"{status_icon} [{dev_name}] (ID: {dev_id})"
                    dropdown_values.append(display_text)
                    agent_map[display_text] = a

            self._agent_display_map = agent_map
            self.agent_dropdown.configure(values=dropdown_values)

            # If no agent selected yet, auto-select first online agent
            if not self.selected_agent_id and agents:
                # Prioritize first online agent
                first_online = next((a for a in agents if a.get("is_online")), agents[0])
                self._select_agent_internal(first_online)
            elif self.selected_agent_id:
                # Update current selected agent's status
                curr = next((a for a in agents if a.get("device_id") == self.selected_agent_id), None)
                if curr:
                    self._update_selected_agent_display(curr)

        self.after(0, _update)

    def _on_agent_selected(self, choice_text: str):
        agent_info = getattr(self, "_agent_display_map", {}).get(choice_text)
        if agent_info:
            self._select_agent_internal(agent_info)

    def _select_agent_internal(self, agent_info: Dict):
        dev_id = agent_info.get("device_id")
        dev_name = agent_info.get("device_name") or dev_id
        self.selected_agent_id = dev_id
        self.selected_agent_name = dev_name

        # Command server to route audio from this agent
        if self.ws_client:
            self.ws_client.select_agent(dev_id)

        # Clear audio player buffer to prevent mixing old audio
        if self.player:
            self.player.jitter_buffer.clear()

        # Update dropdown selected string
        is_online = agent_info.get("is_online", False)
        status_icon = "🟢" if is_online else "🔴"
        display_text = f"{status_icon} [{dev_name}] (ID: {dev_id})"
        self.agent_dropdown.set(display_text)

        self._update_selected_agent_display(agent_info)

    def _update_selected_agent_display(self, agent_info: Dict):
        dev_id = agent_info.get("device_id")
        dev_name = agent_info.get("device_name") or dev_id
        is_online = agent_info.get("is_online", False)
        self.selected_agent_online = is_online

        self.agent_val.configure(text=f"{dev_name} ({dev_id})", text_color="#38bdf8")
        if is_online:
            self.status_val.configure(text="ONLINE (🟢)", text_color="#22c55e")
            self.audio_val.configure(text="RECEIVING (CANLI)", text_color="#22c55e")
        else:
            self.status_val.configure(text="OFFLINE (🔴)", text_color="#ef4444")
            self.audio_val.configure(text="IDLE (SƏSSİZ)", text_color="#94a3b8")

    def _handle_status_update(self, event: dict):
        def _update():
            evt_type = event.get("event")
            if evt_type == "connection_state":
                state = event.get("state")
                if state == "CONNECTED":
                    self.conn_val.configure(text="Qoşulub (Əla)", text_color="#22c55e")
                elif state == "CONNECTING":
                    self.conn_val.configure(text="Qoşulur...", text_color="#f59e0b")
                else:
                    self.conn_val.configure(text="Kəsildi (Disconnected)", text_color="#ef4444")
                    self.audio_val.configure(text="IDLE", text_color="#94a3b8")
        self.after(0, _update)

    def _handle_latency_update(self, rtt_ms: float):
        self.last_latency_ms = rtt_ms
        def _update():
            self.latency_val.configure(
                text=f"{int(rtt_ms)} ms",
                text_color="#22c55e" if rtt_ms < 250 else "#f59e0b"
            )
        self.after(0, _update)

    def _ui_update_loop(self):
        if self.player:
            level = self.player.current_level
            self.signal_bar.set(level / 100.0)

            alert_threshold = self.config.get("alert_threshold", 40.0)
            if level >= alert_threshold and self.config.get("voice_detection_alert", True):
                self.alert_banner.configure(
                    text=f"⚠️ SƏS AŞKARLANDI [{self.selected_agent_name}] ({level:.1f}%)",
                    text_color="#ef4444"
                )
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
        self.vol_label.configure(text=f"Əsas Səs Səviyyəsi (Volume): {int(val * 100)}%")
        self.config["volume"] = val
        self._save_config()

    def _on_gain_change(self, val: float):
        if self.player:
            self.player.playback_gain = val
        self.gain_label.configure(text=f"🔊 Mikrofon Gücləndirici (Boost): {val:.1f}x")
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
        dialog.title("Bash Pro Tech & INTECHA - Settings")
        dialog.geometry("420x360")
        dialog.grab_set()

        lbl_url = ctk.CTkLabel(dialog, text="Server WebSocket URL:")
        lbl_url.pack(anchor="w", padx=20, pady=(15, 2))

        entry_url = ctk.CTkEntry(dialog, width=370)
        entry_url.insert(0, self.config.get("server_url", "ws://46.32.163.90:8000/ws/stream"))
        entry_url.pack(padx=20, pady=5)

        lbl_thresh = ctk.CTkLabel(dialog, text="Səs Həssaslıq Xəbərdarlığı (%):")
        lbl_thresh.pack(anchor="w", padx=20, pady=(10, 2))

        slider_thresh = ctk.CTkSlider(dialog, from_=10.0, to=90.0)
        slider_thresh.set(self.config.get("alert_threshold", 40.0))
        slider_thresh.pack(fill="x", padx=20, pady=5)

        lbl_gain = ctk.CTkLabel(dialog, text=f"🔊 Playback Gain Boost: {self.config.get('playback_gain', 4.0):.1f}x")
        lbl_gain.pack(anchor="w", padx=20, pady=(10, 2))

        slider_gain = ctk.CTkSlider(dialog, from_=1.0, to=10.0, number_of_steps=90)
        slider_gain.set(self.config.get("playback_gain", 4.0))
        slider_gain.pack(fill="x", padx=20, pady=(0, 5))

        def _on_gain_slide(val):
            lbl_gain.configure(text=f"🔊 Playback Gain Boost: {val:.1f}x")

        slider_gain.configure(command=_on_gain_slide)

        def _save_dialog():
            self.config["server_url"] = entry_url.get().strip()
            self.config["alert_threshold"] = slider_thresh.get()
            gain_val = slider_gain.get()
            self.config["playback_gain"] = gain_val
            if self.player:
                self.player.playback_gain = gain_val
            self._save_config()
            dialog.destroy()
            self._force_reconnect()

        btn_save = ctk.CTkButton(dialog, text="Yadda Saxla & Yenidən Qoşul", command=_save_dialog)
        btn_save.pack(pady=20)

    def on_window_close(self):
        if self.player:
            self.player.stop()
        if self.ws_client:
            self.ws_client.stop()
        self.destroy()
