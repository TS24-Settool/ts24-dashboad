#!/usr/bin/env python3
"""
sync_dynamics_to_cloud.py — TS24 Puccetti
DYNAMICS_ANALYSIS と LAP_TIMES を JSON にエクスポートして GitHub にコミット。
Streamlit Cloud はこの JSON を読み込む。

実行: python3 sync_dynamics_to_cloud.py
"""
import json
import pandas as pd
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
EXCEL_PATH = SCRIPT_DIR.parent / "02_DATABASE" / "TS24 DB Master.xlsx"
OUT_DYN    = SCRIPT_DIR / "dynamics_data.json"
OUT_LT     = SCRIPT_DIR / "lap_times_data.json"

if not EXCEL_PATH.exists():
    print(f"❌ Excel not found: {EXCEL_PATH}")
    raise SystemExit(1)

# ── DYNAMICS_ANALYSIS ───────────────────────────────────────
df_dyn = pd.read_excel(str(EXCEL_PATH), sheet_name="DYNAMICS_ANALYSIS", header=1)
df_dyn = df_dyn.dropna(subset=["Rider"]).reset_index(drop=True)
df_dyn["Date"] = df_dyn["Date"].astype(str)
OUT_DYN.write_text(df_dyn.to_json(orient="records", force_ascii=False), encoding="utf-8")
print(f"✅ dynamics_data.json : {len(df_dyn)} rows")

# ── LAP_TIMES ───────────────────────────────────────────────
df_lt = pd.read_excel(str(EXCEL_PATH), sheet_name="LAP_TIMES", header=1)
df_lt = df_lt.dropna(how="all").reset_index(drop=True)
df_lt["DATE"] = df_lt["DATE"].astype(str)
OUT_LT.write_text(df_lt.to_json(orient="records", force_ascii=False), encoding="utf-8")
print(f"✅ lap_times_data.json: {len(df_lt)} rows")

print("\n  → これらのファイルを git add / commit / push して Streamlit Cloud に反映してください。")
