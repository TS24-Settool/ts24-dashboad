#!/usr/bin/env python3
from __future__ import annotations
"""
corner_phase_analysis.py — TS24 Corner Phase Timing Analysis
=============================================================
各ラップの各コーナーで PH1-2 / PH3 / PH4-5 の区間時間(ms)を算出し
corner_phase_data.json に出力する。

フェーズ定義:
  PH1-2: BRAKE_FRONT が 0.3bar を最初に超えた点 → APEX start 直前（最大3秒遡る）
  PH3:   detect_apex_area() の start〜end（5条件同時成立区間）
  PH4-5: APEX end → GAS が 6% を連続5サンプル以上超えた最初の点（最大4秒先）

実行方法:
  python corner_phase_analysis.py               ← 全 MES 処理
  python corner_phase_analysis.py --rider DA77  ← DA77 のみ
  python corner_phase_analysis.py --rider JA52
  python corner_phase_analysis.py --dry-run     ← JSON 書き込みなし
"""

import sys
import re
import math
import json
import argparse
import importlib.util
from pathlib import Path
from datetime import datetime

import numpy as np

# ── パス設定 ─────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DATA_2D_ROOT = SCRIPT_DIR.parent / "DATA 2D"
JSON_OUT     = SCRIPT_DIR / "corner_phase_data.json"

# ── parse_2d_channels.py からインポート ──────────────────────────────
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
detect_apex_area    = p2d.detect_apex_area
find_all_mes        = p2d.find_all_mes
_event_key_from_path= p2d._event_key_from_path
_build_event_meta   = p2d._build_event_meta
_infer_date_for_session = p2d._infer_date_for_session
MIN_LAP_DURATION_S  = p2d.MIN_LAP_DURATION_S

# ── ラウンド正規化マップ ──────────────────────────────────────────────
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

# ── フェーズ検出パラメータ ────────────────────────────────────────────
PH12_BRAKE_THRESHOLD  = 0.3    # Bar — ブレーキ開始判定閾値
PH12_MAX_LOOKBACK_S   = 5.0    # 秒 — 最大遡り時間 (3→5s に拡大)
PH45_GAS_THRESHOLD    = 6.0    # % — アクセルON判定閾値
PH45_CONSEC_SAMPLES   = 5      # 連続サンプル数（GAS条件）
PH45_MAX_LOOKAHEAD_S  = 4.0    # 秒 — 最大先読み時間

# フォールバックコーナー検出パラメータ
FB_BRAKE_THRESHOLD    = 0.5    # Bar — フォールバック用ブレーキ閾値
FB_MIN_BRAKE_DUR_S    = 0.1    # 秒 — 最小ブレーキ持続時間
FB_SPEED_SEARCH_S     = 4.0    # 秒 — ブレーキ後の速度最小点探索範囲
FB_APEX_HALF_S        = 0.2    # 秒 — 速度最小点前後の PH3 ウィンドウ
FB_MIN_GAP_S          = 1.5    # 秒 — 隣接コーナーの最小間隔
# 5条件APEXが不十分と判断する閾値（フォールバック適用条件）
FB_FALLBACK_RATIO     = 0.5    # 5条件数 < ブレーキ検出数 * この割合 でフォールバック
FB_FALLBACK_MIN       = 5      # 長いラップ(>80s)でこの数以下ならフォールバック


def _safe_mean(arr: np.ndarray) -> float | None:
    if arr is None or len(arr) == 0:
        return None
    v = arr[~np.isnan(arr)]
    return round(float(np.mean(v)), 2) if len(v) > 0 else None


def _safe_min(arr: np.ndarray) -> float | None:
    if arr is None or len(arr) == 0:
        return None
    v = arr[~np.isnan(arr)]
    return round(float(np.min(v)), 2) if len(v) > 0 else None


def _safe_max(arr: np.ndarray) -> float | None:
    if arr is None or len(arr) == 0:
        return None
    v = arr[~np.isnan(arr)]
    return round(float(np.max(v)), 2) if len(v) > 0 else None


# ── ブレーキベースのフォールバックコーナー検出 ─────────────────────────
def detect_corners_brake_based(
    brake_lap: np.ndarray,   # ラップスライス済み BRAKE_FRONT (brake_f rate)
    sf_lap: np.ndarray,      # ラップスライス済み SPEED_FRONT (speed rate)
    sus_f_lap: np.ndarray,   # ラップスライス済み SUSP_FRONT (sus_ratio * speed rate)
    sus_r_lap: np.ndarray,   # ラップスライス済み SUSP_REAR
    sr: float,               # speed サンプルレート [Hz]
    brake_scale: float,      # len(brake_f_raw) / len(sf_raw)
    sus_ratio: int,          # susp/speed サンプル比
) -> list[dict]:
    """
    BRAKE_FRONT > 0.5 bar イベント後の速度最小点を各コーナーAPEXとし、
    ±0.2 秒を PH3 ウィンドウとして返す。

    5条件同時成立APEX検出のフォールバック。
    戻り値フォーマットは detect_apex_area() と同一。
    """
    n_brake = len(brake_lap)
    n_sf    = len(sf_lap)
    n_sus_f = len(sus_f_lap)
    n_sus_r = len(sus_r_lap)

    if n_brake == 0 or n_sf == 0:
        return []

    min_brake_samples = max(3, int(FB_MIN_BRAKE_DUR_S * sr * brake_scale))
    min_gap_brake     = max(5, int(FB_MIN_GAP_S * sr * brake_scale))
    half_apex_brake   = max(1, int(FB_APEX_HALF_S * sr * brake_scale))
    spd_search_spls   = max(10, int(FB_SPEED_SEARCH_S * sr))  # speed 空間

    # ブレーキイベント検出
    in_brake = (brake_lap > FB_BRAKE_THRESHOLD).astype(np.int8)
    changes  = np.diff(in_brake, prepend=0, append=0)
    starts   = np.where(changes == 1)[0]
    ends     = np.where(changes == -1)[0]

    corners   = []
    last_apex = -min_gap_brake

    for b_s, b_e in zip(starts, ends):
        if (b_e - b_s) < min_brake_samples:
            continue

        # ブレーキピーク → speed 空間に変換
        b_peak = int(np.argmax(brake_lap[b_s:b_e])) + b_s
        spd_peak = max(0, min(n_sf - 1, int(b_peak / brake_scale)))

        # ブレーキピーク後の速度最小点を探す
        spd_end = min(n_sf, spd_peak + spd_search_spls)
        if spd_end <= spd_peak:
            continue
        spd_min_local = int(np.argmin(sf_lap[spd_peak:spd_end])) + spd_peak

        # speed → brake_f 空間に戻す
        apex_bf = max(0, min(n_brake - 1, int(spd_min_local * brake_scale)))

        # 最小間隔チェック
        if apex_bf - last_apex < min_gap_brake:
            continue

        # PH3 ウィンドウ (速度最小点 ± 0.2秒)
        ph3_s = max(0, apex_bf - half_apex_brake)
        ph3_e = min(n_brake - 1, apex_bf + half_apex_brake)

        # SusF/SusR 平均
        sus_i0 = ph3_s * sus_ratio
        sus_i1 = (ph3_e + 1) * sus_ratio
        susF_seg = sus_f_lap[sus_i0:min(sus_i1, n_sus_f)]
        susR_seg = sus_r_lap[sus_i0:min(sus_i1, n_sus_r)] if n_sus_r > 0 else np.array([])

        susF_avg = float(np.mean(susF_seg)) if len(susF_seg) > 0 else float("nan")
        susR_avg = float(np.mean(susR_seg)) if len(susR_seg) > 0 else float("nan")

        corners.append({
            "start":    ph3_s,
            "end":      ph3_e,
            "mid":      apex_bf,
            "susF_avg": susF_avg,
            "susR_avg": susR_avg,
        })
        last_apex = apex_bf

    return corners


# ── コーナーフェーズ検出 ─────────────────────────────────────────────
def analyze_corner_phases(
    apex: dict,            # detect_apex_area() が返す1コーナー分: {start,end,mid,susF_avg,susR_avg}
    brake_lap: np.ndarray, # ラップスライス済み BRAKE_FRONT (brake_f rate)
    gas_lap: np.ndarray,   # ラップスライス済み GAS (gas_ratio * brake_f rate)
    sus_f_lap: np.ndarray, # ラップスライス済み SUSP_FRONT (sus_ratio * brake_f rate)
    sus_r_lap: np.ndarray, # ラップスライス済み SUSP_REAR
    sf_raw: np.ndarray,    # 全ラン SPEED_FRONT (speed rate)
    lap_start: int,        # speed_raw のラップ開始グローバルインデックス
    lap_end: int,
    sr: float,             # speed サンプルレート [Hz]
    brake_scale: float,    # len(brake_f_raw) / len(sf_raw)
    gas_ratio: int,        # gas samples per speed sample
    sus_ratio: int,        # susp samples per speed sample
    time_per_sample: float,# 秒/speed sample = 1/sr
) -> dict:
    """
    1つの APEX area (detect_apex_area の返値1エントリ) から
    PH1-2 / PH3 / PH4-5 を計算して辞書で返す。

    apex.start / apex.end はすべて brake_lap の ローカルインデックス空間。
    """
    n_brake = len(brake_lap)
    n_gas   = len(gas_lap)
    n_sus_f = len(sus_f_lap)
    n_sus_r = len(sus_r_lap)

    # 有効サンプル時間 (brake_f スペースでの1サンプル duration)
    # time_per_sample は speed スペース → brake スペースは speed の 1/brake_scale 倍
    dt_brake = time_per_sample / max(brake_scale, 1e-6)  # sec per brake sample

    # ── PH3 (APEX area 自体) ─────────────────────────────────────────
    ph3_start = apex["start"]
    ph3_end   = apex["end"]
    ph3_samples = max(0, ph3_end - ph3_start + 1)
    ph3_duration_ms = round(ph3_samples * dt_brake * 1000, 1)

    # PH3 suspension (直接 detect_apex_area の集計値を使用)
    ph3_susf_avg = round(apex["susF_avg"], 2) if not math.isnan(apex["susF_avg"]) else None
    ph3_susr_avg = round(apex["susR_avg"], 2) if not math.isnan(apex["susR_avg"]) else None

    # PH3 speed min (brake_f → speed 変換)
    # global speed index: int((b_lap_global + i) / brake_scale)
    # b_lap_global = lap_start * brake_scale (approx, using brake_scale)
    b_global_ph3_start = int(ph3_start / brake_scale) + lap_start
    b_global_ph3_end   = int(ph3_end   / brake_scale) + lap_start + 1
    b_global_ph3_start = max(lap_start, min(b_global_ph3_start, lap_end - 1))
    b_global_ph3_end   = max(b_global_ph3_start + 1, min(b_global_ph3_end, lap_end))
    _spd_min_raw = _safe_min(sf_raw[b_global_ph3_start:b_global_ph3_end])
    ph3_speed_min = max(0.0, _spd_min_raw) if _spd_min_raw is not None else None

    # ── PH1-2 (apex.start の手前: ブレーキ開始 → APEX start) ─────────
    max_back = max(1, int(PH12_MAX_LOOKBACK_S * sr * brake_scale))
    search_from = max(0, ph3_start - max_back)
    ph12_start  = ph3_start  # デフォルト: ブレーキなし

    # 2段階サーチ:
    # Step1: APEX直前の coast 区間 (brake ≤ threshold) をスキップ
    # Step2: その前のブレーキ区間 (brake > threshold) の開始点を探す
    brake_zone_end = ph3_start - 1
    while brake_zone_end >= search_from and brake_lap[brake_zone_end] <= PH12_BRAKE_THRESHOLD:
        brake_zone_end -= 1

    if brake_zone_end >= search_from:
        # brake > threshold の区間が見つかった → その開始点を探す
        ph12_start = search_from  # デフォルト: 最大遡り端
        for i in range(brake_zone_end - 1, search_from - 1, -1):
            if i < n_brake and brake_lap[i] <= PH12_BRAKE_THRESHOLD:
                ph12_start = i + 1  # i+1 がブレーキ踏み始め (going forward)
                break

    ph12_samples = max(0, ph3_start - ph12_start)
    ph12_duration_ms = round(ph12_samples * dt_brake * 1000, 1)

    # PH1-2 brake peak
    ph12_brake_seg = brake_lap[ph12_start:ph3_start] if ph3_start > ph12_start else np.array([])
    ph12_brake_peak = _safe_max(ph12_brake_seg)

    # PH1-2 SusF avg (brake_lap → sus_f_lap インデックス変換)
    sus_i0 = ph12_start * sus_ratio
    sus_i1 = ph3_start  * sus_ratio
    ph12_susf_avg = _safe_mean(sus_f_lap[sus_i0:min(sus_i1, n_sus_f)]) if sus_i1 > sus_i0 else None

    # ── PH4-5 (apex.end の先: APEX end → アクセルON) ────────────────
    max_fwd_gas = max(1, int(PH45_MAX_LOOKAHEAD_S * sr * gas_ratio))
    g_apex_end  = ph3_end * gas_ratio          # gas_lap ローカルインデックス
    g_search_end = min(g_apex_end + max_fwd_gas, n_gas)

    ph45_end_brake = min(n_brake - 1, ph3_end + int(PH45_MAX_LOOKAHEAD_S * sr * brake_scale))
    found_gas_on = False
    consec = 0
    for g_i in range(g_apex_end, g_search_end):
        if gas_lap[g_i] > PH45_GAS_THRESHOLD:
            consec += 1
            if consec >= PH45_CONSEC_SAMPLES:
                # GAS ON した最初のサンプル: g_i - PH45_CONSEC_SAMPLES + 1
                g_on_start = g_i - PH45_CONSEC_SAMPLES + 1
                ph45_end_brake = min(n_brake - 1, g_on_start // gas_ratio)
                found_gas_on = True
                break
        else:
            consec = 0

    ph45_samples = max(0, ph45_end_brake - ph3_end)
    ph45_duration_ms = round(ph45_samples * dt_brake * 1000, 1)

    # PH4-5 gas avg
    g_i0 = ph3_end * gas_ratio
    g_i1 = ph45_end_brake * gas_ratio
    ph45_gas_avg = _safe_mean(gas_lap[g_i0:min(g_i1, n_gas)]) if g_i1 > g_i0 else None

    # PH4-5 SusF avg
    sus_j0 = ph3_end * sus_ratio
    sus_j1 = ph45_end_brake * sus_ratio
    ph45_susf_avg = _safe_mean(sus_f_lap[sus_j0:min(sus_j1, n_sus_f)]) if sus_j1 > sus_j0 else None

    total_corner_ms = round(ph12_duration_ms + ph3_duration_ms + ph45_duration_ms, 1)

    return {
        "ph12_duration_ms":    ph12_duration_ms,
        "ph12_brake_peak_bar": ph12_brake_peak,
        "ph12_susf_avg":       ph12_susf_avg,
        "ph3_duration_ms":     ph3_duration_ms,
        "ph3_speed_min":       ph3_speed_min,
        "ph3_susf_avg":        ph3_susf_avg,
        "ph3_susr_avg":        ph3_susr_avg,
        "ph45_duration_ms":    ph45_duration_ms,
        "ph45_gas_avg":        ph45_gas_avg,
        "ph45_susf_avg":       ph45_susf_avg,
        "total_corner_ms":     total_corner_ms,
    }


# ── 1 MES ファイル処理 ────────────────────────────────────────────────
def analyze_mes_corner_phases(
    mes_path: Path,
    event_meta: dict,
    rider_filter: str | None = None,
) -> list[dict]:
    """
    1 MES フォルダから全ラップ × 全コーナーのフェーズデータを返す。
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

    # ラウンド正規化
    _raw_ekey = _event_key_from_path(mes_path)
    event = _ROUND_NORM.get(_raw_ekey or "", "") if _raw_ekey else ""
    if not event:
        hed_event = hed.get("Event", "").strip()
        _m = re.match(r"^(R\d+|T\d+)(?:[^0-9]|$)", hed_event.upper())
        if _m:
            event = _ROUND_NORM.get(_m.group(1), hed_event)
        else:
            event = _ROUND_NORM.get(hed_event.upper(), hed_event)

    fn_prefix_m = re.match(r"^([A-Za-z0-9]+)", base)
    fn_prefix   = fn_prefix_m.group(1).upper() if fn_prefix_m else ""
    raw_sess    = hed.get("Session", "")
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
                date_s   = nd
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

    # 必須チャンネル: SPEED_FRONT, SUSP_FRONT, SUSP_REAR, BRAKE_FRONT, GAS (or similar)
    required = ["SPEED_FRONT", "SUSP_FRONT", "SUSP_REAR"]
    for ch in required:
        if ch not in chs or not chs[ch].get("ext"):
            return []

    brake_ch = next((k for k in chs if k.upper() == "BRAKE_FRONT" and chs[k].get("ext")), None)
    if not brake_ch:
        return []   # BRAKE_FRONT 必須

    gas_ch = next(
        (k for k in ("GAS_SMOOTH", "GAS", "TPS", "TPS_A", "SEN_TPSA1") if k in chs and chs[k].get("ext")),
        None,
    )
    if not gas_ch:
        return []   # GAS 必須

    dtps_ch = next(
        (k for k in chs if k.upper() in ("DTPS_A", "DTPS", "TPS_DELTA", "DELTA_TPS") and chs[k].get("ext")),
        None,
    )
    if not dtps_ch:
        return []   # dTPS_A 必須 (5条件APEX)

    sf_raw    = read_channel(mes_path, base, chs["SPEED_FRONT"])
    sus_f_raw = read_channel(mes_path, base, chs["SUSP_FRONT"])
    sus_r_raw = read_channel(mes_path, base, chs["SUSP_REAR"])
    brake_raw = read_channel(mes_path, base, chs[brake_ch])
    gas_raw   = read_channel(mes_path, base, chs[gas_ch])
    dtps_raw  = read_channel(mes_path, base, chs[dtps_ch])

    if len(sf_raw) < 10:
        return []

    susp_ratio  = max(1, round(len(sus_f_raw) / len(sf_raw))) if len(sus_f_raw) > 0 else 4
    brake_scale = len(brake_raw) / len(sf_raw) if len(brake_raw) > 0 else 1.0
    gas_ratio   = max(1, round(len(gas_raw)   / len(sf_raw))) if len(gas_raw)   > 0 else 1

    # ── ラップ境界 ────────────────────────────────────────────────────
    n_laps, lap_times_ms = parse_lap(mes_path, base)

    if n_laps > 0 and lap_times_ms:
        total_ms = lap_times_ms[-1]
        sr = len(sf_raw) / (total_ms / 1000.0) if total_ms > 0 else 100.0
    else:
        sr = 100.0
    sr  = max(10.0, min(sr, 500.0))

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

    # ── ラップ別 × コーナー別 解析 ─────────────────────────────────
    results = []

    for lap_idx, (lap_start, lap_end, lap_t_s) in enumerate(boundaries):
        lap_no = lap_idx + 1

        if lap_t_s < MIN_LAP_DURATION_S:
            continue
        if lap_end - lap_start < 20:
            continue

        time_per_sample = 1.0 / sr   # sec per speed sample

        # brake_f ラップスライス
        b_start = int(lap_start * brake_scale)
        b_end   = int(min(lap_end * brake_scale, len(brake_raw)))
        if b_end <= b_start:
            continue

        # gas ラップスライス
        g_start = lap_start * gas_ratio
        g_end   = min(lap_end * gas_ratio, len(gas_raw))

        # dtps ラップスライス
        d_start = lap_start * gas_ratio
        d_end   = min(lap_end * gas_ratio, len(dtps_raw))

        # susp ラップスライス
        s_start = lap_start * susp_ratio
        s_end   = min(lap_end * susp_ratio, len(sus_f_raw))

        brake_lap = brake_raw[b_start:b_end]
        gas_lap   = gas_raw[g_start:g_end]
        dtps_lap  = dtps_raw[d_start:d_end]
        sus_f_lap = sus_f_raw[s_start:s_end]
        sus_r_lap = sus_r_raw[s_start:s_end] if len(sus_r_raw) > 0 else np.array([], dtype=np.float32)

        # ── APEX area 検出 (5条件同時成立) ─────────────────────────────
        apex_areas_5cond = detect_apex_area(
            brake_lap, gas_lap, dtps_lap, sus_f_lap, sus_r_lap,
            gas_ratio=gas_ratio, sus_ratio=susp_ratio,
        )

        # ── フォールバック: ブレーキベースコーナー検出 ──────────────────
        sf_lap_local = sf_raw[lap_start:lap_end]
        apex_areas_fb = detect_corners_brake_based(
            brake_lap, sf_lap_local, sus_f_lap, sus_r_lap,
            sr, brake_scale, susp_ratio,
        )

        # 5条件APEXが少なすぎる場合はフォールバックを使用
        n_5cond = len(apex_areas_5cond)
        n_fb    = len(apex_areas_fb)
        use_fallback = (
            n_fb > 0 and (
                n_5cond == 0 or
                (lap_t_s > 80.0 and n_5cond < FB_FALLBACK_MIN) or
                n_5cond < n_fb * FB_FALLBACK_RATIO
            )
        )
        apex_areas = apex_areas_fb if use_fallback else apex_areas_5cond

        if not apex_areas:
            continue

        for c_idx, apex in enumerate(apex_areas):
            phase = analyze_corner_phases(
                apex=apex,
                brake_lap=brake_lap,
                gas_lap=gas_lap,
                sus_f_lap=sus_f_lap,
                sus_r_lap=sus_r_lap,
                sf_raw=sf_raw,
                lap_start=lap_start,
                lap_end=lap_end,
                sr=sr,
                brake_scale=brake_scale,
                gas_ratio=gas_ratio,
                sus_ratio=susp_ratio,
                time_per_sample=time_per_sample,
            )

            row = {
                "round":          event,
                "circuit":        circuit,
                "date":           date_fmt,
                "session_type":   session_type,
                "rider":          rider_tag,
                "run_no":         run_no,
                "lap_no":         lap_no,
                "lap_time_s":     round(lap_t_s, 3),
                "corner_no":      c_idx + 1,
            }
            row.update(phase)
            results.append(row)

    return results


# ── Main ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Corner Phase Analysis")
    parser.add_argument("--rider",   choices=["DA77", "JA52"], help="ライダーフィルター")
    parser.add_argument("--dry-run", action="store_true", help="JSON 書き込みなし")
    args = parser.parse_args()

    print("=" * 60)
    print("  TS24 Puccetti — Corner Phase Analysis (PH1-2/PH3/PH4-5)")
    print("=" * 60)

    if not DATA_2D_ROOT.exists():
        print(f"\n❌ DATA 2D フォルダが見つかりません: {DATA_2D_ROOT}")
        sys.exit(1)

    mes_list = find_all_mes(DATA_2D_ROOT)
    print(f"\n📂 Found {len(mes_list)} MES folders")

    print("🔍 Building event metadata...")
    event_meta = _build_event_meta(DATA_2D_ROOT)
    print(f"   → {len(event_meta)} events: {sorted(event_meta.keys())}")

    all_rows  = []
    n_laps    = 0
    n_corners = 0
    errors    = []

    for i, mes in enumerate(mes_list, 1):
        label = f"{mes.parent.name}/{mes.name}"
        print(f"  [{i:3d}/{len(mes_list)}] {label} ... ", end="", flush=True)
        try:
            rows = analyze_mes_corner_phases(mes, event_meta, rider_filter=args.rider)
            if rows:
                laps_this = len(set((r["lap_no"], r["run_no"]) for r in rows))
                n_laps    += laps_this
                n_corners += len(rows)
                all_rows.extend(rows)
                print(f"✅ laps={laps_this} corners={len(rows)}")
            else:
                print("⏭ skipped")
        except Exception as e:
            errors.append((label, str(e)))
            print(f"⚠️  {e}")

    print(f"\n✅ Total: {len(all_rows)} corner entries  ({n_laps} laps, n_corners={n_corners})")

    if not all_rows:
        print("\n⚠️  データなし。チャンネル構成を確認してください。")
        return

    if args.dry_run:
        print("\n[dry-run] JSON 書き込みをスキップ")
        # サマリーを表示
        for row in all_rows[:5]:
            print(f"  sample: {row['rider']} {row['circuit']} lap{row['lap_no']} c{row['corner_no']}"
                  f" PH12={row['ph12_duration_ms']}ms PH3={row['ph3_duration_ms']}ms"
                  f" PH45={row['ph45_duration_ms']}ms")
    else:
        JSON_OUT.write_text(
            json.dumps(all_rows, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )
        print(f"\n📄 Written: {JSON_OUT}  ({len(all_rows)} rows)")

    if errors:
        print(f"\n⚠️  {len(errors)} errors:")
        for path, msg in errors[:10]:
            print(f"   {path}: {msg}")


if __name__ == "__main__":
    main()
