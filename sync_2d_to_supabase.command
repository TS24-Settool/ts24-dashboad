#!/bin/bash
# TS24 Puccetti — 2D Data → Supabase Sync
# ────────────────────────────────────────
# 事前準備: Supabase SQL Editor で create_2d_tables.sql を実行してください

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================="
echo "  TS24 Puccetti — 2D → Supabase Sync"
echo "========================================="
echo ""

python3 "$SCRIPT_DIR/sync_2d_to_supabase.py"

echo ""
read -p "Press Enter to exit..."
