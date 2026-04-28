#!/bin/bash
# TS24 Dashboard — Supabase lap_times 同期
# Double-click this file to run

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================="
echo "  TS24 — lap_times Supabase 同期"
echo "========================================="
echo ""

python3 sync_lap_times.py

echo ""
read -p "Press Enter to exit..."
