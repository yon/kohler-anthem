# Kohler Anthem - Credential Extraction
#
# Tools for extracting credentials needed to use the kohler-anthem library.
# See README.md for detailed instructions.

SHELL := /bin/bash
.PHONY: all clean credentials-extract credentials-generate deps emulator-apim-capture emulator-apk-install emulator-check emulator-frida-setup emulator-setup help tools-check

# Paths
APK_DIR := kohler-konnect-3.0.1-apk
BUILD_DIR := .build
SCRIPTS_DIR := scripts

.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Kohler Anthem - Credential Extraction"
	@echo ""
	@echo "Quick start:"
	@echo "  make all    Run full credential extraction workflow"
	@echo ""
	@echo "Individual steps:"
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-26s %s\n", $$1, $$2}'

all: deps credentials-extract emulator-setup emulator-frida-setup emulator-apk-install emulator-apim-capture credentials-generate ## Run full credential extraction
	@echo ""
	@echo "Credential extraction complete!"
	@echo "Check kohler-credentials.yaml for your credentials."

clean: ## Remove build artifacts
	rm -rf $(BUILD_DIR)

credentials-extract: $(BUILD_DIR) ## Extract client_id and api_resource from APK
	@python3 $(SCRIPTS_DIR)/credentials_extract.py

credentials-generate: ## Generate credentials.yaml from extracted secrets
	@python3 $(SCRIPTS_DIR)/credentials_generate.py

deps: ## Install required tools (jadx, adb, frida-tools)
	@echo "Installing tools..."
	@which brew > /dev/null || (echo "Homebrew not found. Install from https://brew.sh" && exit 1)
	@brew list --cask android-platform-tools > /dev/null 2>&1 || brew install --cask android-platform-tools
	@brew list jadx > /dev/null 2>&1 || brew install jadx
	@brew list jq > /dev/null 2>&1 || brew install jq
	@pip3 install --quiet frida-tools
	@echo "All tools installed."

emulator-apim-capture: ## Capture APIM key via Frida (requires emulator)
	@python3 $(SCRIPTS_DIR)/apim_capture.py

emulator-apk-install: ## Install Kohler Konnect APK on emulator
	@python3 $(SCRIPTS_DIR)/emulator_apk_install.py

emulator-check: ## Check emulator connection and frida-server status
	@python3 $(SCRIPTS_DIR)/emulator_check.py

emulator-frida-setup: ## Download and install frida-server on emulator
	@python3 $(SCRIPTS_DIR)/frida_setup.py

emulator-setup: ## Create and start Genymotion emulator (requires Genymotion Desktop)
	@python3 $(SCRIPTS_DIR)/emulator_setup.py

tools-check: ## Check if required tools are installed
	@python3 $(SCRIPTS_DIR)/tools_check.py

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)
