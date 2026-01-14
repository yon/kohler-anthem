# Kohler Anthem - Development Tools
#
# Tools for reverse engineering and API discovery.
# For credential extraction, use `make help` at the project root.

SHELL := /bin/bash
.PHONY: capture clean frida-start frida-status frida-stop help install-cert latest logs mitmproxy proxy-off proxy-on

# Paths
DEV_DIR := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
PROJECT_DIR := $(DEV_DIR)/..
SCRIPTS_DIR := $(DEV_DIR)/scripts
OUTPUT_DIR := $(DEV_DIR)/output

HOST_IP := $(shell ipconfig getifaddr en0 2>/dev/null || echo "10.0.2.2")
MITMPROXY := $(shell which mitmdump 2>/dev/null || echo ~/Library/Python/3.9/bin/mitmdump)
ADB := $(shell which adb 2>/dev/null || echo /Applications/Genymotion.app/Contents/MacOS/tools/adb)
FRIDA_PS := $(shell which frida-ps 2>/dev/null || echo ~/Library/Python/3.9/bin/frida-ps)

help:
	@echo "Kohler Anthem - Development Tools"
	@echo ""
	@echo "For credential extraction, run from project root:"
	@echo "  cd .. && make credential-extraction"
	@echo ""
	@echo "Traffic capture (for API discovery):"
	@echo "  make capture       Launch app with Frida hooks (captures HTTP, MQTT, IoT)"
	@echo "  make logs          List recent capture logs"
	@echo "  make latest        View latest capture log"
	@echo "  make mitmproxy     Start mitmproxy for HTTP traffic capture"
	@echo ""
	@echo "Frida server:"
	@echo "  make frida-start   Start frida-server on emulator"
	@echo "  make frida-status  Check frida-server status"
	@echo "  make frida-stop    Stop frida-server on emulator"
	@echo ""
	@echo "Proxy (for mitmproxy):"
	@echo "  make install-cert  Install mitmproxy CA cert on emulator"
	@echo "  make proxy-off     Disable proxy on emulator"
	@echo "  make proxy-on      Configure emulator to use proxy (HOST_IP=$(HOST_IP))"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         Remove capture logs"
	@echo ""
	@echo "See ../docs/CREDENTIAL_EXTRACTION.md for setup instructions."

# =============================================================================
# Traffic Capture (Frida)
# =============================================================================

capture:
	@mkdir -p $(OUTPUT_DIR)
	@python3 $(SCRIPTS_DIR)/frida_dev_capture.py

# =============================================================================
# Frida Server
# =============================================================================

frida-start:
	@$(ADB) root >/dev/null 2>&1 || true
	@$(ADB) shell "pkill -9 frida-server 2>/dev/null; /data/local/tmp/frida-server &" &
	@sleep 2
	@$(FRIDA_PS) -U >/dev/null 2>&1 && echo "Frida server running" || echo "ERROR: Could not connect"

frida-status:
	@$(FRIDA_PS) -U 2>&1 | head -5 || echo "Frida not connected"

frida-stop:
	@$(ADB) shell pkill -9 frida-server 2>/dev/null || true
	@echo "Frida server stopped"

# =============================================================================
# Traffic Capture Logs
# =============================================================================

latest:
	@LATEST=$$(ls -t $(OUTPUT_DIR)/capture_*.log 2>/dev/null | head -1); \
	if [ -n "$$LATEST" ]; then \
		echo "Viewing: $$LATEST"; \
		less $$LATEST; \
	else \
		echo "No capture logs found"; \
	fi

logs:
	@echo "Recent capture logs:"
	@echo ""
	@ls -lt $(OUTPUT_DIR)/capture_*.log 2>/dev/null | head -10 || echo "No capture logs found"

# =============================================================================
# mitmproxy
# =============================================================================

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

mitmproxy:
	@echo "Starting mitmproxy on port 8080..."
	@echo "Make sure proxy is configured: make proxy-on"
	@echo "Output: $(SCRIPTS_DIR)/captured_traffic/"
	@echo ""
	$(MITMPROXY) -s $(SCRIPTS_DIR)/capture_kohler_traffic.py --set block_global=false

proxy-off:
	@echo "Disabling proxy on emulator..."
	@$(ADB) shell settings put global http_proxy :0
	@echo "Proxy disabled."

proxy-on:
	@echo "Configuring proxy on emulator ($(HOST_IP):8080)..."
	@$(ADB) shell settings put global http_proxy $(HOST_IP):8080
	@echo "Proxy enabled. Run 'make mitmproxy' to start capturing."

# =============================================================================
# Cleanup
# =============================================================================

clean:
	@echo "Removing capture logs..."
	@rm -f $(OUTPUT_DIR)/capture_*.log
	@rm -f $(OUTPUT_DIR)/mitmproxy_*.log
	@rm -f $(OUTPUT_DIR)/mitmproxy_*.flow
	@echo "Done"
