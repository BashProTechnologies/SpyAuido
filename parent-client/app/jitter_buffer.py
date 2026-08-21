import collections
import threading
import logging

logger = logging.getLogger("parent.jitter_buffer")


class JitterBuffer:
    """
    Thread-safe ring buffer for real-time audio playback.
    Uses deque for O(1) append/pop with automatic overflow handling.
    """
    def __init__(self, max_frames: int = 15):
        self.max_frames = max_frames
        self._buffer = collections.deque(maxlen=max_frames)
        self._lock = threading.Lock()
        self._total_pushed = 0
        self._total_dropped = 0

    def push(self, pcm_bytes: bytes):
        """Push frame. If full, oldest frame is automatically dropped by deque."""
        with self._lock:
            if len(self._buffer) >= self.max_frames:
                self._total_dropped += 1
            self._buffer.append(pcm_bytes)
            self._total_pushed += 1

    def pop(self) -> bytes:
        """Pop next frame for playback. Returns empty bytes if buffer is empty."""
        with self._lock:
            if self._buffer:
                return self._buffer.popleft()
            return b""

    def clear(self):
        """Clear all buffered frames."""
        with self._lock:
            self._buffer.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "buffered": len(self._buffer),
                "total_pushed": self._total_pushed,
                "total_dropped": self._total_dropped
            }
