#!/usr/bin/env python3
"""
parse_2d_channels.py — 2D Logger Channel Dynamics Analysis
===========================================================
2D Analyser (.MES) フォルダからチャンネルデータを読み込み、
以下の指標を計算して PUCCETTI_DB_MASTER.xlsx の新シート
「DYNAMICS_ANALYSIS」に保存する。

計算項目:
  1. APEX時のF/Rサスペンションストローク量 (mm)
  2. APEX時のホイールフォース (N) — 車体動力学方程式から算出
  3. ピットレーンリミッター発動区間 (Speed F 56〜64 km/h が3秒以上) のF/Rサスストローク平均 (mm)
  4. ブレーキ直前のF/Rサスストローク (mm)

使用チャンネル:
  SPEED_FRONT (km/h)  → APEX検出・低速ゾーン判定・加減速度計算
  SUSP_FRONT  (mm)    → フロントサスストローク
  SUSP_REAR   (mm)    → リアサスストローク
  BRAKE_FRONT (Bar)   → ブレーキ検出補助
  BRAKE_REAR  (Bar)   → ブレーキ検出補助

TS24 パラメータ (Knowledge Base 11.8):
  JA52: WB=1399mm, h=644.9mm, Fw_rate=30.1N/mm, Rw_rate=58.4N/mm
        F-weight=48.92%, R-weight=51.08%
  DA77: WB=1411.5mm, h=651.1mm, Fw_rate=26.1N/mm, Rw_rate=57.8N/mm
        F-weight=48.71%, R-weight=51.29%

実行方法:
  python3 parse_2d_channels.py
"""

import os
import re
import struct
import math
import json
from pathlib import Path
from datetime import datetime
import numpy as np

# ── 定数 ─────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).resolve().parent
DATA_2D_ROOT  = SCRIPT_DIR.parent / "DATA 2D"
EXCEL_PATH    = SCRIPT_DIR.parent / "02_DATABASE" / "TS24 DB Master.xlsx"
OUTPUT_SHEET  = "DYNAMICS_ANALYSIS"

G             = 9.81        # m/s²
KMH_TO_MS     = 1.0 / 3.6  # km/h → m/s

# TS24 バイオメカニクスパラメータ
RIDER_PARAMS = {
    "JA52": {
        "wheelbase_m":    1.399,
        "cog_h_m":        0.6449,
        "f_weight_ratio": 0.4892,
        "fw_rate_Nmm":    30.1,
        "rw_rate_Nmm":    58.4,
    },
    "DA77": {
        "wheelbase_m":    1.4115,
        "cog_h_m":        0.6511,
        "f_weight_ratio": 0.4871,
        "fw_rate_Nmm":    26.1,
        "rw_rate_Nmm":    57.8,
    },
}

# APEX検出パラメータ (局所極小点 + プロミネンスフィルタ方式)
APEX_SPEED_THRESHOLD_RATIO = 0.92  # ラップ最高速の92%以下のみAPEX候補とする
APEX_MIN_GAP_S             = 0.25  # 隣接APEX間の最小間隔 [秒] (シケイン対応)
APEX_SMOOTH_WINDOW_S       = 0.3   # Speed Fスムージング [秒]
APEX_MIN_PROMINENCE_KMH    = 15.0  # APEX前後 ±4秒の最高速との最低落差 [km/h]
#   → 直線上の微細な速度変動(5〜10km/h)を除外し、真のコーナーのみ検出
APEX_PROMINENCE_WINDOW_S   = 4.0   # プロミネンス判定ウィンドウ [秒]
MIN_LAP_DURATION_S         = 60.0  # これ未満のラップはアウトラップ/フォーメーション等として除外

# ピットレーンリミッターパラメータ
PIT_LIMITER_SPEED_KMH  = 60.0  # ピットリミッター速度
PIT_LIMITER_MARGIN_KMH = 4.0   # ±マージン → 56〜64 km/h
PIT_LIMITER_MIN_S      = 3.0   # 最小持続時間 (秒)

# ブレーキ検出パラメータ
BRAKE_DECEL_THRESHOLD_MS2 = -8.0   # 減速度閾値 (m/s²) — 負 = 減速 (強めに設定)
BRAKE_CONFIRM_SAMPLES     = 15     # 連続N サンプル以上で確定 (~0.15s @100Hz)
BRAKE_MIN_GAP_SAMPLES     = 80     # 次ブレーキイベントまでの最小間隔 (~0.8s)
BRAKE_MIN_SPEED_KMH       = 80.0   # この速度以上でのみブレーキとみなす
BRAKE_LOOK_AHEAD_SAMPLES  = 8      # ブレーキ開始N サンプル前の値を「直前」とする
BRAKE_SMOOTH_WINDOW       = 7      # Speed F 微分前スムージングウィンドウ

# ── DDD パーサー ──────────────────────────────────────────────────────
def parse_ddd(mes_path: Path, base: str) -> dict:
    """DDD → {channel_name: {ext, offset, scale, signed}}"""
    ddd_path = mes_path / f"{base}.DDD"
    if not ddd_path.exists():
        return {}
    raw  = ddd_path.read_bytes()
    text = raw.decode("latin-1", errors="replace")

    sections, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^\[([0-9A-Fa-f]+)\]$", line)
        if m:
            current = m.group(1)
            sections[current] = {}
            continue
        if current and "=" in line:
            k, _, v = line.partition("=")
            sections[current][k.strip()] = v.strip()

    def hex_float(h):
        try:
            return struct.unpack(">f", bytes.fromhex(h.zfill(8)))[0]
        except Exception:
            return 1.0

    channels = {}
    for _, fields in sections.items():
        line4 = fields.get("4", "")
        line6 = fields.get("6", "")
        line3 = fields.get("3", "")
        name  = line4.split(",")[0].strip() if line4 else ""
        if not name:
            continue
        parts6 = line6.split(",")
        ext    = parts6[3] if len(parts6) > 3 else ""
        parts3 = line3.split(",")
        offset = int(parts3[0]) if parts3 and parts3[0].lstrip("-").isdigit() else 0
        scale  = hex_float(parts3[3]) if len(parts3) > 3 else 1.0
        mult   = hex_float(parts3[6]) if len(parts3) > 6 else 1.0
        signed = line6.startswith("FFFFFFFE") or (len(parts6) > 1 and parts6[1] == "I")
        channels[name] = {
            "ext": ext, "offset": offset,
            "scale": scale, "mult": mult or 1.0,
            "signed": signed,
        }
    return channels


def read_channel(mes_path: Path, base: str, ch: dict) -> np.ndarray:
    """チャンネルファイルを物理値 numpy 配列として読み込む"""
    path = mes_path / f"{base}.{ch['ext']}"
    if not path.exists():
        return np.array([], dtype=np.float32)
    data = path.read_bytes()
    n    = len(data) // 2
    dtype = np.int16 if ch["signed"] else np.uint16
    raw  = np.frombuffer(data[: n * 2], dtype=dtype).astype(np.float32)
    off, sc, mu = ch["offset"], ch["scale"], ch["mult"]
    return (raw - off) * sc * (mu or 1.0)


# ── HED パーサー ──────────────────────────────────────────────────────
def parse_hed(mes_path: Path, base: str) -> dict:
    """HED → セッションメタデータ dict
    セクション別に収集し、フラットキーは [GENERAL] を最優先とする。
    セクション固有キーは 'SECTION.Key' 形式でも保存。
    """
    path = mes_path / f"{base}.HED"
    if not path.exists():
        return {}
    text    = path.read_bytes().decode("latin-1", errors="replace")
    info    = {}
    section = "GENERAL"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            # セクション固有キー (例: MASS.Bike, GENERAL.Date)
            info[f"{section}.{k}"] = v
            # フラットキー: GENERAL 優先、なければ初回のみ
            if k not in info or section == "GENERAL":
                info[k] = v
    return info


# ── LAP パーサー ──────────────────────────────────────────────────────
def parse_lap(mes_path: Path, base: str):
    """LAP → (n_laps, [lap_end_ms, ...])"""
    path = mes_path / f"{base}.LAP"
    if not path.exists():
        return 0, []
    data   = path.read_bytes()
    n_int  = len(data) // 4
    if n_int < 3:
        return 0, []
    vals   = struct.unpack(f"<{n_int}I", data[: n_int * 4])
    n_laps = vals[0]
    times  = list(vals[3: 3 + n_laps])
    return n_laps, times


# ── ユーティリティ ────────────────────────────────────────────────────
def smooth(arr: np.ndarray, w: int = 5) -> np.ndarray:
    """numpy convolve による高速移動平均スムージング"""
    if w <= 1 or len(arr) < w:
        return arr
    kernel = np.ones(w, dtype=np.float32) / w
    return np.convolve(arr, kernel, mode="same")


def derivative(arr: np.ndarray, dt: float) -> np.ndarray:
    """numpy gradient による高速中央差分微分 (単位: /dt)"""
    if len(arr) < 2:
        return np.zeros_like(arr)
    return np.gradient(arr.astype(np.float64), dt).astype(np.float32)


def susp_at_speed_index(susp: np.ndarray, speed_idx: int, ratio: int = 4) -> float:
    """Speed sample index → 対応する SUSP 値 (SUSP は Speed の ratio 倍サンプル)"""
    si = speed_idx * ratio
    if 0 <= si < len(susp):
        return float(susp[si])
    return float("nan")


def susp_mean_in_range(susp: np.ndarray, s_start: int, s_end: int, ratio: int = 4) -> float:
    """Speed sample 範囲 [s_start, s_end] に対応する SUSP の平均"""
    i0  = max(0, s_start * ratio)
    i1  = min(len(susp), s_end * ratio)
    if i0 >= i1:
        return float("nan")
    return float(np.mean(susp[i0:i1]))


def safe_mean(lst):
    lst = [float(v) for v in lst if v is not None and not math.isnan(float(v) if hasattr(v, '__float__') else v)]
    return round(sum(lst) / len(lst), 2) if lst else None


# ── 動力学計算 ────────────────────────────────────────────────────────
def wheel_forces(rider_tag: str, mass_kg: float, ax_ms2: float):
    """
    ホイール荷重計算 (m/s² ← 正=加速, 負=制動)
    Returns (Nf_N, Nr_N)
    """
    p    = RIDER_PARAMS.get(rider_tag, RIDER_PARAMS["DA77"])
    L    = p["wheelbase_m"]
    h    = p["cog_h_m"]
    fw   = p["f_weight_ratio"]
    rw   = 1.0 - fw
    # 静的荷重
    Nf0  = mass_kg * G * fw
    Nr0  = mass_kg * G * rw
    # 動的荷重移動 (制動時はフロントへ移動, ax<0 → -ax>0)
    dN   = mass_kg * (-ax_ms2) * h / L   # 正値=フロントへ移動
    Nf   = Nf0 + dN
    Nr   = Nr0 - dN
    return max(0.0, Nf), max(0.0, Nr)


# ── APEX 検出 ────────────────────────────────────────────────────────
def detect_apexes(speed_kmh: np.ndarray, lap_start: int, lap_end: int,
                  sr: float) -> list:
    """
    ラップ内の全コーナーAPEX を局所極小点(Local Minima)方式で検出。

    【旧方式の問題】
      「速度が閾値以下の連続区間の最小1点」 → 連続コーナー・シケインが
      1点に折りたたまれ、1ラップあたり3〜8コーナーしか検出できなかった。

    【新方式】
      速度トレースの勾配符号が (負 → 正) に変化する点 = 局所極小 を全て検出。
      ラップ最高速の 92% 以下 かつ 隣接APEXと 0.25秒以上 離れているものを採用。
      → 全コーナーの APEX を個別に検出可能 (フィリップアイランド13、アッセン18 等)

    Returns: list of sample indices (global index)
    """
    seg = speed_kmh[lap_start:lap_end]
    if len(seg) < 10:
        return []

    # 0.4 秒ウィンドウでスムージング (ノイズによる偽極小除去)
    smooth_w  = max(3, int(APEX_SMOOTH_WINDOW_S * sr))
    seg_s     = smooth(seg, smooth_w)

    max_speed = float(np.max(seg_s))
    if max_speed < 10:
        return []
    threshold = max_speed * APEX_SPEED_THRESHOLD_RATIO

    # 勾配を計算し、(負 → 正) の符号変化 = 局所極小 を抽出
    grad      = np.gradient(seg_s.astype(np.float64))
    neg_to_pos = (grad[:-1] < 0) & (grad[1:] >= 0)
    local_min  = np.where(neg_to_pos)[0]

    # 速度閾値フィルタ: 最高速の 92% 以下のみ
    valid = local_min[seg_s[local_min] < threshold]

    # プロミネンスウィンドウ (直線速度との落差チェック)
    pw = int(APEX_PROMINENCE_WINDOW_S * sr)

    # 最小間隔フィルタ + プロミネンスフィルタ
    min_gap    = max(5, int(APEX_MIN_GAP_S * sr))
    apexes     = []
    last_local = -min_gap

    for idx in valid:
        idx = int(idx)
        # ±APEX_PROMINENCE_WINDOW_S 秒の最高速との落差を確認
        w0    = max(0, idx - pw)
        w1    = min(len(seg_s), idx + pw)
        depth = float(np.max(seg_s[w0:w1])) - float(seg_s[idx])
        if depth < APEX_MIN_PROMINENCE_KMH:
            continue   # 直線上の微細な速度変動 → 無視
        if idx - last_local >= min_gap:
            apexes.append(lap_start + idx)
            last_local = idx

    return apexes


# ── ピットレーンリミッター区間検出 ───────────────────────────────────
def detect_pit_limiter_zones(speed_kmh: np.ndarray, lap_start: int, lap_end: int,
                              sr: float) -> list:
    """
    ピットレーンリミッター発動区間の検出。
    Speed F が [56, 64] km/h の範囲に 3秒以上連続して収まっている区間を返す。
    ローリング平均ではなく瞬時速度の帯域チェックを使用
    (リミッターは電子的速度クランプで瞬時に安定するため)。

    Returns: list of (start_idx, end_idx) tuples (global indices)
    """
    seg = speed_kmh[lap_start:lap_end]
    if len(seg) < 10:
        return []
    lo          = PIT_LIMITER_SPEED_KMH - PIT_LIMITER_MARGIN_KMH   # 56 km/h
    hi          = PIT_LIMITER_SPEED_KMH + PIT_LIMITER_MARGIN_KMH   # 64 km/h
    min_samples = max(1, int(PIT_LIMITER_MIN_S * sr))

    # 軽いスムージング (0.2 s) でノイズ除去してから帯域チェック
    smooth_w = max(1, int(0.2 * sr))
    seg_s    = smooth(seg, smooth_w)

    # 帯域内 mask & ランレングス
    mask    = (seg_s >= lo) & (seg_s <= hi)
    changes = np.diff(mask.astype(np.int8), prepend=0, append=0)
    starts  = np.where(changes == 1)[0]
    ends    = np.where(changes == -1)[0]

    zones = []
    for s, e in zip(starts, ends):
        if (e - s) >= min_samples:
            zones.append((lap_start + int(s), lap_start + int(e)))
    return zones


# ── ブレーキング直前検出 ──────────────────────────────────────────────
def detect_brake_entries(speed_kmh: np.ndarray, speed_ms: np.ndarray,
                         lap_start: int, lap_end: int, dt: float) -> list:
    """
    Speed F の急激な減速開始点を検出し、
    その BRAKE_LOOK_AHEAD_SAMPLES 前の index を返す。
    条件: 速度が BRAKE_MIN_SPEED_KMH 以上の状態で急減速が BRAKE_CONFIRM_SAMPLES 以上継続
    Returns: list of sample indices (global) — ブレーキ直前
    """
    seg_kmh = speed_kmh[lap_start:lap_end]
    seg_ms  = speed_ms[lap_start:lap_end]
    if len(seg_ms) < 10:
        return []

    # numpy による高速スムージング + 微分
    seg_s = smooth(seg_ms.astype(np.float64), BRAKE_SMOOTH_WINDOW)
    dv    = derivative(seg_s, dt)   # m/s²

    # マスク: 高速かつ強い減速
    mask_brake = (dv < BRAKE_DECEL_THRESHOLD_MS2) & (seg_kmh >= BRAKE_MIN_SPEED_KMH)

    # ランレングスで連続ブレーキ区間を検出
    changes = np.diff(mask_brake.astype(np.int8), prepend=0, append=0)
    starts  = np.where(changes == 1)[0]
    ends    = np.where(changes == -1)[0]

    entries    = []
    last_entry = -BRAKE_MIN_GAP_SAMPLES

    for s, e in zip(starts, ends):
        duration = int(e) - int(s)
        if duration < BRAKE_CONFIRM_SAMPLES:
            continue
        brake_start = int(s)
        if brake_start - last_entry < BRAKE_MIN_GAP_SAMPLES:
            continue
        look_back = max(0, brake_start - BRAKE_LOOK_AHEAD_SAMPLES)
        entries.append(lap_start + look_back)
        last_entry = brake_start

    return entries


# ── セッション解析メイン ──────────────────────────────────────────────
def analyze_mes(mes_path: Path) -> dict | None:
    """1 MES フォルダを解析して結果 dict を返す。失敗時は None。"""
    base = mes_path.name.replace(".MES", "")

    # ── メタデータ
    hed = parse_hed(mes_path, base)
    if not hed:
        return None

    # ライダー識別 (HED: Rider Number 例 #77 or #52)
    rider_num = hed.get("Rider Number", "")
    if "77" in rider_num:
        rider_tag = "DA77"
    elif "52" in rider_num or "JA" in rider_num.upper():
        rider_tag = "JA52"
    else:
        return None   # ライダー不明はスキップ

    # 質量 ([MASS] セクションから優先取得)
    def _to_float(s, default):
        try:
            return float(str(s).split("(")[0].strip() or default)
        except Exception:
            return float(default)
    bike_kg  = _to_float(hed.get("MASS.Bike",  hed.get("MASS.bike",  163)), 163)
    rider_kg = _to_float(hed.get("MASS.Rider", hed.get("MASS.rider", 75)),  75)
    if bike_kg < 50 or bike_kg > 300:   # 数値異常ならデフォルト
        bike_kg = 163
    if rider_kg < 40 or rider_kg > 150:
        rider_kg = 75
    mass_kg  = bike_kg + rider_kg

    # セッション情報
    event   = hed.get("Event", "")
    session = hed.get("Session", "")
    # ランナンバーはHEDが常に"01"を返すためファイル名末尾の数字を使用
    # 例: D1-#77-03.MES → 3, D2-JA52-09.MES → 9
    run_match = re.search(r"-(\d+)$", base)
    run_no    = int(run_match.group(1)) if run_match else int(hed.get("Run", "1") or 1)
    circuit = hed.get("Circuit", "").upper()
    date_s  = hed.get("Date", "")
    date_fmt = date_s
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            date_fmt = datetime.strptime(date_s, fmt).strftime("%Y-%m-%d")
            break
        except Exception:
            continue

    # セッション種別マッピング
    sess_map = {
        "FP": "FP", "F1": "FP", "F2": "FP",
        "QP": "QP", "Q1": "QP", "Q2": "QP",
        "WU": "WUP", "WU1": "WUP", "WU2": "WUP",
        "WUP1": "WUP", "WUP2": "WUP",
        "R1": "RACE1", "R2": "RACE2",
        "RACE1": "RACE1", "RACE2": "RACE2",
        "D1": "TEST_D1", "D2": "TEST_D2",
    }
    session_type = sess_map.get(session.upper(), session.upper())

    # ── チャンネル定義
    chs = parse_ddd(mes_path, base)
    needed = ["SPEED_FRONT", "SUSP_FRONT", "SUSP_REAR"]
    for ch in needed:
        if ch not in chs or not chs[ch]["ext"]:
            return None   # 必須チャンネルなし

    # ── データ読み込み
    sf_raw    = read_channel(mes_path, base, chs["SPEED_FRONT"])   # km/h
    sus_f_raw = read_channel(mes_path, base, chs["SUSP_FRONT"])    # mm
    sus_r_raw = read_channel(mes_path, base, chs.get("SUSP_REAR", {}))  # mm

    if len(sf_raw) < 10:
        return None

    # SUSP/SPEED サンプル比率
    susp_ratio = max(1, round(len(sus_f_raw) / len(sf_raw))) if len(sus_f_raw) > 0 else 4

    # ── ラップ情報
    n_laps, lap_times_ms = parse_lap(mes_path, base)

    # サンプルレート推定
    if n_laps > 0 and lap_times_ms:
        total_ms = lap_times_ms[-1]
        sr       = len(sf_raw) / (total_ms / 1000.0) if total_ms > 0 else 100.0
    else:
        sr       = 100.0   # デフォルト 100 Hz (LAP なし)

    sr  = max(10.0, min(sr, 500.0))   # 安全クランプ
    dt  = 1.0 / sr                    # 秒/サンプル

    # Speed を m/s に変換 (numpy)
    sf_ms = sf_raw * KMH_TO_MS

    # ── ラップ境界を sample index へ変換
    if n_laps > 0 and lap_times_ms:
        boundaries = []
        prev_ms    = 0
        for t_ms in lap_times_ms:
            s = int(prev_ms / 1000.0 * sr)
            e = int(t_ms   / 1000.0 * sr)
            boundaries.append((s, min(e, len(sf_raw) - 1)))
            prev_ms = t_ms
    else:
        # LAP なし → 全録音を 1 "ラップ" として扱う
        boundaries = [(0, len(sf_raw) - 1)]

    # ── 解析 -------------------------------------------
    apex_results  = []   # (speed_kmh, susF_mm, susR_mm, Nf_N, Nr_N)
    pit_results   = []   # ピットリミッター: (avg_speed, susF_mm, susR_mm)
    brake_results = []   # (speed_kmh, susF_mm, susR_mm)

    for (lap_start, lap_end) in boundaries:
        lap_duration_s = (lap_end - lap_start) / sr
        if lap_duration_s < MIN_LAP_DURATION_S:
            continue   # アウトラップ/フォーメーションラップ/ピット出入り等を除外
        if lap_end - lap_start < 20:
            continue

        # 1. APEX 検出 (全コーナー局所極小方式)
        apexes = detect_apexes(sf_raw, lap_start, lap_end, sr)
        for ai in apexes:
            v_kmh = sf_raw[ai]
            if v_kmh < 0:
                continue
            # 加減速度 (m/s²)
            if 0 < ai < len(sf_ms) - 1:
                ax = (sf_ms[ai + 1] - sf_ms[ai - 1]) / (2.0 * dt)
            else:
                ax = 0.0
            Nf, Nr = wheel_forces(rider_tag, mass_kg, ax)
            sF = susp_at_speed_index(sus_f_raw, ai, susp_ratio)
            sR = susp_at_speed_index(sus_r_raw, ai, susp_ratio) if len(sus_r_raw) > 0 else float("nan")
            apex_results.append({
                "speed_kmh": round(v_kmh, 1),
                "susF_mm":   round(sF, 1) if not math.isnan(sF) else None,
                "susR_mm":   round(sR, 1) if not math.isnan(sR) else None,
                "Nf_N":      round(Nf, 1),
                "Nr_N":      round(Nr, 1),
                "ax_ms2":    round(ax, 2),
            })

        # 2. ピットレーンリミッター区間検出
        pit_zones = detect_pit_limiter_zones(sf_raw, lap_start, lap_end, sr)
        for (z0, z1) in pit_zones:
            avg_v   = float(np.mean(sf_raw[z0:z1]))
            sF_mean = susp_mean_in_range(sus_f_raw, z0, z1, susp_ratio)
            sR_mean = susp_mean_in_range(sus_r_raw, z0, z1, susp_ratio) if len(sus_r_raw) > 0 else float("nan")
            pit_results.append({
                "speed_kmh": round(avg_v, 1),
                "susF_mm":   round(sF_mean, 1) if not math.isnan(sF_mean) else None,
                "susR_mm":   round(sR_mean, 1) if not math.isnan(sR_mean) else None,
            })

        # 3. ブレーキ直前検出
        entries = detect_brake_entries(sf_raw, sf_ms, lap_start, lap_end, dt)
        for bi in entries:
            v_kmh = sf_raw[bi] if bi < len(sf_raw) else 0
            sF    = susp_at_speed_index(sus_f_raw, bi, susp_ratio)
            sR    = susp_at_speed_index(sus_r_raw, bi, susp_ratio) if len(sus_r_raw) > 0 else float("nan")
            brake_results.append({
                "speed_kmh": round(v_kmh, 1),
                "susF_mm":   round(sF, 1) if not math.isnan(sF) else None,
                "susR_mm":   round(sR, 1) if not math.isnan(sR) else None,
            })

    # ── 集計
    def agg(lst, key):
        return safe_mean([r[key] for r in lst])

    return {
        "round":                event,
        "date":                 date_fmt,
        "circuit":              circuit,
        "session_type":         session_type,
        "rider":                rider_tag,
        "run_no":               run_no,
        "sample_rate_hz":       round(sr, 1),
        "n_laps_analyzed":      max(1, n_laps) if n_laps > 0 else 1,
        # APEX
        "apex_count":           len(apex_results),
        "apex_speed_avg_kmh":   agg(apex_results, "speed_kmh"),
        "apex_susF_avg_mm":     agg(apex_results, "susF_mm"),
        "apex_susR_avg_mm":     agg(apex_results, "susR_mm"),
        "apex_wheelF_avg_N":    agg(apex_results, "Nf_N"),
        "apex_wheelR_avg_N":    agg(apex_results, "Nr_N"),
        "apex_ax_avg_ms2":      agg(apex_results, "ax_ms2"),
        # ピットレーンリミッター
        "pit_count":            len(pit_results),
        "pit_speed_avg_kmh":    agg(pit_results, "speed_kmh"),
        "pit_susF_avg_mm":      agg(pit_results, "susF_mm"),
        "pit_susR_avg_mm":      agg(pit_results, "susR_mm"),
        # ブレーキ直前
        "brake_entry_count":    len(brake_results),
        "brake_speed_avg_kmh":  agg(brake_results, "speed_kmh"),
        "brake_susF_avg_mm":    agg(brake_results, "susF_mm"),
        "brake_susR_avg_mm":    agg(brake_results, "susR_mm"),
    }


# ── MES フォルダ収集 ─────────────────────────────────────────────────
def find_all_mes(root: Path) -> list:
    """DATA 2D 配下の全 .MES フォルダを再帰的に収集"""
    mes_list = []
    for entry in root.rglob("*.MES"):
        if entry.is_dir():
            mes_list.append(entry)
    # 直下 .MES も収集
    for entry in root.iterdir():
        if entry.is_dir() and entry.name.endswith(".MES"):
            if entry not in mes_list:
                mes_list.append(entry)
    return sorted(mes_list)


# ── Excel 書き込み ───────────────────────────────────────────────────
def write_to_excel(results: list, excel_path: Path, sheet_name: str):
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import (
            PatternFill, Font, Alignment, Border, Side
        )
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  ❌ openpyxl not found. pip install openpyxl --break-system-packages")
        return False

    wb = load_workbook(excel_path)

    # シートが既存ならクリア
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)

    # ── スタイル定義
    HDR_FILL  = PatternFill("solid", fgColor="1F4E79")  # 濃紺
    HDR_FONT  = Font(bold=True, color="FFFFFF", size=10)
    GRP_FILL  = {
        "info":  PatternFill("solid", fgColor="D6E4F0"),
        "apex":  PatternFill("solid", fgColor="E2EFDA"),
        "slow":  PatternFill("solid", fgColor="FFF2CC"),
        "brake": PatternFill("solid", fgColor="FCE4D6"),
    }
    GRP_FONT  = {k: Font(bold=True, size=9, color="000000") for k in GRP_FILL}
    CELL_FONT = Font(size=9)
    CENTER    = Alignment(horizontal="center", vertical="center")
    THIN      = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"),  bottom=Side(style="thin"),
    )

    # ── ヘッダー定義
    HEADERS = [
        # (label, key, group, width)
        ("Round",          "round",               "info",  12),
        ("Date",           "date",                "info",  12),
        ("Circuit",        "circuit",             "info",  18),
        ("Session",        "session_type",        "info",  10),
        ("Rider",          "rider",               "info",  8),
        ("Run",            "run_no",              "info",  6),
        ("SR (Hz)",        "sample_rate_hz",      "info",  8),
        ("Laps",           "n_laps_analyzed",     "info",  6),
        # APEX
        ("APEX Count",     "apex_count",          "apex",  10),
        ("APEX Spd (km/h)","apex_speed_avg_kmh",  "apex",  14),
        ("APEX SusF (mm)", "apex_susF_avg_mm",    "apex",  14),
        ("APEX SusR (mm)", "apex_susR_avg_mm",    "apex",  14),
        ("APEX WhlF (N)",  "apex_wheelF_avg_N",   "apex",  14),
        ("APEX WhlR (N)",  "apex_wheelR_avg_N",   "apex",  14),
        ("APEX ax (m/s²)", "apex_ax_avg_ms2",     "apex",  13),
        # ピットレーンリミッター
        ("Pit Count",      "pit_count",           "slow",  10),
        ("Pit Spd (km/h)", "pit_speed_avg_kmh",   "slow",  14),
        ("Pit SusF (mm)",  "pit_susF_avg_mm",      "slow",  14),
        ("Pit SusR (mm)",  "pit_susR_avg_mm",      "slow",  14),
        # ブレーキ直前
        ("Brk Count",      "brake_entry_count",   "brake", 10),
        ("Brk Spd (km/h)", "brake_speed_avg_kmh", "brake", 14),
        ("Brk SusF (mm)",  "brake_susF_avg_mm",   "brake", 14),
        ("Brk SusR (mm)",  "brake_susR_avg_mm",   "brake", 14),
    ]

    # ── Row 1: グループ行
    grp_labels = {
        "info":  ("Session Info",          1,  8),
        "apex":  ("APEX Analysis",         9,  15),
        "slow":  ("Pit Lane Limiter",       16, 19),
        "brake": ("Braking Entry",         20, 23),
    }
    ws.row_dimensions[1].height = 18
    for grp, (label, col_s, col_e) in grp_labels.items():
        cell = ws.cell(row=1, column=col_s, value=label)
        cell.fill      = GRP_FILL[grp]
        cell.font      = GRP_FONT[grp]
        cell.alignment = CENTER
        if col_s < col_e:
            ws.merge_cells(
                start_row=1, start_column=col_s,
                end_row=1,   end_column=col_e
            )

    # ── Row 2: 列ヘッダー
    ws.row_dimensions[2].height = 22
    for ci, (label, key, grp, width) in enumerate(HEADERS, start=1):
        cell = ws.cell(row=2, column=ci, value=label)
        cell.fill      = HDR_FILL
        cell.font      = HDR_FONT
        cell.alignment = CENTER
        cell.border    = THIN
        ws.column_dimensions[get_column_letter(ci)].width = width

    # ── データ行
    for ri, row in enumerate(results, start=3):
        ws.row_dimensions[ri].height = 16
        for ci, (label, key, grp, _) in enumerate(HEADERS, start=1):
            val  = row.get(key)
            cell = ws.cell(row=ri, column=ci, value=val)
            cell.font      = CELL_FONT
            cell.alignment = CENTER
            cell.border    = THIN
            # ゼブラ
            if ri % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F2F2F2")

    # ウィンドウ枠固定
    ws.freeze_panes = "A3"

    wb.save(excel_path)
    return True


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  TS24 Puccetti — 2D Channel Dynamics Analysis")
    print("=" * 60)

    if not DATA_2D_ROOT.exists():
        print(f"\n❌ DATA 2D フォルダが見つかりません: {DATA_2D_ROOT}")
        return

    if not EXCEL_PATH.exists():
        print(f"\n❌ Excel ファイルが見つかりません: {EXCEL_PATH}")
        return

    # MES 収集
    mes_list = find_all_mes(DATA_2D_ROOT)
    print(f"\n📂 Found {len(mes_list)} MES folders")

    # 解析
    results = []
    errors  = []
    for i, mes in enumerate(mes_list, 1):
        print(f"  [{i:3d}/{len(mes_list)}] {mes.parent.name}/{mes.name} ... ", end="", flush=True)
        try:
            r = analyze_mes(mes)
            if r:
                results.append(r)
                n_apex = r["apex_count"]
                n_pit  = r["pit_count"]
                n_brk  = r["brake_entry_count"]
                print(f"✅ APEX={n_apex} PitLim={n_pit} Brk={n_brk}")
            else:
                print("⏭ skipped (missing channels or metadata)")
        except Exception as e:
            errors.append((str(mes), str(e)))
            print(f"⚠️  {e}")

    print(f"\n✅ Analyzed: {len(results)} sessions  ❌ Errors: {len(errors)}")

    if not results:
        print("\n⚠️  解析結果なし。チャンネルデータを確認してください。")
        return

    # 重複排除 (round+date+circuit+session+rider+run が同一のもの → 後者を優先)
    seen, deduped = {}, []
    for r in results:
        k = (r["round"], r["date"], r["circuit"], r["session_type"], r["rider"], r["run_no"])
        seen[k] = r
    deduped = list(seen.values())
    deduped.sort(key=lambda r: (r["date"], r["rider"], r["run_no"]))

    print(f"\n📝 Writing {len(deduped)} rows → sheet '{OUTPUT_SHEET}' ...")
    ok = write_to_excel(deduped, EXCEL_PATH, OUTPUT_SHEET)

    if ok:
        print(f"\n✅ DYNAMICS_ANALYSIS sheet written to:")
        print(f"   {EXCEL_PATH}")
    else:
        print("\n❌ Excel 書き込み失敗")

    if errors:
        print("\n⚠️  Errors encountered:")
        for path, msg in errors[:10]:
            print(f"   {path}: {msg}")


if __name__ == "__main__":
    main()
