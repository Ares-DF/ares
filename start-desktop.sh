#!/bin/bash
# Ares — Start Electron desktop app
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/backend/.venv/bin/activate"
cd "$SCRIPT_DIR/electron"
exec npx electron . "$@"
