# Comprehensive 14-Step Test Plan

Run these test cases to verify the end-to-end functionality, low latency, security, and resilience of the Baby Monitor system.

---

### Test 1: Baby Client -> Server Connection
- **Action**: Launch `BabyMonitor-Baby.exe` on Baby PC.
- **Expected Result**: Status changes to "STREAMING". Server logs show `Baby Client connected: baby_room_pc_01`.

### Test 2: Parent Client -> Server Connection
- **Action**: Launch `BabyMonitor-Parent.exe` on Parent PC.
- **Expected Result**: Status changes to "CONNECTED". Latency indicator displays RTT (e.g. 120 ms).

### Test 3: End-to-End Real-Time Audio Streaming
- **Action**: Speak or play audio in front of Baby PC microphone.
- **Expected Result**: Parent PC hears audio in real-time with ~120-200 ms delay. Signal bar pulses.

### Test 4: Internet Disconnect & Reconnect Test
- **Action**: Disable Wi-Fi / unplug Ethernet on Baby PC for 15 seconds, then reconnect.
- **Expected Result**: Baby Client status changes to "OFFLINE". Exponential backoff triggers retries. On reconnect, status automatically restores to "STREAMING" without user intervention.

### Test 5: Central VPS Restart Test
- **Action**: Execute `docker compose restart` on VPS.
- **Expected Result**: Both clients detect WebSocket disconnect and automatically reconnect within 5 seconds once VPS is back up.

### Test 6: Baby PC Reboot Test
- **Action**: Reboot Baby PC Windows OS.
- **Expected Result**: On Windows startup, Baby Client autostarts in background, connects to VPS, and starts streaming automatically.

### Test 7: Parent PC Reboot Test
- **Action**: Reboot Parent PC Windows OS.
- **Expected Result**: Parent Client connects to VPS upon opening, detects Baby PC online status, and resumes listening.

### Test 8: Wrong Authentication Test
- **Action**: Modify `device_token` in `config.json` to an invalid string.
- **Expected Result**: Server rejects WebSocket handshake (HTTP 401 / WS 4001). IP rate limiter increments failure count.

### Test 9: High Packet Loss Simulation
- **Action**: Simulate 10% packet loss using network throttling tools.
- **Expected Result**: Jitter buffer drops delayed frames to maintain live speed. Audio does not accumulate delay.

### Test 10: High Latency Simulation
- **Action**: Add 300 ms artificial delay to network link.
- **Expected Result**: Parent dashboard displays latency warning (e.g. "320 ms", yellow indicator). Audio remains clear.

### Test 11: Microphone Disconnect Test
- **Action**: Unplug USB microphone from Baby PC.
- **Expected Result**: Recorder logs warning. UI shows microphone disconnected error gracefully.

### Test 12: Microphone Reconnect Test
- **Action**: Re-plug USB microphone into Baby PC.
- **Expected Result**: Device selection menu picks default device and resumes recording without crash.

### Test 13: Voice Activation (VAD) Mode Test
- **Action**: Enable "Voice Activated Streaming" in Baby Client. Keep room silent, then make sound.
- **Expected Result**: During silence, 0 audio bytes sent. When sound occurs, stream activates instantly.

### Test 14: Unauthorized Multiple Clients Attempt
- **Action**: Attempt to connect an unknown client with invalid device ID.
- **Expected Result**: Connection immediately dropped, recorded in security logs, zero audio data leaked.
