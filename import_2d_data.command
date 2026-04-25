#!/bin/bash
# TS24 Puccetti — 2D Data Auto-Import
# ─────────────────────────────────────────────────────────────────
# 使い方:
#   ダブルクリックで実行 → 新規データフォルダーを入力 → 自動追加
#   過去データはall_sessions.jsonキャッシュから自動復元されます
#
# Usage:
#   Double-click to run → enter new round data folder → auto-merge
#   Historical data is restored from all_sessions.json cache.
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
EXCEL="$ROOT_DIR/02_DATABASE/TS24 DB Master.xlsx"
CACHE="$ROOT_DIR/02_DATABASE/all_sessions.json"

echo "========================================="
echo "  TS24 Puccetti — 2D Data Import"
echo "  (Incremental mode — cache backed)"
echo "========================================="
echo ""
echo "Excel : $EXCEL"
echo "Cache : $CACHE"
echo ""

# ── 新規データフォルダーを確認 ───────────────────────────────────
echo "New round data folder path (drag & drop or type full path)."
echo "Leave blank to rebuild Excel from cache only:"
echo ""
read -p "Folder: " NEW_DATA_DIR

# 前後のスペースとクォートを除去
NEW_DATA_DIR="$(echo "$NEW_DATA_DIR" | sed "s/^['\"]//;s/['\"]$//" | xargs)"

if [ -z "$NEW_DATA_DIR" ]; then
    echo ""
    echo "No folder specified — rebuilding Excel from cache..."
    SCAN_PATH="NONE"
elif [ ! -d "$NEW_DATA_DIR" ]; then
    echo ""
    echo "WARNING: Folder not found: $NEW_DATA_DIR"
    echo "Rebuilding Excel from cache only..."
    SCAN_PATH="NONE"
else
    echo ""
    echo "Scanning: $NEW_DATA_DIR"
    SCAN_PATH="$NEW_DATA_DIR"
fi

echo ""
python3 "$SCRIPT_DIR/parse_2d_to_excel.py" "$SCAN_PATH" "$EXCEL" "$CACHE"

echo ""
read -p "Press Enter to exit..."
