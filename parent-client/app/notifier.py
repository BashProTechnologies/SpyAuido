import time
import sys
import logging
import threading

logger = logging.getLogger("parent.notifier")

class AlertNotifier:
    """
    Windows Notification & Sound Alert Manager with Cooldown protection.
    """
    def __init__(self, cooldown_sec: float = 10.0):
        self.cooldown_sec = cooldown_sec
        self.last_alert_time: float = 0.0
        self._toaster = None

        if sys.platform == "win32":
            try:
                from win10toast import ToastNotifier
                self._toaster = ToastNotifier()
            except ImportError:
                logger.info("win10toast module not available, falling back to sound alert only.")

    def trigger_baby_sound_alert(self, level: float, message: str = "BABY SOUND DETECTED"):
        """Trigger visual & sound alert if cooldown has passed."""
        now = time.time()
        if (now - self.last_alert_time) < self.cooldown_sec:
            return

        self.last_alert_time = now
        logger.info(f"[ALERT TRIGGERED] {message} (Level: {level:.1f}%)")

        # Sound beep alert
        threading.Thread(target=self._play_beep, daemon=True).start()

        # Toast notification
        if self._toaster and sys.platform == "win32":
            threading.Thread(target=self._show_toast, args=(message, f"Audio level: {level:.1f}%"), daemon=True).start()

    def _play_beep(self):
        try:
            if sys.platform == "win32":
                import winsound
                # Play 2 quick alert beeps
                winsound.Beep(1000, 300)
                winsound.Beep(1500, 300)
        except Exception as e:
            logger.error(f"Error playing alert beep: {e}")

    def _show_toast(self, title: str, msg: str):
        try:
            if self._toaster:
                self._toaster.show_toast(
                    title,
                    msg,
                    duration=5,
                    threaded=True
                )
        except Exception as e:
            logger.error(f"Error displaying toast notification: {e}")
