#!/usr/bin/env python3
from __future__ import annotations
"""
lap_overlay_extractor.py — TS24 Lap Overlay データ生成
=======================================================
MESファイルから各ラップの時系列データを N点（デフォルト200）に
リサンプルして lap_overlay_data.json に出力する。

出力スキーマ（1ラップ=1エントリ）:
  circuit, rider, session_type, run_no, lap_no, lap_time_s, n_points,
  channels: {lap_progress, speed, brake, gas, sus_f, sus_r}

実行方法:
  python lap_overlay_extractor.py               # 全データ
  python lap_overlay_extractor.py --rider DA77  # DA77のみ
  python lap_overlay_extractor.py --rider JA52
  python lap_overlay_extractor.py --points 300  # リサンプル点数変更
  python lap_overlay_extractor.py --dry-run     # JSON書き込みなし
"""

import sys
import re
import json
import argparse
import importlib.util
from pathlib import Path
from datetime import datetime

import numpy as np

# ── パス設定 ─────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DATA_2D_ROOT = SCRIPT_DIR.parent / "DATA 2D"
JSON_OUT     = SCRIPT_DIR / "lap_overlay_data.json"

DEFAULT_POINTS = 200

# ── parse_2d_channels.py インポート ──────────────────────────────────
_p2d_path = SCRIPT_DIR / "parse_2d_channels.py"
if not _p2d_path.exists():
    print(f"[ERROR] parse_2d_channels.py が見つかりません: {_p2d_path}")
    sys.exit(1)

spec = importlib.util.spec_from_file_location("p2d", _p2d_path)
p2d  = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2d)

parse_hed           = p2d.parse_hed
parse_ddd           = p2d.parse_ddd
parse_lap           = p2d.parse_lap
read_channel        = p2d.read_channel
find_all_mes        = p2d.find_all_mes
_event_key_from_path     = p2d._event_key_from_path
_build_event_meta        = p2d._build_event_meta
_infer_date_for_session  = p2d._infer_date_for_session
MIN_LAP_DURATION_S  = p2d.MIN_LAP_DURATION_S

# ── ラウンド/セッション正規化マップ ──────────────────────────────────
_ROUND_NORM: dict[str, str] = {
    "R01": "ROUND1", "R1": "ROUND1",
    "R02": "ROUND2", "R2": "ROUND2",
    "R03": "ROUND3", "R3": "ROUND3",
    "R04": "ROUND4", "R4": "ROUND4",
    "R05": "ROUND5", "R5": "ROUND5",
    "T01": "TEST1",  "T1": "TEST1",
    "T02": "TEST2",  "T2": "TEST2",
    "T03": "TEST3",  "T3": "TEST3",
    "T04": "TEST4",  "T4": "TEST4",
    "T05": "TEST5",  "T5": "TEST5",
    "T06": "TEST6",  "T6": "TEST6",
    "TEST1": "TEST1", "TEST2": "TEST2", "TEST3": "TEST3",
    "TEST4": "TEST4", "TEST5": "TEST5", "TEST6": "TEST6",
    "WORKSHOP": "WORKSHOP",
}
_SESS_MAP = {
    "FP": "FP", "F1": "FP", "F2": "FP",
    "QP": "QP", "Q1": "QP", "Q2": "QP",
    "WU": "WUP", "WU1": "WUP", "WU2": "WUP",
    "WUP": "WUP", "WUP1": "WUP", "WUP2": "WUP",
    "R1": "RACE1", "R2": "RACE2",
    "RACE1": "RACE1", "RACE2": "RACE2",
    "D1": "TEST_D1", "D2": "TEST_D2",
    "L1": "TEST_D1", "L2": "TEST_D2",
    "SP": "SP", "INLAPR1": "RACE1", "INLAPR2": "RACE2",
}
_CIRC_NORM = {
    "PHILLIPISLAND": "PHILLIP ISLAND",
    "PHILLIPISISLAND": "PHILLIP ISLAND",
    "PHILLIP ISLAND": "PHILLIP ISLAND",
    "PHI": "PHILLIP ISLAND",
    "AUSTRALIA": "PHILLIP ISLAND",
}
_DEFAULT_CIRCUIT = {"PHILLIP ISLAND", "PHILLIPISLAND"}
_DEFAULT_DATE    = "16/02/2026"


def _round2(arr: np.ndarray) -> list[float]:
    """numpy配列を小数2桁のfloatリストに変換（JSON用）"""
    return [round(float(v), 2) for v in arr]


def resample_channel(
    raw: np.ndarray,
    lap_start: int,
    lap_end: int,
    n_points: int,
    ratio: float = 1.0,
) -> np.ndarray:
    """
    ラップ区間のチャンネルデータを n_points 点に均等リサンプル。

    ratio : len(channel) / len(speed_front) の比率
            速度の4倍レートのサスペンションなら ratio=4
    """
    if len(raw) == 0:
        return np.full(n_points, np.nan)

    # チャンネルのラップ区間インデックス
    ch_start = int(lap_start * ratio)
    ch_end   = int(min(lap_end * ratio, len(raw)))
    if ch_end <= ch_start:
        return np.full(n_points, np.nan)

    seg = raw[ch_start:ch_end].astype(np.float64)
    # 元データの正規化時間軸 (0〜1)
    src_x = np.linspace(0.0, 1.0, len(seg))
    # 目標時間軸 (0〜1, n_points点)
    dst_x = np.linspace(0.0, 1.0, n_points)
    return np.interp(dst_x, src_x, seg)


def analyze_mes_overlay(
    mes_path: Path,
    event_meta: dict,
    rider_filter: str | None = None,
    n_points: int = DEFAULT_POINTS,
) -> list[dict]:
    """
    1 MES フォルダから全ラップのオーバーレイデータを返す。
    必須チャンネルが揃わない場合は空リストを返す。
    """
    base = mes_path.name.replace(".MES", "")

    hed = parse_hed(mes_path, base)
    if not hed:
        return []

    # ライダー識別
    rider_num = hed.get("Rider Number", "")
    if "77" in rider_num:
        rider_tag = "DA77"
    elif "52" in rider_num or "JA" in rider_num.upper():
        rider_tag = "JA52"
    else:
        fname_up = mes_path.name.upper()
        par_up   = mes_path.parent.name.upper()
        if "JA52" in fname_up or "52" in fname_up or par_up in ("52", "JA52"):
            rider_tag = "JA52"
        elif "77" in fname_up or "DA77" in fname_up or par_up in ("DA77", "77"):
            rider_tag = "DA77"
        else:
            return []

    if rider_filter and rider_tag != rider_filter:
        return []

    # メタデータ正規化
    _raw_ekey = _event_key_from_path(mes_path)
    event = _ROUND_NORM.get(_raw_ekey or "", "") if _raw_ekey else ""
    if not event:
        hed_event = hed.get("Event", "").strip()
        _m = re.match(r"^(R\d+|T\d+)(?:[^0-9]|$)", hed_event.upper())
        event = _ROUND_NORM.get(_m.group(1) if _m else hed_event.upper(), hed_event)

    fn_prefix_m  = re.match(r"^([A-Za-z0-9]+)", base)
    fn_prefix    = fn_prefix_m.group(1).upper() if fn_prefix_m else ""
    raw_sess     = hed.get("Session", "")
    session_type = _SESS_MAP.get(fn_prefix, _SESS_MAP.get(raw_sess.upper(), raw_sess.upper() or fn_prefix))

    run_match = re.search(r"-(\d+)$", base)
    run_no    = int(run_match.group(1)) if run_match else int(hed.get("Run", "1") or 1)

    circuit = hed.get("Circuit", "").upper()
    date_s  = hed.get("Date", "")
    if re.match(r"^\d{2}\.\d{4}$", date_s):
        yy, mmdd = date_s[:2], date_s[3:]
        date_s = f"{mmdd[2:]}/{mmdd[:2]}/20{yy}"

    date_fmt = date_s
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            date_fmt = datetime.strptime(date_s, fmt).strftime("%Y-%m-%d")
            break
        except Exception:
            continue

    # JA52 デフォルト HED 補完
    is_default = (
        (circuit in _DEFAULT_CIRCUIT and date_s == _DEFAULT_DATE
         and raw_sess.upper() in ("L1", "L2", "")) or circuit in ("", "?")
    )
    if is_default and event_meta:
        ekey = _event_key_from_path(mes_path)
        if ekey and ekey in event_meta:
            em = event_meta[ekey]
            nc = em.get("circuit", "").strip()
            if nc:
                circuit = nc
            nd = _infer_date_for_session(fn_prefix, em.get("session_dates", {}))
            if nd:
                date_fmt = nd
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
                    try:
                        date_fmt = datetime.strptime(nd, fmt).strftime("%Y-%m-%d")
                        break
                    except Exception:
                        continue

    circuit = _CIRC_NORM.get(circuit.upper().strip(), circuit.upper().strip())

    # ── チャンネル読み込み ────────────────────────────────────────────
    chs = parse_ddd(mes_path, base)
    if "SPEED_FRONT" not in chs or not chs["SPEED_FRONT"].get("ext"):
        return []

    sf_raw    = read_channel(mes_path, base, chs["SPEED_FRONT"])    # km/h (基準)
    if len(sf_raw) < 10:
        return []

    # オプションチャンネル（各比率計算）
    sus_f_raw = np.array([], dtype=np.float32)
    sus_r_raw = np.array([], dtype=np.float32)
    brake_raw = np.array([], dtype=np.float32)
    gas_raw   = np.array([], dtype=np.float32)

    if "SUSP_FRONT" in chs and chs["SUSP_FRONT"].get("ext"):
        sus_f_raw = read_channel(mes_path, base, chs["SUSP_FRONT"])
    if "SUSP_REAR" in chs and chs["SUSP_REAR"].get("ext"):
        sus_r_raw = read_channel(mes_path, base, chs["SUSP_REAR"])

    brake_ch = next((k for k in chs if k.upper() == "BRAKE_FRONT" and chs[k].get("ext")), None)
    if brake_ch:
        brake_raw = read_channel(mes_path, base, chs[brake_ch])

    gas_ch = next(
        (k for k in ("GAS_SMOOTH", "GAS", "TPS_A", "TPS") if k in chs and chs[k].get("ext")),
        None,
    )
    if gas_ch:
        gas_raw = read_channel(mes_path, base, chs[gas_ch])

    # サンプルレート比
    def _ratio(arr):
        if len(arr) == 0 or len(sf_raw) == 0:
            return 1.0
        return len(arr) / len(sf_raw)

    susp_ratio  = _ratio(sus_f_raw)
    brake_ratio = _ratio(brake_raw)
    gas_ratio   = _ratio(gas_raw)

    # ── ラップ境界 ────────────────────────────────────────────────────
    n_laps, lap_times_ms = parse_lap(mes_path, base)
    if n_laps > 0 and lap_times_ms:
        total_ms = lap_times_ms[-1]
        sr = len(sf_raw) / (total_ms / 1000.0) if total_ms > 0 else 100.0
    else:
        sr = 100.0
    sr = max(10.0, min(sr, 500.0))

    if n_laps > 0 and lap_times_ms:
        boundaries = []
        prev_ms = 0
        for t_ms in lap_times_ms:
            s_idx   = int(prev_ms / 1000.0 * sr)
            e_idx   = int(t_ms   / 1000.0 * sr)
            lap_t_s = (t_ms - prev_ms) / 1000.0
            boundaries.append((s_idx, min(e_idx, len(sf_raw) - 1), lap_t_s))
            prev_ms = t_ms
    else:
        dur_s = len(sf_raw) / sr
        boundaries = [(0, len(sf_raw) - 1, dur_s)]

    lap_progress = np.linspace(0.0, 1.0, n_points)

    results = []
    for lap_idx, (lap_start, lap_end, lap_t_s) in enumerate(boundaries):
        lap_no = lap_idx + 1

        if lap_t_s < MIN_LAP_DURATION_S:
            continue
        if lap_end - lap_start < n_points:
            continue

        # 各チャンネルをリサンプル
        speed_resampled  = resample_channel(sf_raw,    lap_start, lap_end, n_points, 1.0)
        brake_resampled  = resample_channel(brake_raw, lap_start, lap_end, n_points, brake_ratio)
        gas_resampled    = resample_channel(gas_raw,   lap_start, lap_end, n_points, gas_ratio)
        sus_f_resampled  = resample_channel(sus_f_raw, lap_start, lap_end, n_points, susp_ratio)
        sus_r_resampled  = resample_channel(sus_r_raw, lap_start, lap_end, n_points, susp_ratio)

        # 物理的クランプ (ノイズ除去)
        speed_resampled  = np.clip(speed_resampled, 0.0, 350.0)
        brake_resampled  = np.clip(brake_resampled, 0.0, 30.0)
        gas_resampled    = np.clip(gas_resampled,   0.0, 105.0)
        sus_f_resampled  = np.clip(sus_f_resampled, 0.0, 200.0)
        sus_r_resampled  = np.clip(sus_r_resampled, 0.0, 200.0)

        results.append({
            "circuit":           circuit,
            "round":             event,
            "date":              date_fmt,
            "rider":             rider_tag,
            "session_type":      session_type,
            "run_no":            run_no,
            "lap_no":            lap_no,
            "lap_time_s":        round(lap_t_s, 3),
            "n_points":          n_points,
            "lap_distance_m":    None,   # GPS実装後に有効化
            "distance_progress": None,   # GPS実装後に有効化
            "channels": {
                "lap_progress": _round2(lap_progress),
                "speed":        _round2(speed_resampled),
                "brake":        _round2(brake_resampled),
                "gas":          _round2(gas_resampled),
                "sus_f":        _round2(sus_f_resampled),
                "sus_r":        _round2(sus_r_resampled),
            },
        })

    return results


# ── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Lap Overlay Extractor")
    parser.add_argument("--rider",   choices=["DA77", "JA52"], help="ライダーフィルター")
    parser.add_argument("--points",  type=int, default=DEFAULT_POINTS, help="リサンプル点数")
    parser.add_argument("--dry-run", action="store_true", help="JSON書き込みなし")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  TS24 Puccetti — Lap Overlay Extractor ({args.points} points)")
    print("=" * 60)

    if not DATA_2D_ROOT.exists():
        print(f"\n❌ DATA 2D フォルダが見つかりません: {DATA_2D_ROOT}")
        sys.exit(1)

    mes_list = find_all_mes(DATA_2D_ROOT)
    print(f"\n📂 Found {len(mes_list)} MES folders")

    print("🔍 Building event metadata...")
    event_meta = _build_event_meta(DATA_2D_ROOT)
    print(f"   → {len(event_meta)} events: {sorted(event_meta.keys())}")

    all_rows = []
    n_laps   = 0
    errors   = []

    for i, mes in enumerate(mes_list, 1):
        label = f"{mes.parent.name}/{mes.name}"
        print(f"  [{i:3d}/{len(mes_list)}] {label} ... ", end="", flush=True)
        try:
            rows = analyze_mes_overlay(mes, event_meta, args.rider, args.points)
            if rows:
                n_laps += len(rows)
                all_rows.extend(rows)
                print(f"✅ {len(rows)} laps")
            else:
                print("⏭ skipped")
        except Exception as e:
            errors.append((label, str(e)))
            print(f"⚠️  {e}")

    print(f"\n✅ Total: {n_laps} laps extracted")

    if not all_rows:
        print("\n⚠️  データなし")
        return

    if args.dry_run:
        print("\n[dry-run] JSON 書き込みをスキップ")
        s = all_rows[0]
        print(f"  Sample: {s['circuit']} {s['rider']} {s['session_type']} Lap{s['lap_no']}")
        print(f"  Points: {s['n_points']}")
        sp = s['channels']['speed']
        su = s['channels']['sus_f']
        print(f"  Speed range: {min(sp):.0f}〜{max(sp):.0f} km/h")
        print(f"  SusF range:  {min(su):.1f}〜{max(su):.1f} mm")
    else:
        JSON_OUT.write_text(
            json.dumps(all_rows, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        size_mb = JSON_OUT.stat().st_size / 1_048_576
        print(f"\n📄 Written: {JSON_OUT}")
        print(f"   {n_laps} laps × {args.points} points × 6 channels  ({size_mb:.1f} MB)")

    if errors:
        print(f"\n⚠️  {len(errors)} errors:")
        for path, msg in errors[:10]:
            print(f"   {path}: {msg}")


if __name__ == "__main__":
    main()
