# Kohler Anthem - Development

Tools and documentation for reverse engineering and developing the Kohler Anthem API.

## Directory Structure

```
dev/
├── apk/           # APK files (gitignored)
├── output/        # Capture logs (gitignored)
├── docs/          # Reverse engineering notes
│   ├── MY_DEVICE.md
│   ├── SESSION_STATE.md
│   └── VALVE_PROTOCOL.md
├── scripts/       # Development scripts
│   ├── frida_*.js/py   # Frida bypass and capture
│   ├── capture_*.py    # Traffic capture
│   ├── extract_*.py    # APK analysis
│   └── test_*.py       # API testing
└── Makefile       # Dev make targets
```

## Quick Start

```bash
# Start capture session (requires Genymotion + frida-server)
make capture

# View latest capture log
make latest
```

## Prerequisites

1. **Genymotion** emulator with Android 10+
2. **frida-server** running on emulator
3. **Kohler Konnect** APK installed

## Setup

```bash
# Install tools
brew install jadx frida-tools

# Start frida-server on emulator
adb root
adb push frida-server /data/local/tmp/
adb shell chmod +x /data/local/tmp/frida-server
adb shell /data/local/tmp/frida-server &
```

## Capture Traffic

The capture scripts hook the Kohler app to log:
- REST API requests/responses
- IoT Hub connection strings
- MQTT messages
- Command serialization

```bash
make capture   # Launch app with hooks
make logs      # List capture files
make latest    # View latest capture
```

## APK Analysis

Extract secrets (client_id, api_resource) from the APK:

```bash
# Place APK in dev/apk/base.apk
python3 scripts/extract_secrets_from_apk.py ../apk/base.apk
```
