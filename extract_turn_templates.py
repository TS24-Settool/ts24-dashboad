#!/usr/bin/env python3
from __future__ import annotations
"""
extract_turn_templates.py — TS24 Turn Template Extractor  (v2)
=============================================================
corner_phase_data.json から各サーキットの Turn 定義テンプレートを生成し
turn_templates.json に出力する。

【v2の修正点】
- corner_no ごとに「何ラップで検出されたか（coverage）」を集計してデデュープ
- coverage < 閾値（max_laps の 15%）のコーナーは除外（outlier 抑制）
- median_corners_per_lap > 30 のサーキットは検出品質不良フラグ付きで出力

【設計原則】
  コーナーは「検出するもの」ではなく「定義するもの」
  → このスクリプトが生成した draft は必ず手動検証を行うこと
  → manual_validated: true に変更してコミットする前にコーナー数を照合すること

実行方法:
  python extract_turn_templates.py               # 全サーキット
  python extract_turn_templates.py --circuit ASSEN
  python extract_turn_templates.py --dry-run
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

# median_corners_per_lap がこの値を超える場合、検出品質不良と判断
POOR_QUALITY_THRESHOLD = 30
# 正常品質サーキットの coverage threshold (max_count の何割以上)
MIN_COVERAGE_FRAC      = 0.15
# 最低 coverage サンプル数 (絶対値)
MIN_COVERAGE_ABS       = 3

# 期待Turn数（確認用表示のみ、フィルタには使用しない）
EXPECTED_TURNS = {
    "ASSEN":          18,
    "CREMONA":        10,
    "JEREZ":          13,
    "PHILLIP ISLAND": 12,
    "PORTIMAO":       15,
}


def build_circuit_template(
    circuit: str,
    rows: list[dict],
    today: str,
    existing: dict,
) -> dict:
    """1サーキット分の corner_phase_data から Turn テンプレートを生成する。"""

    # ── ラップ識別（rider + run_no + lap_no で一意）─────────────────
    by_lap: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (row.get("rider", ""), row.get("run_no", 0), row.get("lap_no", 0))
        by_lap[key].append(row)

    n_laps = len(by_lap)
    if n_laps == 0:
        return {}

    # ── ラップごとのコーナー数を集計（品質判定用）──────────────────
    lap_max_cno = [
        max((r.get("corner_no", 0) for r in lap_rows), default=0)
        for lap_rows in by_lap.values()
    ]
    median_corners_per_lap = statistics.median(lap_max_cno)

    # ── corner_no ごとのラップカバレッジを集計 ─────────────────────
    # cno → [progress_value, ...]  (progress = 累積時間/laptime)
    by_corner: dict[int, list[float]] = defaultdict(list)

    for lap_rows in by_lap.values():
        lt_s = lap_rows[0].get("lap_time_s", 0.0) or 0.0
        if lt_s < 30.0:
            continue
        sorted_rows = sorted(lap_rows, key=lambda r: r.get("corner_no", 0))
        cum_ms = 0.0
        for row in sorted_rows:
            cno  = int(row.get("corner_no", 0))
            ph12 = row.get("ph12_duration_ms") or 0
            prog = min(1.0, (cum_ms + ph12) / (lt_s * 1000))
            by_corner[cno].append(prog)
            cum_ms += (row.get("total_corner_ms") or 0)

    if not by_corner:
        return {}

    max_count = max(len(v) for v in by_corner.values())

    # ── 検出品質フラグ ──────────────────────────────────────────────
    is_poor_quality = (median_corners_per_lap > POOR_QUALITY_THRESHOLD)
    threshold = max(
        MIN_COVERAGE_ABS,
        int(max_count * MIN_COVERAGE_FRAC),
    )

    if is_poor_quality:
        # 品質不良: 閾値を大幅に上げてノイズを除外
        threshold = max(threshold, int(max_count * 0.70))
        note = (
            f"⚠️ 検出品質不良: median {median_corners_per_lap:.0f} corners/lap "
            f"(expected ~{EXPECTED_TURNS.get(circuit, '?')}) — "
            "ブレーキベース検出が過検出しています。手動マッピング推奨。"
        )
    else:
        note = (
            "自動抽出 draft。Turn数が実際のサーキットコーナー数と一致しない可能性があります。"
            f"manual_validated: true にする前に実際のコーナー数"
            f"（期待値 ~{EXPECTED_TURNS.get(circuit, '?')}）と照合してください。"
        )

    # ── Turn リスト生成（coverage >= threshold のみ）─────────────────
    turns = []
    for cno in sorted(by_corner.keys()):
        progs = by_corner[cno]
        count = len(progs)
        if count < threshold:
            continue
        med_prog = statistics.median(progs)
        frac     = count / max_count

        if frac >= 0.80:
            conf = "高"
        elif frac >= 0.50:
            conf = "中"
        else:
            conf = "低"

        turns.append({
            "turn":       f"T{cno}",
            "cid_src":    f"C{cno:02d}",
            "progress":   round(med_prog, 4),
            "confidence": conf,
            "n_laps":     count,
        })

    # ── 既存テンプレートの manual_validated を保持 ─────────────────
    was_validated = existing.get(circuit, {}).get("manual_validated", False)

    return {
        "n_turns":                  len(turns),
        "median_corners_per_lap":   round(median_corners_per_lap, 1),
        "detection_quality":        "poor" if is_poor_quality else "acceptable",
        "source":                   f"brake_cluster_extracted_{today}",
        "manual_validated":         was_validated,
        "note":                     note,
        "turns":                    turns,
    }


def main():
    parser = argparse.ArgumentParser(description="Turn Template Extractor v2")
    parser.add_argument("--circuit",  help="サーキット名でフィルター")
    parser.add_argument("--dry-run",  action="store_true", help="JSON書き込みなし")
    args = parser.parse_args()

    print("=" * 60)
    print("  TS24 Turn Template Extractor v2")
    print("=" * 60)

    if not CP_JSON.exists():
        print(f"❌ corner_phase_data.json が見つかりません: {CP_JSON}")
        sys.exit(1)

    cp_data = json.loads(CP_JSON.read_text(encoding="utf-8"))
    today   = date.today().isoformat()

    existing: dict = {}
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass

    # サーキット別グループ化
    by_circuit: dict[str, list[dict]] = defaultdict(list)
    for row in cp_data:
        c = row.get("circuit", "")
        if c:
            by_circuit[c].append(row)

    circuits = (
        [c for c in by_circuit if c == args.circuit]
        if args.circuit
        else sorted(by_circuit.keys())
    )
    if args.circuit and not circuits:
        print(f"❌ '{args.circuit}' のデータが見つかりません")
        print(f"   利用可能: {sorted(by_circuit.keys())}")
        sys.exit(1)

    templates: dict = {}
    print()
    for circ in circuits:
        tmpl = build_circuit_template(circ, by_circuit[circ], today, existing)
        if not tmpl:
            continue
        templates[circ] = tmpl

        expected = EXPECTED_TURNS.get(circ, "?")
        n        = tmpl["n_turns"]
        ok       = "✅" if (isinstance(expected, int) and abs(n - expected) <= 3) else "⚠️ "
        qual     = "🔴 POOR" if tmpl["detection_quality"] == "poor" else "🟢 OK  "
        validated = "✅ validated" if tmpl["manual_validated"] else "⚠️  NOT validated"

        print(f"  {ok} {circ:20s}: {n:3d} turns "
              f"(expected ~{expected:3})  "
              f"{qual}  med={tmpl['median_corners_per_lap']:.0f}/lap  "
              f"{validated}")

    if args.dry_run:
        print("\n[dry-run] JSON 書き込みをスキップ")
        for circ, tmpl in list(templates.items())[:2]:
            print(f"\n  {circ} first 5 turns:")
            for t in tmpl["turns"][:5]:
                print(f"    {t['turn']:4s} prog={t['progress']:.4f}  "
                      f"conf={t['confidence']}  n_laps={t['n_laps']}")
        return

    merged = dict(existing)
    merged.update(templates)
    _json_text = json.dumps(merged, ensure_ascii=False, indent=2)
    for _jout in [OUT_JSON, OUT_JSON.parent.parent / "06_DASHBOARD" / OUT_JSON.name]:
        if _jout.parent.exists():
            _jout.write_text(_json_text, encoding="utf-8")
            print(f"\n📄 Written: {_jout}  ({len(merged)} circuits)")
    print("\n⚠️  全サーキット manual_validated: false")
    print("   サーキットマップで確認後、対象サーキットの manual_validated を true に変更してください。")


if __name__ == "__main__":
    main()
