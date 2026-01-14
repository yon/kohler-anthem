# Kohler Anthem - Development Scripts

Scripts for reverse engineering and API discovery.

For credential extraction scripts, see the `scripts/` directory at the project root.

## Scripts

| Script | Description |
|--------|-------------|
| `capture_kohler_traffic.py` | mitmproxy addon for HTTP traffic capture |
| `comprehensive_apk_analysis.py` | Deep APK analysis |
| `discover_api.py` | API endpoint discovery |
| `extract_apk_endpoints.py` | Extract API endpoints from decompiled APK |
| `frida_capture_hooks.js` | Frida hooks for traffic capture (HTTP, MQTT, IoT) |
| `frida_dev_capture.py` | Launch app with both bypass and capture hooks |
| `frida_proxy_inject.js` | Inject proxy settings via Frida |
| `test_api.py` | API testing utilities |
| `test_quick_dirty.py` | Quick API tests |

## Usage

```bash
# From dev/ directory
make capture    # Launch app with traffic capture
make logs       # List capture logs
make latest     # View latest capture log
```

## Captured Traffic

The Frida hooks log:
- `[HTTP]` - REST API requests (OkHttp)
- `[IOT HUB]` - IoT Hub connection strings
- `[IOT MESSAGE]` - Messages sent to IoT Hub
- `[MQTT]` - MQTT connections and publishes
- `[GSON]` - Command objects being serialized
- `[RETROFIT]` - Request bodies
