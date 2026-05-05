#!/bin/bash
# TS24 Engineer Workbench — 起動スクリプト
# Double-click this file to launch

SCRIPT_DIR="$HOME/Desktop/Data TS24 Claude/05_SCRIPTS"

echo "========================================="
echo "  TS24 Engineer Workbench"
echo "========================================="
echo ""

cd "$SCRIPT_DIR"

# Python3 確認
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 が見つかりません。インストールしてください。"
    read -p "Press Enter to exit..."
    exit 1
fi

# PyQt6 確認
if ! python3 -c "import PyQt6" &> /dev/null; then
    echo "⚠️  PyQt6 が未インストールです。インストールします..."
    pip3 install PyQt6 pyqtgraph --break-system-packages
    echo ""
fi

echo "✅ Workbench を起動します..."
echo ""
python3 ts24_workbench.py

echo ""
read -p "Press Enter to exit..."
