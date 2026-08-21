import os
import sys
import logging

# Ensure app package is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.gui import ParentDashboardApp

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")
    app = ParentDashboardApp(config_path)
    app.mainloop()

if __name__ == "__main__":
    main()
