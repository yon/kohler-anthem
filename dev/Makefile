# Kohler Anthem - Development Tools
#
# Setup and traffic capture tools for development.

SHELL := /bin/bash
.PHONY: help install extract env capture clean logs mitmproxy proxy-on proxy-off install-cert frida-start frida-stop frida-status

# Paths
DEV_DIR := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
PROJECT_DIR := $(DEV_DIR)/..
SCRIPTS_DIR := $(DEV_DIR)/scripts
OUTPUT_DIR := $(DEV_DIR)/output
APK_DIR := $(DEV_DIR)/apk
BUILD_DIR := $(DEV_DIR)/build
DECOMPILED_DIR := $(BUILD_DIR)/decompiled

HOST_IP := $(shell ipconfig getifaddr en0 2>/dev/null || echo "10.0.2.2")
MITMPROXY := ~/Library/Python/3.9/bin/mitmdump
ADB := $(shell which adb 2>/dev/null || echo /Applications/Genymotion.app/Contents/MacOS/tools/adb)
FRIDA_PS := $(shell which frida-ps 2>/dev/null || echo ~/Library/Python/3.9/bin/frida-ps)

help:
	@echo "Kohler Anthem - Development Tools"
	@echo ""
	@echo "Setup (first time):"
	@echo "  make install       Install required tools (brew, python, adb, frida, jadx)"
	@echo "  make extract       Extract secrets from APK (client_id, api_resource)"
	@echo "  make capture       Launch app with Frida bypass (captures APIM key)"
	@echo "  make env           Generate .env file from captured secrets"
	@echo ""
	@echo "Frida server:"
	@echo "  make frida-start   Start frida-server on emulator"
	@echo "  make frida-stop    Stop frida-server on emulator"
	@echo "  make frida-status  Check frida-server status"
	@echo ""
	@echo "Traffic capture:"
	@echo "  make logs          Show recent capture logs"
	@echo "  make mitmproxy     Start mitmproxy to capture HTTP traffic"
	@echo "  make proxy-on      Configure emulator to use proxy (HOST_IP=$(HOST_IP))"
	@echo "  make proxy-off     Disable proxy on emulator"
	@echo "  make install-cert  Install mitmproxy CA cert on emulator"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         Remove build artifacts and capture logs"
	@echo ""
	@echo "See SETUP.md for detailed instructions."

# =============================================================================
# Install Tools
# =============================================================================

install: install-brew install-python install-android install-apk-tools install-frida
	@echo ""
	@echo "All tools installed. Next step: make extract"

install-brew:
	@which brew > /dev/null || /bin/bash -c "$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

install-python:
	@brew list python@3.11 > /dev/null 2>&1 || brew install python@3.11
	@pip3 install --quiet frida-tools aiohttp

install-android:
	@brew list --cask android-platform-tools > /dev/null 2>&1 || brew install --cask android-platform-tools

install-frida:
	@pip3 install --quiet --upgrade frida-tools

install-apk-tools:
	@brew list jadx > /dev/null 2>&1 || brew install jadx
	@brew list jq > /dev/null 2>&1 || brew install jq

# =============================================================================
# Extract Secrets from APK
# =============================================================================

extract: $(BUILD_DIR)
	@if [ ! -f "$(APK_DIR)/base.apk" ]; then \
		echo "ERROR: APK not found at $(APK_DIR)/base.apk"; \
		echo ""; \
		echo "Get the APK from your Android device:"; \
		echo "  1. Install 'Kohler Konnect' from Play Store"; \
		echo "  2. adb shell pm path com.kohler.hermoth"; \
		echo "  3. adb pull <path>/base.apk $(APK_DIR)/base.apk"; \
		exit 1; \
	fi
	@echo "Decompiling APK..."
	@jadx --quiet -d $(DECOMPILED_DIR) $(APK_DIR)/base.apk 2>/dev/null || true
	@echo "Extracting secrets..."
	@python3 $(SCRIPTS_DIR)/extract_secrets_from_apk.py $(DECOMPILED_DIR) > $(BUILD_DIR)/secrets.json
	@echo ""
	@echo "Secrets extracted:"
	@cat $(BUILD_DIR)/secrets.json | jq .
	@echo ""
	@echo "Next step: make capture"

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

# =============================================================================
# Generate .env File
# =============================================================================

env:
	@python3 $(SCRIPTS_DIR)/generate_env.py

# =============================================================================
# Frida Capture & Bypass
# =============================================================================

capture:
	@python3 $(SCRIPTS_DIR)/frida_capture_apim.py

frida-start:
	@$(ADB) root >/dev/null 2>&1 || true
	@$(ADB) shell "pkill -9 frida-server 2>/dev/null; /data/local/tmp/frida-server &" &
	@sleep 2
	@$(FRIDA_PS) -U >/dev/null 2>&1 && echo "Frida server running" || echo "ERROR: Could not connect"

frida-stop:
	@$(ADB) shell pkill -9 frida-server 2>/dev/null || true
	@echo "Frida server stopped"

frida-status:
	@$(FRIDA_PS) -U 2>&1 | head -5 || echo "Frida not connected"

# =============================================================================
# Traffic Capture Logs
# =============================================================================

logs:
	@echo "Recent capture logs:"
	@echo ""
	@ls -lt $(OUTPUT_DIR)/capture_*.log 2>/dev/null | head -10 || echo "No capture logs found"

latest:
	@LATEST=$$(ls -t $(OUTPUT_DIR)/capture_*.log 2>/dev/null | head -1); \
	if [ -n "$$LATEST" ]; then \
		echo "Viewing: $$LATEST"; \
		less $$LATEST; \
	else \
		echo "No capture logs found"; \
	fi

# =============================================================================
# mitmproxy
# =============================================================================

mitmproxy:
	@echo "Starting mitmproxy on port 8080..."
	@echo "Make sure proxy is configured: make proxy-on"
	@echo "Output: $(OUTPUT_DIR)/mitmproxy_http.log"
	@echo ""
	$(MITMPROXY) -s $(SCRIPTS_DIR)/mitmproxy_capture.py --set block_global=false

proxy-on:
	@echo "Configuring proxy on emulator ($(HOST_IP):8080)..."
	@$(ADB) shell settings put global http_proxy $(HOST_IP):8080
	@echo "Proxy enabled. Run 'make mitmproxy' to start capturing."

proxy-off:
	@echo "Disabling proxy on emulator..."
	@$(ADB) shell settings put global http_proxy :0
	@echo "Proxy disabled."

install-cert:
	@echo "Installing mitmproxy CA certificate..."
	@if [ ! -f ~/.mitmproxy/mitmproxy-ca-cert.cer ]; then \
		echo "CA cert not found. Run mitmproxy once first to generate it."; \
		exit 1; \
	fi
	@HASH=$$(openssl x509 -inform PEM -subject_hash_old -in ~/.mitmproxy/mitmproxy-ca-cert.cer | head -1); \
	echo "Certificate hash: $$HASH"; \
	openssl x509 -inform PEM -in ~/.mitmproxy/mitmproxy-ca-cert.cer -out /tmp/$$HASH.0; \
	$(ADB) root; \
	sleep 1; \
	$(ADB) remount; \
	sleep 1; \
	$(ADB) push /tmp/$$HASH.0 /system/etc/security/cacerts/; \
	$(ADB) shell chmod 644 /system/etc/security/cacerts/$$HASH.0; \
	echo "Certificate installed. Reboot emulator for changes to take effect."
	@echo "Run: $(ADB) reboot"

# =============================================================================
# Cleanup
# =============================================================================

clean:
	@echo "Removing build artifacts and capture logs..."
	@rm -rf $(BUILD_DIR)
	@rm -f $(OUTPUT_DIR)/capture_*.log
	@rm -f $(OUTPUT_DIR)/mitmproxy_*.log
	@rm -f $(OUTPUT_DIR)/mitmproxy_*.flow
	@echo "Done"
