import os
import sys
import logging

# Ensure app package is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.gui import BabyMonitorApp

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    app = BabyMonitorApp(config_path)

    # Always ensure autostart registry is set if enabled in config
    from app.autostart import set_autostart
    if app.config.get("autostart", True):
        set_autostart(True)

    # If launched with --autostart or start_minimized, hide immediately
    if "--autostart" in sys.argv or app.config.get("start_minimized", False):
        app.hide_to_tray()

    app.mainloop()

if __name__ == "__main__":
    main()
