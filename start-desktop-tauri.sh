#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares
#
# Launch the Tauri desktop shell in dev mode (Track D / D3).
# Requires the Rust toolchain (rustup) + the Tauri CLI:
#   cargo install tauri-cli --version '^2'
# and, once, the app icons:
#   ( cd src-tauri && cargo tauri icon ../frontend/public/icon.png )
set -euo pipefail
cd "$(dirname "$0")/src-tauri"
exec cargo tauri dev
