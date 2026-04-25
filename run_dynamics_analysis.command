#!/bin/bash
# TS24 Puccetti — 2D Channel Dynamics Analysis
# ─────────────────────────────────────────────
# DATA 2D フォルダ内の全 MES を解析し
# TS24 DB Master.xlsx の DYNAMICS_ANALYSIS シートに書き込む

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo "  TS24 Puccetti — Dynamics Analysis (APEX / SlowZ / Brake)"
echo "============================================================"
echo ""

python3 "$SCRIPT_DIR/parse_2d_channels.py"

echo ""
read -p "Press Enter to exit..."
