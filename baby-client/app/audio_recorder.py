import logging
import threading
import time
from typing import Callable, Optional, List, Dict
import numpy as np
import sounddevice as sd
from app.vad import VoiceActivityDetector
from scipy import signal as scipy_signal

logger = logging.getLogger("baby.audio_recorder")

class AudioRecorder:
    """
    Real-time Microphone Input Capture & Audio Processing Engine.
    Captures 16kHz 16-bit Mono PCM audio in 20ms frames.
    """
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_duration_ms: int = 20,
        device_index: Optional[int] = None,
        on_audio_frame: Optional[Callable[[bytes, float, bool], None]] = None
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(self.sample_rate * (self.frame_duration_ms / 1000.0))  # 320 samples
        self.gain_factor = 2.0  # capture gain (1.0 = no boost, 2.0 = moderate boost)
        self.device_index = device_index
        self.on_audio_frame = on_audio_frame  # callback(pcm_bytes, level_percentage, is_vad_active)

        self.vad = VoiceActivityDetector()
        self.mode = "continuous"  # "continuous" or "vad"
        
        self._stream: Optional[sd.InputStream] = None
        self._is_running = False
        self._lock = threading.Lock()

    @staticmethod
    def get_input_devices() -> List[Dict]:
        """List available microphone input devices."""
        devices = []
        try:
            devs = sd.query_devices()
            for idx, dev in enumerate(devs):
                if dev.get('max_input_channels', 0) > 0:
                    devices.append({
                        'index': idx,
                        'name': dev['name'],
                        'channels': dev['max_input_channels'],
                        'default_samplerate': dev['default_samplerate']
                    })
        except Exception as e:
            logger.error(f"Error querying audio input devices: {e}")
        return devices

    def start(self) -> bool:
        """
        Start microphone input stream safely.
        Returns True if successful, False if microphone is unavailable.
        """
        with self._lock:
            if self._is_running:
                return True
            self._is_running = True

        # If device_index is None, pick default host input device or first active input device
        target_device = self.device_index
        if target_device is None:
            try:
                default_in = sd.query_devices(kind='input')
                target_device = default_in['index']
                logger.info(f"Selected Windows Default Input Device: [{target_device}] {default_in['name']}")
            except Exception:
                available_devices = self.get_input_devices()
                if available_devices:
                    target_device = available_devices[0]['index']
                    logger.info(f"Auto-selected first valid input device: index={target_device}")

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='int16',
                blocksize=self.frame_size,
                device=target_device,
                callback=self._audio_callback
            )
            self._stream.start()
            logger.info(f"Microphone recording started on device index={target_device}")
            return True
        except Exception as e:
            logger.warning(f"Could not open microphone stream (device={target_device}): {e}")
            self._is_running = False
            self._stream = None
            return False

    def stop(self):
        """Stop microphone input stream."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            self._stream = None
        logger.info("Microphone recording stopped.")

    def set_device(self, device_index: Optional[int]) -> bool:
        """Dynamically switch microphone device."""
        was_running = self._is_running
        if was_running:
            self.stop()
        self.device_index = device_index
        if was_running:
            return self.start()
        return True

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """Callback executed by sounddevice for each 20ms block."""
        if status:
            logger.warning(f"Audio stream status warning: {status}")

        if not self._is_running:
            return

        # --- High Quality Audio Processing Pipeline ---
        samples = indata.astype(np.float32)

        # 1. Soft Dynamic Gain Boost (Clean amplification without harsh clipping)
        gain = getattr(self, 'gain_factor', 4.0)
        samples = samples * gain

        # 2. Dynamic Limiter / Soft Clipper (Prevents distortion while keeping max loudness)
        # Apply smooth tanh limiting for peaks exceeding 80% range
        max_val = 32000.0
        over_mask = np.abs(samples) > (max_val * 0.8)
        if np.any(over_mask):
            samples[over_mask] = np.sign(samples[over_mask]) * (
                max_val * 0.8 + (max_val * 0.2) * np.tanh((np.abs(samples[over_mask]) - max_val * 0.8) / (max_val * 0.2))
            )

        samples_out = np.clip(samples, -32768, 32767).astype(np.int16)
        pcm_data = samples_out.tobytes()

        is_vad_active, level = self.vad.process_frame(pcm_data)

        # Decide whether to transmit frame based on mode
        should_transmit = True
        if self.mode == "vad" and not is_vad_active:
            should_transmit = False

        if self.on_audio_frame and should_transmit:
            self.on_audio_frame(pcm_data, level, is_vad_active)
