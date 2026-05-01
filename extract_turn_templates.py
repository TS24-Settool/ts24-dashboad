#!/usr/bin/env python3
from __future__ import annotations
"""
extract_turn_templates.py — TS24 Turn Template Extractor
=========================================================
corner_phase_data.json から各サーキットの Turn 定義テンプレートを生成し
turn_templates.json に出力する。

【設計原則】
コーナーは「検出するもの」ではなく「定義するもの」。
このスクリプトが生成した draft は必ず手動検証を行ってから使用すること
（manual_validated: true に変更してコミット）。

出力スキーマ:
{
  "ASSEN": {
    "n_turns": 18,
    "source": "brake_cluster_extracted_2026-05-01",
    "manual_validated": false,
    "note": "Manual validation required before use in official analysis.",
    "turns": [
      {"turn": "T1", "cid_src": "C01", "progress": 0.0452, "confidence": "中"},
      ...
    ]
  }
}

実行方法:
  python extract_turn_templates.py               # 全サーキット
  python extract_turn_templates.py --circuit ASSEN
  python extract_turn_templates.py --dry-run     # JSON書き込みなし
"""

import sys
import json
import argparse
import statistics
from pathlib import Path
from datetime import date
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
CP_JSON    = SCRIPT_DIR / "corner_phase_data.json"
OUT_JSON   = SCRIPT_DIR / "turn_templates.json"

# 既存テンプレートを読み込んで manual_validated を保持するために使用
_EXISTING: dict = {}


def _cid(cno: int) -> str:
    return f"C{cno:02d}"


def _turn(cno: int) -> str:
    return f"T{cno}"


def build_circuit_template(
    circuit: str,
    cp_rows: list[dict],
    today: str,
) -> dict:
    """
    corner_phase_data の1サーキット分から Turn テンプレートを生成する。

    アルゴリズム:
    1. 各ラップの全コーナーの累積時間位置 → lap_progress を計算
    2. 同じ corner_no のラップ間中央値で progress を代表値とする
    3. ラップ数が多いほどconfidenceを上げる
    """
    # ラップ別にコーナー progress を計算
    # {(run_no, lap_no): [(corner_no, progress), ...]}
    lap_corners: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    lap_times: dict[tuple, float] = {}

    for row in cp_rows:
        key = (row.get("run_no", 0), row.get("lap_no", 0))
        lap_times[key] = row.get("lap_time_s", 0.0) or 0.0

    # まず各ラップの全コーナーを収集
    laps_grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in cp_rows:
        key = (row.get("run_no", 0), row.get("lap_no", 0))
        laps_grouped[key].append(row)

    # 各ラップ→各コーナーの brake_peak_progress を計算
    for key, rows in laps_grouped.items():
        lt_s = lap_times.get(key, 0.0)
        if lt_s < 30.0:
            continue
        sorted_rows = sorted(rows, key=lambda r: r.get("corner_no", 0))
        cum_ms = 0.0
        for row in sorted_rows:
            cno  = int(row.get("corner_no", 0))
            ph12 = row.get("ph12_duration_ms") or 0
            prog = min(1.0, (cum_ms + ph12) / (lt_s * 1000))
            lap_corners[key].append((cno, prog))
            cum_ms += (row.get("total_corner_ms") or 0)

    # コーナーNo別に progress の中央値・標準偏差を計算
    by_corner: dict[int, list[float]] = defaultdict(list)
    for laps_data in lap_corners.values():
        for cno, prog in laps_data:
            by_corner[cno].append(prog)

    # Turn テンプレート生成
    turns = []
    for cno in sorted(by_corner.keys()):
        progs = by_corner[cno]
        n     = len(progs)
        med   = round(statistics.median(progs), 4)
        stdev = round(statistics.stdev(progs), 4) if n >= 2 else 0.0

        # confidence: 多くのラップで安定して検出 = 高
        if n >= 10 and stdev < 0.02:
            conf = "高"
        elif n >= 5 and stdev < 0.05:
            conf = "中"
        else:
            conf = "低"

        turns.append({
            "turn":       _turn(cno),
            "cid_src":    _cid(cno),
            "progress":   med,
            "confidence": conf,
            "n_laps":     n,
            "stdev":      stdev,
        })

    # 既存テンプレートの manual_validated を保持
    existing_validated = _EXISTING.get(circuit, {}).get("manual_validated", False)

    return {
        "n_turns":         len(turns),
        "source":          f"brake_cluster_extracted_{today}",
        "manual_validated": existing_validated,
        "note":            (
            "Manual validation required before use in official analysis. "
            "GPS-based update planned. "
            "Set manual_validated: true after verifying Turn positions on track map."
        ),
        "turns": turns,
    }


def main():
    parser = argparse.ArgumentParser(description="Turn Template Extractor")
    parser.add_argument("--circuit", help="サーキット名でフィルター")
    parser.add_argument("--dry-run", action="store_true", help="JSON書き込みなし")
    args = parser.parse_args()

    print("=" * 60)
    print("  TS24 Turn Template Extractor")
    print("=" * 60)

    if not CP_JSON.exists():
        print(f"❌ corner_phase_data.json が見つかりません: {CP_JSON}")
        sys.exit(1)

    cp_data = json.loads(CP_JSON.read_text(encoding="utf-8"))

    # 既存テンプレートを読み込む（manual_validated 保持のため）
    global _EXISTING
    if OUT_JSON.exists():
        try:
            _EXISTING = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            _EXISTING = {}

    today = date.today().isoformat()

    # サーキット別グループ化
    by_circuit: dict[str, list[dict]] = defaultdict(list)
    for row in cp_data:
        c = row.get("circuit", "")
        if c:
            by_circuit[c].append(row)

    if args.circuit:
        circuits = [c for c in by_circuit if c == args.circuit]
        if not circuits:
            print(f"❌ サーキット '{args.circuit}' のデータが見つかりません")
            print(f"   利用可能: {sorted(by_circuit.keys())}")
            sys.exit(1)
    else:
        circuits = sorted(by_circuit.keys())

    templates: dict = {}
    for circ in circuits:
        rows = by_circuit[circ]
        tmpl = build_circuit_template(circ, rows, today)
        templates[circ] = tmpl
        validated_str = "✅ validated" if tmpl["manual_validated"] else "⚠️  NOT validated"
        print(f"  {circ:20s}: {tmpl['n_turns']:3d} turns  {validated_str}  "
              f"[high:{sum(1 for t in tmpl['turns'] if t['confidence']=='高')} "
              f"mid:{sum(1 for t in tmpl['turns'] if t['confidence']=='中')} "
              f"low:{sum(1 for t in tmpl['turns'] if t['confidence']=='低')}]")

    if args.dry_run:
        print("\n[dry-run] JSON 書き込みをスキップ")
        sample = next(iter(templates.values()), {})
        if sample.get("turns"):
            print(f"  sample turn: {sample['turns'][0]}")
        return

    # 既存テンプレートとマージ（指定サーキットのみ上書き、他は保持）
    merged = dict(_EXISTING)
    merged.update(templates)

    OUT_JSON.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n📄 Written: {OUT_JSON}  ({len(merged)} circuits)")
    print("\n⚠️  重要: manual_validated はすべて false です。")
    print("   実際のコーナー位置を確認後、該当サーキットの manual_validated を true に変更してください。")


if __name__ == "__main__":
    main()
