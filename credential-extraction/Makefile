# Kohler Anthem - Credential Extraction
#
# Capture pipeline for the Kohler Konnect APIM /token GET (service-account JWT)
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

# Patched APK bundle (Is.b.n() returns false; resigned with debug key).
# Required because Frida hooks on Is.b don't intercept on Android 11 AVD.
APK_PATCHED_DIR := $(EXTRACTION_DIR)/konnect-apk-patched
APK_PATCHED     := $(APK_PATCHED_DIR)/base.apk

# --- tool paths as real Make targets ---------------------------------------

# brew --prefix gives /opt/homebrew on Apple Silicon, /usr/local on Intel.
# Cached at parse-time (single shell-out per make invocation).
BREW_PREFIX     := $(shell brew --prefix 2>/dev/null)

ADB             := $(BREW_PREFIX)/bin/adb
JADX            := $(BREW_PREFIX)/bin/jadx
JQ              := $(BREW_PREFIX)/bin/jq
MITMDUMP_BREW   := $(BREW_PREFIX)/bin/mitmdump
XZ              := $(BREW_PREFIX)/bin/xz
APKTOOL         := $(BREW_PREFIX)/bin/apktool

# Android SDK (installed via android-commandlinetools cask). The cask installs
# into share/android-commandlinetools but does NOT bundle the emulator binary,
# system image, or build-tools — `make sdk-components` calls sdkmanager to add
# those. Each component is exposed as a real file target so Make won't re-run.
ANDROID_HOME    := $(BREW_PREFIX)/share/android-commandlinetools
SDKMANAGER      := $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager
AVDMANAGER      := $(ANDROID_HOME)/cmdline-tools/latest/bin/avdmanager
EMULATOR_BIN    := $(ANDROID_HOME)/emulator/emulator
ANDROID_PLATFORM_TOOLS := $(ANDROID_HOME)/platform-tools/adb
SYSTEM_IMAGE_DIR := $(ANDROID_HOME)/system-images/android-30/google_apis/arm64-v8a
BUILD_TOOLS_DIR := $(ANDROID_HOME)/build-tools/35.0.0
# platforms;android-30 is OPTIONAL — the system image already declares the API
# level. Leaving it as a separate target callers can opt into if they need it.
PLATFORM_DIR    := $(ANDROID_HOME)/platforms/android-30

JAVA_HOME       := $(BREW_PREFIX)/opt/openjdk
KEYTOOL         := $(JAVA_HOME)/bin/keytool

# Inside the project venv (after `make venv` + pip installs)
FRIDA           := $(VENV)/bin/frida
MITMDUMP_VENV   := $(VENV)/bin/mitmdump
PIP             := $(VENV)/bin/pip

BREW_TOOLS      := $(ADB) $(JADX) $(JQ) $(MITMDUMP_BREW) $(XZ) $(APKTOOL) \
                   $(SDKMANAGER) $(KEYTOOL)
SDK_COMPONENTS  := $(EMULATOR_BIN) $(SYSTEM_IMAGE_DIR) $(BUILD_TOOLS_DIR)
VENV_TOOLS      := $(FRIDA) $(MITMDUMP_VENV)
ALL_TOOLS       := $(BREW_TOOLS) $(SDK_COMPONENTS) $(VENV_TOOLS)

# --- phony declarations -----------------------------------------------------

.PHONY: help all harness \
        venv deps tools-check sdk-components \
        secrets-init secrets-link secrets-check \
        apk-verify apk-update apk-patch apk-install-patched \
        capture-pfx-password extract-client-cert \
        avd-setup avd-recreate \
        emulator-setup emulator-check \
        emulator-frida-setup \
        emulator-apk-install emulator-apk-install-patched \
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
	@echo "  make harness          End-to-end APIM /token capture (AVD + patched APK + Frida + mTLS)"
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

harness: deps secrets-check apk-verify ## Run the full end-to-end APIM /token capture pipeline (AVD + patched APK + Frida + mTLS)
	$(Q)$(PY) $(SCRIPTS_DIR)/harness.py

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

$(APKTOOL): | _check-brew
	@echo "Installing apktool..."
	$(Q)brew install apktool

$(SDKMANAGER) $(AVDMANAGER): | _check-brew
	@echo "Installing android-commandlinetools..."
	$(Q)brew install --cask android-commandlinetools

$(KEYTOOL): | _check-brew
	@echo "Installing openjdk..."
	$(Q)brew install openjdk

# Android SDK components installed via sdkmanager (`yes |` accepts licenses).
# Each subcomponent gets its own target so Make won't re-install. If you change
# the system image or build-tools version, update the var at the top.
$(EMULATOR_BIN): | $(SDKMANAGER) $(KEYTOOL)
	@echo "Installing Android emulator..."
	$(Q)export JAVA_HOME=$(JAVA_HOME); \
	  yes | $(SDKMANAGER) --licenses >/dev/null 2>&1 || true; \
	  $(SDKMANAGER) --install 'emulator' 'platform-tools'

$(SYSTEM_IMAGE_DIR): | $(SDKMANAGER) $(KEYTOOL)
	@echo "Installing Android 11 system image (google_apis arm64-v8a)..."
	$(Q)export JAVA_HOME=$(JAVA_HOME); \
	  $(SDKMANAGER) --install 'system-images;android-30;google_apis;arm64-v8a'

$(BUILD_TOOLS_DIR): | $(SDKMANAGER) $(KEYTOOL)
	@echo "Installing build-tools 35.0.0..."
	$(Q)export JAVA_HOME=$(JAVA_HOME); \
	  $(SDKMANAGER) --install 'build-tools;35.0.0'

$(PLATFORM_DIR): | $(SDKMANAGER) $(KEYTOOL)
	@echo "Installing platforms;android-30..."
	$(Q)export JAVA_HOME=$(JAVA_HOME); \
	  $(SDKMANAGER) --install 'platforms;android-30'

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

deps: $(ALL_TOOLS) ## Install required tools + SDK components (idempotent)
	@echo "All tools installed."

sdk-components: $(SDK_COMPONENTS) ## Install just the Android SDK components (emulator, system-image, build-tools)
	@echo "Android SDK components ready under $(ANDROID_HOME)."

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

apk-patch: deps $(APK_BASE) ## Apktool-patch Is.b.n() to return false + resign (defeats Konnect root check)
	$(Q)$(PY) $(SCRIPTS_DIR)/apk_patch.py

apk-install-patched: emulator-check $(APK_PATCHED) ## Install the patched APK on the emulator (-i com.android.vending)
	$(Q)$(PY) $(SCRIPTS_DIR)/emulator_apk_install.py --patched

capture-pfx-password: emulator-frida-setup apk-install-patched ## Recover the app_certificate.p12 password via Frida
	$(Q)$(PY) $(SCRIPTS_DIR)/capture_pfx_password.py

extract-client-cert: ## Extract res/raw/app_certificate.p12 → PEM using captured password
	$(Q)$(PY) $(SCRIPTS_DIR)/extract_client_cert.py

# --- emulator orchestration -------------------------------------------------

# AVD: Boots an Android 11 + google_apis + arm64-v8a image with a writable
# /system partition (needed for the mitmproxy CA install).
avd-setup: $(SDK_COMPONENTS) ## Create + start the KohlerExtraction AVD (idempotent)
	$(Q)$(PY) $(SCRIPTS_DIR)/avd_setup.py

avd-recreate: $(SDK_COMPONENTS) ## Delete + recreate the KohlerExtraction AVD before starting
	$(Q)$(PY) $(SCRIPTS_DIR)/avd_setup.py --recreate

# `emulator-setup` is the harness-facing alias.
emulator-setup: avd-setup ## Create + start the emulator (AVD)

emulator-check: $(ADB) ## Check emulator connection + frida-server status
	$(Q)$(PY) $(SCRIPTS_DIR)/emulator_check.py

emulator-frida-setup: emulator-check $(FRIDA) $(XZ) ## Push frida-server to the emulator
	$(Q)$(PY) $(SCRIPTS_DIR)/frida_setup.py

emulator-apk-install: emulator-check apk-verify ## Install the (unpatched) Konnect APK on the emulator
	$(Q)$(PY) $(SCRIPTS_DIR)/emulator_apk_install.py

emulator-apk-install-patched: emulator-check apk-install-patched ## Alias for apk-install-patched (back-compat)

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

clean-emulator: ## Stop emulator + delete the KohlerExtraction AVD
	$(Q)adb -s emulator-5554 emu kill >/dev/null 2>&1 || true
	$(Q)pkill -f 'qemu-system-aarch64' >/dev/null 2>&1 || true
	$(Q)pkill -f 'KohlerExtraction' >/dev/null 2>&1 || true
	$(Q)if [ -x "$(AVDMANAGER)" ]; then \
	  JAVA_HOME=$(JAVA_HOME) $(AVDMANAGER) delete avd --name KohlerExtraction 2>/dev/null || true; \
	fi
	$(Q)rm -rf $$HOME/.android/avd/KohlerExtraction.avd $$HOME/.android/avd/KohlerExtraction.ini 2>/dev/null || true
	$(Q)adb kill-server >/dev/null 2>&1 || true
	@echo "Stopped + deleted KohlerExtraction AVD"

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
