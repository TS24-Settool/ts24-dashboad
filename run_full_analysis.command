#!/bin/bash
# ============================================================
#  TS24 Puccetti — Full Analysis Workflow
#  DATA 2D フォルダに新しいデータを追加した後、このファイルを
#  ダブルクリックするだけで全解析を自動実行します。
# ============================================================
#
#  実行内容:
#    STEP 1 — 2D チャンネル動力学解析 (parse_2d_channels.py)
#             → DYNAMICS_ANALYSIS シート更新
#    STEP 2 — パフォーマンス相関解析 (performance_correlation.py)
#             → PERFORMANCE_CORRELATION シート更新
#    STEP 3 — ダッシュボード用JSONエクスポート (sync_dynamics_to_cloud.py)
#             → dynamics_data.json / lap_times_data.json 更新
#
#  出力先: 02_DATABASE/TS24 DB Master.xlsx
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo "  TS24 Puccetti — Full Analysis Workflow"
echo "============================================================"
echo ""
echo "  Script dir : $SCRIPT_DIR"
echo "  Started    : $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── STEP 1: 動力学解析 ────────────────────────────────────────────────
echo "------------------------------------------------------------"
echo "  STEP 1/2 — 2D Channel Dynamics Analysis"
echo "  (APEX / Pit Limiter / Braking Entry → DYNAMICS_ANALYSIS)"
echo "------------------------------------------------------------"
python3 "$SCRIPT_DIR/parse_2d_channels.py"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ STEP 1 failed. Aborting."
    read -p "Press Enter to exit..."
    exit 1
fi

echo ""

# ── STEP 2: パフォーマンス相関解析 ──────────────────────────────────
echo "------------------------------------------------------------"
echo "  STEP 2/2 — Performance Correlation Analysis"
echo "  (Lap Time × Suspension Posture → PERFORMANCE_CORRELATION)"
echo "------------------------------------------------------------"
python3 "$SCRIPT_DIR/performance_correlation.py"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ STEP 2 failed."
    read -p "Press Enter to exit..."
    exit 1
fi

echo ""

# ── STEP 3: JSONエクスポート（Streamlit Cloud用） ─────────────────
echo "------------------------------------------------------------"
echo "  STEP 3/3 — Export JSON for Streamlit Cloud"
echo "  (dynamics_data.json / lap_times_data.json)"
echo "------------------------------------------------------------"
python3 "$SCRIPT_DIR/sync_dynamics_to_cloud.py"

if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️  STEP 3 failed (JSON export). Excel data is still updated."
fi

echo ""
echo "============================================================"
echo "  ✅ All analysis complete!"
echo "  Finished : $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo ""
echo "  Updated files:"
echo "    • TS24 DB Master.xlsx  — DYNAMICS_ANALYSIS / PERFORMANCE_CORRELATION"
echo "    • dynamics_data.json   — Streamlit Cloud 用データ"
echo "    • lap_times_data.json  — Streamlit Cloud 用データ"
echo ""
echo "  ▶ git push origin main を実行するとダッシュボードに反映されます"
echo ""
read -p "Press Enter to exit..."
