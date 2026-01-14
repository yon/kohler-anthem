# Kohler Anthem - Development

Tools for reverse engineering and API discovery. **Not for general use.**

For credential extraction (setting up the library), see [docs/CREDENTIAL_EXTRACTION.md](../docs/CREDENTIAL_EXTRACTION.md).

## Directory Structure

```
dev/
├── docs/          # Reverse engineering notes
│   ├── MY_DEVICE.md
│   ├── SESSION_STATE.md
│   └── VALVE_PROTOCOL.md
├── output/        # Capture logs (gitignored)
├── scripts/       # Development scripts
│   ├── capture_kohler_traffic.py   # mitmproxy addon for HTTP capture
│   ├── comprehensive_apk_analysis.py
│   ├── discover_api.py
│   ├── extract_apk_endpoints.py
│   ├── frida_capture_hooks.js      # Frida hooks for traffic capture
│   ├── frida_dev_capture.py        # Launch app with capture hooks
│   ├── frida_proxy_inject.js
│   ├── test_api.py
│   └── test_quick_dirty.py
└── Makefile       # Dev-only make targets
```

## Quick Start

```bash
# Traffic capture with Frida (requires Genymotion + frida-server)
make capture

# View latest capture log
make latest
```

## Prerequisites

1. **Genymotion** emulator with Android 10+
2. **frida-server** running on emulator (see `make frida-start`)
3. **Kohler Konnect** APK installed

## Make Targets

| Target | Description |
|--------|-------------|
| `capture` | Launch app with Frida hooks (captures HTTP, MQTT, IoT) |
| `frida-start` | Start frida-server on emulator |
| `frida-status` | Check frida-server status |
| `frida-stop` | Stop frida-server on emulator |
| `install-cert` | Install mitmproxy CA cert on emulator |
| `latest` | View latest capture log |
| `logs` | List recent capture logs |
| `mitmproxy` | Start mitmproxy for HTTP traffic capture |
| `proxy-off` | Disable proxy on emulator |
| `proxy-on` | Configure emulator to use proxy |

## Captured Traffic

The Frida capture hooks log:
- `[HTTP]` - REST API requests (OkHttp)
- `[IOT HUB]` - IoT Hub connection strings
- `[IOT MESSAGE]` - Messages sent to IoT Hub
- `[MQTT]` - MQTT connections and publishes
- `[GSON]` - Command objects being serialized
- `[RETROFIT]` - Request bodies

## Tips

- Clear app data between captures for clean sessions:
  ```bash
  adb shell pm clear com.kohler.hermoth
  ```
- The bypass script (`scripts/frida_bypass.js`) is shared with the credential extraction workflow
- Only the capture hooks are dev-specific
