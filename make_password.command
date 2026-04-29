#!/bin/bash
# TS24 Dashboard — Password Generator launcher
# Double-click this file to run

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/password_generator.py"
