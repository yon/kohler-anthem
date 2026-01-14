# Credential Extraction

This guide walks you through extracting the credentials needed to use the kohler-anthem library.

## Quick Start

```bash
# Install dependencies (jadx, adb, frida-tools)
make deps

# Run full credential extraction
make all
```

Or run individual steps:

```bash
make credentials-extract      # Extract client_id & api_resource from APK
make emulator-apim-capture    # Capture APIM key (requires Genymotion)
make credentials-generate     # Generate kohler-credentials.yaml
```

## Prerequisites

### Automated by `make deps`

- adb (Android Debug Bridge)
- frida-tools (runtime instrumentation)
- jadx (APK decompiler)
- jq (JSON processor)
- Python 3.9+

### Manual Setup Required

**Genymotion Desktop** - Android emulator with root access

The APIM key capture requires a rooted Android emulator to run Frida. Genymotion Desktop provides this capability.

> **Important**: You need **Genymotion Desktop** (30-day trial or paid license), NOT the free "Genymotion Personal" edition. The free edition does not support rooted emulators required for Frida instrumentation.

## Genymotion Setup

### 1. Download and Install Genymotion Desktop

1. Go to https://www.genymotion.com/product-desktop/download/
2. Click **"Get started"** under Desktop (30-day trial)
3. Create a Genymotion account if you don't have one
4. Download the installer for your platform
5. Install Genymotion Desktop

### 2. Create and Start Emulator

**Automated (recommended):**

```bash
make emulator-setup
```

This creates a "KohlerExtraction" device (Samsung Galaxy S10, Android 11, 4GB RAM) and starts it.

**Manual via GUI:**

1. Launch Genymotion Desktop
2. Click **"+"** to add a new device
3. Select **"Samsung Galaxy S10"** (or similar)
4. Choose **Android 11** or higher
5. Click **Install** to download the device image
6. Once downloaded, click **Start** to launch the emulator

### 3. Verify Emulator Connection

Once the emulator is running:

```bash
make emulator-check
```

This verifies:
- Device is connected via adb
- frida-server status

## What You'll Get

| Credential | Description | Source |
|------------|-------------|--------|
| `kohler_client_id` | OAuth client ID | Extracted from APK |
| `kohler_api_resource` | OAuth API scope | Extracted from APK |
| `kohler_apim_key` | API subscription key | Captured via Frida |
| `kohler_username` | Your email | You provide |
| `kohler_password` | Your password | You provide |

## Step-by-Step Guide

> **Note**: The emulator must be running for steps 3-5. Start it before proceeding.

### Step 1: Install Tools

```bash
make deps
```

This installs jadx, adb, frida-tools, and Python dependencies via Homebrew.

### Step 2: Extract Credentials from APK

```bash
make credentials-extract
```

This decompiles the APK (included in the repo at `kohler-konnect-3.0.1-apk/`) and extracts:
- `client_id` - Azure AD B2C client ID
- `api_resource` - OAuth API scope

Results are saved to `.build/secrets.json` (used by `make credentials-generate`).

### Step 3: Set Up Frida Server

Start your Genymotion emulator, then:

```bash
make emulator-frida-setup
```

This downloads and installs frida-server on the emulator.

### Step 4: Install APK on Emulator

```bash
make emulator-apk-install
```

This installs all split APKs (`base.apk` + `split_config.*.apk`) on the emulator using `adb install-multiple`.

### Step 5: Capture APIM Key

```bash
make emulator-apim-capture
```

This launches the Kohler Konnect app with Frida bypass and captures the APIM key.

**In the emulator:**
1. Grant location permission when prompted
2. Log in with your Kohler account
3. Select your device when prompted
4. Watch for "CAPTURED APIM SUBSCRIPTION KEY" in the terminal
5. **Kill the app** in the emulator (swipe it away or force stop) to let the script complete

The key is saved to `.build/captured_apim_key.json`.

### Step 6: Generate kohler-credentials.yaml

```bash
make credentials-generate
```

This creates `kohler-credentials.yaml` with the extracted values. Edit the file to add your Kohler account credentials:

```yaml
kohler_api_resource: <extracted>
kohler_apim_key: <captured>
kohler_client_id: <extracted>
kohler_password: YOUR_VALUE_HERE  # Fill in your password
kohler_username: YOUR_VALUE_HERE  # Fill in your email
```

## Troubleshooting

### "adb: command not found"

Run `make deps` to install Android Platform Tools.

### "No device connected"

Make sure Genymotion is running with an Android device. Check with:
```bash
adb devices
```

Or start via CLI:
```bash
gmtool admin start "KohlerExtraction"
```

### "frida-server not running"

Try:
```bash
adb root
adb shell /data/local/tmp/frida-server &
```

### "APIM key not captured"

- Make sure you launched with `make emulator-apim-capture`, not by tapping the app icon
- Log into the app (key is captured after authentication)
- Look for "[+] SecurePreferences APIM key capture installed" in output

### App crashes or shows "rooted device"

The Frida bypass handles root/emulator detection. If it still fails:
1. Clear app data: `adb shell pm clear com.kohler.hermoth`
2. Restart frida-server
3. Try again

### Genymotion trial expired

The 30-day trial is for evaluation. Options:
- Purchase a Genymotion Desktop license
- Use a physical rooted Android device with Frida

## Make Targets Reference

| Target | Description |
|--------|-------------|
| `all` | Run full extraction workflow |
| `credentials-extract` | Extract credentials from APK |
| `credentials-generate` | Generate kohler-credentials.yaml |
| `deps` | Install required tools |
| `emulator-apim-capture` | Capture APIM key via Frida |
| `emulator-apk-install` | Install split APKs on emulator |
| `emulator-check` | Check emulator connection and frida-server |
| `emulator-frida-setup` | Install frida-server on emulator |
| `emulator-setup` | Create and start Genymotion emulator |
| `tools-check` | Verify prerequisites |

## GMTool Reference

Genymotion's CLI tool for automation:

```bash
# Device management
gmtool admin list              # List all devices
gmtool admin list --running    # List running devices
gmtool admin start <device>    # Start a device
gmtool admin stop <device>     # Stop a device
gmtool admin stopall           # Stop all devices

# Device creation
gmtool admin templates         # List available templates
gmtool admin create <profile> <android> <name> [options]

# Options: --nbcpu, --ram, --width, --height, --density
```

See [GMTool documentation](https://docs.genymotion.com/desktop/06_GMTool/) for full reference.
