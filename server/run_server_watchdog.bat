@echo off
title SpyAudio Relay Server Watchdog (Bash Pro Tech ^& INTECHA)
echo ========================================================
echo   Starting Crash-Proof Server Watchdog Loop...
echo ========================================================

:loop
echo [%date% %time%] Launching server process...
python app/main.py
echo [%date% %time%] Server process terminated or crashed with errorlevel %errorlevel%.
echo [%date% %time%] Auto-restarting server in 2 seconds...
timeout /t 2 /nobreak >nul
goto loop
