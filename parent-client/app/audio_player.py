import logging
import threading
import numpy as np
import sounddevice as sd
from app.jitter_buffer import JitterBuffer

logger = logging.getLogger("parent.audio_player")


class AudioPlayer:
    """
    Real-time Low-Latency Audio Playback Engine using SoundDevice.
    Plays incoming PCM audio frames from the Baby Monitor.
    """
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frame_duration_ms: int = 20
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(self.sample_rate * (self.frame_duration_ms / 1000.0))  # 320 samples
        self.expected_bytes = self.frame_size * 2  # 640 bytes (int16)

        self.jitter_buffer = JitterBuffer(max_frames=5)  # ~100ms buffer (was 300ms - reduced to fix echo)
        self.volume: float = 0.7
        self.playback_gain: float = 1.5  # gentle boost - increase for louder output
        self.is_muted: bool = False
        self.listen_enabled: bool = True

        self._stream: sd.OutputStream = None
        self._is_running = False
        self._lock = threading.Lock()

        self.current_level: float = 0.0
        self._frames_played = 0
        self._frames_silent = 0

    def start(self):
        """Start sound output playback stream."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True

        try:
            # Use default output device
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='int16',
                blocksize=self.frame_size,
                callback=self._audio_callback,
                latency='low'
            )
            self._stream.start()
            logger.info(f"Audio playback started: {self.sample_rate}Hz, blocksize={self.frame_size}, expected_bytes={self.expected_bytes}")
        except Exception as e:
            logger.error(f"Failed to start audio playback: {e}")
            self._is_running = False
            raise

    def stop(self):
        """Stop sound output stream."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"Error stopping playback: {e}")
            self._stream = None
        logger.info(f"Audio playback stopped. Played={self._frames_played}, Silent={self._frames_silent}")

    def push_pcm_frame(self, pcm_bytes: bytes):
        """Receive incoming raw PCM audio bytes and push to jitter buffer."""
        if self._is_running and self.listen_enabled:
            self.jitter_buffer.push(pcm_bytes)

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        """Callback executed by sounddevice to fill output buffer."""
        if status:
            logger.warning(f"Playback status: {status}")

        pcm_bytes = self.jitter_buffer.pop()

        if not pcm_bytes or self.is_muted or not self.listen_enabled:
            outdata.fill(0)
            self.current_level = 0.0
            self._frames_silent += 1
            return

        # Handle frame size mismatch gracefully
        needed = frames * 2  # int16 = 2 bytes per sample
        if len(pcm_bytes) < needed:
            # Pad with silence
            pcm_bytes = pcm_bytes + b'\x00' * (needed - len(pcm_bytes))
        elif len(pcm_bytes) > needed:
            # Truncate
            pcm_bytes = pcm_bytes[:needed]

        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)

        # 1. Apply Volume & Dynamic Playback Gain Boost (0.5x to 10.0x)
        total_gain = self.volume * getattr(self, 'playback_gain', 3.0)
        samples = samples * total_gain

        # 2. Soft-Clipping Limiter (Prevents sound crackling/distortion even at 10x volume)
        limit_threshold = 28000.0
        over_mask = np.abs(samples) > limit_threshold
        if np.any(over_mask):
            samples[over_mask] = np.sign(samples[over_mask]) * (
                limit_threshold + (32767.0 - limit_threshold) * np.tanh((np.abs(samples[over_mask]) - limit_threshold) / (32767.0 - limit_threshold))
            )

        samples = np.clip(samples, -32768, 32767).astype(np.int16)

        # Calculate live peak level percentage
        rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
        self.current_level = float(np.clip((rms / 32768.0) * 100.0, 0.0, 100.0))

        # Output to audio hardware
        outdata[:, 0] = samples
        self._frames_played += 1
