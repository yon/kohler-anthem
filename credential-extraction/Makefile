# Kohler Anthem - Credential Extraction
#
# Capture pipeline for the Kohler Konnect /token POST against B2C_1A_signin,
# plus legacy static-credential extraction. See README.md for the user journey.
#
# Every tool the harness needs is expressed as a real Make file target. `make
# deps` only runs `brew install` for the ones that don't exist yet; re-running
# is fast (no `brew list` shell calls).

SHELL          := /bin/bash
.DEFAULT_GOAL  := help
.NOTPARALLEL:

# --- paths ------------------------------------------------------------------

EXTRACTION_DIR := $(abspath .)
REPO_ROOT      := $(abspath ..)
BUILD_DIR      := .build
SCRIPTS_DIR    := scripts

# Python venv (shared with the main library)
VENV           := $(REPO_ROOT)/.venv
VENV_PYTHON    := $(VENV)/bin/python3
PY             := $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)

# Secrets
ENV_FILE       := $(REPO_ROOT)/.env
ENV_TARGET     := /Volumes/ring/env/kohler.env
ENV_EXAMPLE    := $(EXTRACTION_DIR)/env.example

# Persistent caches outside the repo
CACHE_DIR      := $(HOME)/Library/Caches/kohler-anthem

# In-repo (git-LFS) Konnect APK — the canonical install source.
APK_DIR        := $(EXTRACTION_DIR)/konnect-apk
APK_MANIFEST   := $(APK_DIR)/manifest.json
APK_BASE       := $(APK_DIR)/base.apk

# --- tool paths as real Make targets ---------------------------------------

# brew --prefix gives /opt/homebrew on Apple Silicon, /usr/local on Intel.
# Cached at parse-time (single shell-out per make invocation).
BREW_PREFIX     := $(shell brew --prefix 2>/dev/null)

ADB             := $(BREW_PREFIX)/bin/adb
JADX            := $(BREW_PREFIX)/bin/jadx
JQ              := $(BREW_PREFIX)/bin/jq
MITMDUMP_BREW   := $(BREW_PREFIX)/bin/mitmdump
XZ              := $(BREW_PREFIX)/bin/xz
GMTOOL          := /Applications/Genymotion.app/Contents/MacOS/gmtool

# Inside the project venv (after `make venv` + pip installs)
FRIDA           := $(VENV)/bin/frida
MITMDUMP_VENV   := $(VENV)/bin/mitmdump
PIP             := $(VENV)/bin/pip

BREW_TOOLS      := $(ADB) $(JADX) $(JQ) $(MITMDUMP_BREW) $(XZ) $(GMTOOL)
VENV_TOOLS      := $(FRIDA) $(MITMDUMP_VENV)
ALL_TOOLS       := $(BREW_TOOLS) $(VENV_TOOLS)

# --- phony declarations -----------------------------------------------------

.PHONY: help all harness \
        venv deps tools-check \
        secrets-init secrets-link secrets-check \
        apk-verify apk-update \
        genymotion-signin \
        emulator-setup emulator-check \
        emulator-frida-setup \
        emulator-apk-install \
        emulator-mitmproxy-setup emulator-mitmproxy-clear emulator-mitmproxy-uninstall \
        emulator-konnect-signin record-konnect-signin \
        emulator-token-capture emulator-apim-capture \
        credentials-extract credentials-generate \
        doctor \
        clean clean-cache clean-emulator clean-all \
        ci-smoke \
        _check-brew

# --- help -------------------------------------------------------------------

help: ## Show this help message
	@echo "Kohler Anthem — credential-extraction harness"
	@echo
	@echo "First-time setup (anyone, fresh machine):"
	@echo "  make deps             Install brew + pip tools (idempotent)"
	@echo "  make secrets-init     Scaffold env file from env.example"
	@echo "  make secrets-link     Symlink .env → /Volumes/ring/env/kohler.env"
	@echo "  \$$EDITOR $(ENV_TARGET)   Fill in YOUR_VALUE_HERE blanks"
	@echo "  make secrets-check    Verify the env file is complete"
	@echo "  make harness          Run the whole pipeline end-to-end"
	@echo
	@echo "Top-level workflows:"
	@echo "  make harness          Full B2C_1A_signin /token capture"
	@echo "  make all              Legacy APIM-key extraction"
	@echo "  make doctor           One-shot diagnostics snapshot"
	@echo
	@echo "Individual steps:"
	@grep -E '^[a-z][a-z0-9-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-30s %s\n", $$1, $$2}'
	@echo
	@echo "Set V=1 to see the actual commands being run."

ifeq ($(V),1)
Q :=
else
Q := @
endif

# --- top-level workflows ---------------------------------------------------

harness: deps secrets-check apk-verify ## Run the full B2C_1A_signin /token capture pipeline
	$(Q)$(PY) $(SCRIPTS_DIR)/harness.py --skip-apk-fetch

all: deps credentials-extract emulator-setup emulator-frida-setup emulator-apk-install emulator-apim-capture credentials-generate ## Legacy: APIM-key credential extraction
	@echo
	@echo "APIM credential extraction complete!"
	@echo "Check kohler-credentials.yaml for your credentials."

# --- venv + tool installs (real file targets) ------------------------------

_check-brew:
	$(Q)if [ -z "$(BREW_PREFIX)" ]; then \
	  echo "ERROR: Homebrew not found. Install it from https://brew.sh first."; \
	  exit 1; \
	fi

# Each brew tool is a real file target. Make won't re-run brew install if the
# binary already exists. Casks may prompt for an admin password on first run.
$(ADB): | _check-brew
	@echo "Installing android-platform-tools (provides adb)..."
	$(Q)brew install --cask android-platform-tools

$(JADX): | _check-brew
	@echo "Installing jadx..."
	$(Q)brew install jadx

$(JQ): | _check-brew
	@echo "Installing jq..."
	$(Q)brew install jq

$(MITMDUMP_BREW): | _check-brew
	@echo "Installing mitmproxy (brew)..."
	$(Q)brew install mitmproxy

$(XZ): | _check-brew
	@echo "Installing xz..."
	$(Q)brew install xz

$(GMTOOL): | _check-brew
	@echo "Installing Genymotion Desktop..."
	$(Q)brew install --cask genymotion

# The project venv. python3 must exist on the system PATH.
$(VENV_PYTHON):
	@echo "Creating project venv at $(VENV)"
	$(Q)python3 -m venv $(VENV)
	$(Q)$(VENV_PYTHON) -m pip install --quiet --upgrade pip

$(FRIDA): $(VENV_PYTHON)
	@echo "Installing frida-tools into venv..."
	$(Q)$(PIP) install --quiet frida-tools

$(MITMDUMP_VENV): $(VENV_PYTHON)
	@echo "Installing mitmproxy into venv..."
	$(Q)$(PIP) install --quiet mitmproxy

venv: $(VENV_PYTHON) ## Create the project Python venv

deps: $(ALL_TOOLS) ## Install required tools (real file targets — only installs what's missing)
	@echo "All tools installed."

tools-check: ## Verify every required tool is installed and discoverable
	$(Q)$(PY) $(SCRIPTS_DIR)/tools_check.py

# --- secrets bootstrap -----------------------------------------------------

secrets-init: ## Scaffold /Volumes/ring/env/kohler.env from env.example
	$(Q)$(PY) $(SCRIPTS_DIR)/secrets_init.py

secrets-link: ## Create the .env symlink in the repo root
	$(Q)$(PY) $(SCRIPTS_DIR)/secrets_link.py

secrets-check: ## Verify all required env keys are populated
	$(Q)$(PY) $(SCRIPTS_DIR)/secrets_check.py

# --- APK (in-repo, git-LFS-tracked) -----------------------------------------

# `$(APK_MANIFEST)` is a real file in the repo. If it (or `base.apk`) is missing,
# either git-LFS hasn't been pulled or someone deleted it — the recipe gives a
# clear next-action hint.
$(APK_MANIFEST) $(APK_BASE):
	@echo "ERROR: $@ is missing."
	@echo "  Either git-LFS content has not been pulled or the file was deleted."
	@echo "  Recover with:"
	@echo "    git lfs pull --include='credential-extraction/konnect-apk/'"
	@false

apk-verify: $(APK_MANIFEST) $(APK_BASE) ## Hash-check the in-repo APK against its manifest
	$(Q)$(PY) $(SCRIPTS_DIR)/apk_fetch.py --verify

apk-update: deps ## Refresh the in-repo APK from APKPure (review before committing)
	$(Q)$(PY) $(SCRIPTS_DIR)/apk_fetch.py --update

# --- emulator orchestration -------------------------------------------------

genymotion-signin: secrets-check $(GMTOOL) ## Sign in to Genymotion via gmtool
	$(Q)$(PY) $(SCRIPTS_DIR)/genymotion_signin.py

emulator-setup: deps genymotion-signin ## Create + start the KohlerExtraction device
	$(Q)$(PY) $(SCRIPTS_DIR)/emulator_setup.py

emulator-check: $(ADB) ## Check emulator connection + frida-server status
	$(Q)$(PY) $(SCRIPTS_DIR)/emulator_check.py

emulator-frida-setup: emulator-check $(FRIDA) $(XZ) ## Push frida-server to the emulator
	$(Q)$(PY) $(SCRIPTS_DIR)/frida_setup.py

emulator-apk-install: emulator-check apk-verify ## Install Konnect APK on the emulator
	$(Q)$(PY) $(SCRIPTS_DIR)/emulator_apk_install.py

emulator-mitmproxy-setup: emulator-check $(MITMDUMP_VENV) ## Install mitmproxy CA + set HTTP proxy on the emulator
	$(Q)$(PY) $(SCRIPTS_DIR)/mitmproxy_setup.py

emulator-mitmproxy-clear: $(ADB) ## Remove the Android global http_proxy (CA stays installed)
	$(Q)$(PY) $(SCRIPTS_DIR)/mitmproxy_setup.py --clear

emulator-mitmproxy-uninstall: $(ADB) ## Remove the mitmproxy CA from /system AND clear the proxy
	$(Q)$(PY) $(SCRIPTS_DIR)/mitmproxy_setup.py --uninstall

emulator-konnect-signin: $(ADB) ## Pre-grant perms + (eventually) drive Konnect sign-in
	$(Q)$(PY) $(SCRIPTS_DIR)/konnect_signin.py

record-konnect-signin: emulator-check ## Record the Konnect sign-in UI flow for replay
	$(Q)$(PY) $(SCRIPTS_DIR)/record_konnect_signin.py

emulator-token-capture: emulator-check emulator-mitmproxy-setup ## Run mitmdump+Frida to capture /token
	$(Q)$(PY) $(SCRIPTS_DIR)/token_capture.py

emulator-apim-capture: emulator-frida-setup ## Capture APIM key via Frida (legacy)
	$(Q)$(PY) $(SCRIPTS_DIR)/apim_capture.py

# --- legacy static extraction ----------------------------------------------

credentials-extract: $(BUILD_DIR) $(JADX) ## Extract client_id + api_resource from APK
	$(Q)$(PY) $(SCRIPTS_DIR)/credentials_extract.py

credentials-generate: ## Generate kohler-credentials.yaml from extracted values
	$(Q)$(PY) $(SCRIPTS_DIR)/credentials_generate.py

# --- diagnostics ------------------------------------------------------------

doctor: ## Snapshot of host + emulator state for debugging
	$(Q)$(PY) $(SCRIPTS_DIR)/doctor.py

# --- cleanup ----------------------------------------------------------------

clean: ## Remove .build/ (per-run scratch space)
	rm -rf $(BUILD_DIR)

clean-emulator: ## Stop + delete the KohlerExtraction Genymotion device
	$(Q)"$(GMTOOL)" admin stop KohlerExtraction 2>/dev/null; sleep 2; \
	"$(GMTOOL)" admin delete KohlerExtraction || true; \
	adb kill-server >/dev/null 2>&1 || true; \
	echo "Stopped + deleted KohlerExtraction"

clean-cache: ## Wipe the persistent harness cache (mitmproxy CA, captures, etc.) — DANGEROUS
	@echo "About to remove $(CACHE_DIR). Continue? [y/N]"
	@read confirm && [ "$$confirm" = "y" ] && rm -rf $(CACHE_DIR) || echo "Aborted."

clean-all: clean clean-emulator ## Clean everything: build dir + emulator (NOT cache; use clean-cache for that)

# --- CI / smoke ------------------------------------------------------------

ci-smoke: deps tools-check apk-verify ## CI-safe steps (no emulator needed)
	$(Q)$(PY) $(SCRIPTS_DIR)/secrets_check.py || true
	@echo "ci-smoke complete (deps + tools-check + apk-verify ok)"

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)
