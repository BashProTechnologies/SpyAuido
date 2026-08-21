import sys
import os
import logging

logger = logging.getLogger("baby.autostart")

APP_REG_NAME = "BabyMonitorBabyClient"

def set_autostart(enabled: bool) -> bool:
    """
    Enable or disable Windows autostart via HKCU registry.
    """
    if sys.platform != "win32":
        logger.warning("Autostart registry configuration is only supported on Windows.")
        return False

    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            if enabled:
                # Path to current executable or Python script
                if getattr(sys, 'frozen', False):
                    exe_path = f'"{sys.executable}" --autostart'
                else:
                    script_path = os.path.abspath(sys.argv[0])
                    exe_path = f'"{sys.executable}" "{script_path}" --autostart'

                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, exe_path)
                logger.info(f"Autostart enabled in registry: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                    logger.info("Autostart entry removed from registry.")
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        logger.error(f"Failed to modify autostart registry: {e}")
        return False

def is_autostart_enabled() -> bool:
    """Check if autostart registry entry exists."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_REG_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.error(f"Error checking autostart state: {e}")
        return False
