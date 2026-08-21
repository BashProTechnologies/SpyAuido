# Secure Real-Time Baby Monitor System

A self-hosted, privacy-first, low-latency Baby Monitor system built with Python, WebSocket over TLS, and modern CustomTkinter GUIs. Designed to connect two Windows PCs across different ISPs using a Central VPS relay.

---

## Features
- **Ultra Low Latency**: 120 - 200 ms end-to-end latency using Opus/PCM over persistent TLS WebSocket.
- **Privacy-First**: Zero audio persistence on VPS disk. Pure in-memory streaming.
- **No Port Forwarding**: Works seamlessly across different ISPs via outbound TLS (Port 443).
- **Voice Activated Streaming (VAD)**: Intelligent energy detection, hysteresis, and sound duration filtering.
- **Auto Reconnect**: Exponential backoff reconnects automatically during Wi-Fi or server dropouts.
- **Windows Autostart & Stealth Tray**: Runs on boot, minimizes to system tray.
- **Security Hardened**: Token authentication, constant-time verification, IP rate limiting, masked tokens.

---

## Project Structure
```
baby-monitor/
├── server/               # FastAPI VPS WebSocket Relay Server
├── baby-client/          # Baby Room Windows Client App
├── parent-client/        # Parent Receiver Windows Dashboard App
├── deployment/           # Docker Compose & Nginx configuration
└── docs/                 # Deployment guide & 14-step Test Plan
```

---

## Quick Start (Development Mode)

### 1. Start VPS Server locally
```bash
cd server
pip install -r requirements.txt
python app/main.py
```

### 2. Start Baby Client
```bash
cd baby-client
pip install -r requirements.txt
python app/main.py
```

### 3. Start Parent Client
```bash
cd parent-client
pip install -r requirements.txt
python app/main.py
```

---

## Building Executables (.exe for Windows)

To compile standalone Windows executables with PyInstaller:

### Build Baby Client:
```bash
cd baby-client
pyinstaller baby_client.spec
```
Output: `baby-client/dist/BabyMonitor-Baby.exe`

### Build Parent Client:
```bash
cd parent-client
pyinstaller parent_client.spec
```
Output: `parent-client/dist/BabyMonitor-Parent.exe`

---

## Deployment & Production
Refer to [docs/VPS_DEPLOYMENT.md](file:///c:/Users/Ubash/OneDrive/Рабочий%20stol/SpyAudio/docs/VPS_DEPLOYMENT.md) for full VPS deployment instructions.
Refer to [docs/TESTING_PLAN.md](file:///c:/Users/Ubash/OneDrive/Рабочий%20stol/SpyAudio/docs/TESTING_PLAN.md) for verification procedures.
