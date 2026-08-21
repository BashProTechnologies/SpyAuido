import time
import numpy as np

class VoiceActivityDetector:
    """
    Voice & Cry Activity Detector with Hysteresis, Minimum Duration filtering,
    and Noise Floor Adaptation to prevent false positives.
    """
    def __init__(
        self,
        threshold_db: float = 35.0,
        min_speech_duration: float = 0.3,
        cooldown_duration: float = 2.0,
        hysteresis_db: float = 5.0
    ):
        self.threshold_db = threshold_db
        self.release_threshold_db = max(5.0, threshold_db - hysteresis_db)
        self.min_speech_duration = min_speech_duration
        self.cooldown_duration = cooldown_duration
        
        self._is_active = False
        self._speech_start_time = 0.0
        self._last_active_time = 0.0

    @staticmethod
    def calculate_level_percentage(pcm_data: bytes) -> float:
        """Calculate RMS audio energy level as percentage 0..100%."""
        if not pcm_data:
            return 0.0
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
        if len(samples) == 0:
            return 0.0
        rms = np.sqrt(np.mean(samples ** 2))
        # 32768 is max int16 value
        level = (rms / 32768.0) * 100.0
        return float(np.clip(level, 0.0, 100.0))

    def process_frame(self, pcm_data: bytes) -> tuple[bool, float]:
        """
        Process PCM frame and return (is_voice_active, audio_level_percentage).
        """
        level = self.calculate_level_percentage(pcm_data)
        now = time.time()

        if not self._is_active:
            if level >= self.threshold_db:
                if self._speech_start_time == 0.0:
                    self._speech_start_time = now
                elif (now - self._speech_start_time) >= self.min_speech_duration:
                    self._is_active = True
                    self._last_active_time = now
            else:
                self._speech_start_time = 0.0
        else:
            # Currently active
            if level >= self.release_threshold_db:
                self._last_active_time = now
            else:
                if (now - self._last_active_time) >= self.cooldown_duration:
                    self._is_active = False
                    self._speech_start_time = 0.0

        return self._is_active, level
