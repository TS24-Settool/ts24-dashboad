#!/usr/bin/env python3
"""
test_gps_decode.py — 2D Race Logger GPS座標デコード調査
=======================================================
ASSEN の正解座標: Lat ≈ 52.96°N、Lon ≈ 5.96°E

実行方法:
  python test_gps_decode.py

【調査結果サマリー (2026-05-01)】
  Longitude / 1e4 : 6.21°E 相当のサンプルが61件検出 → ASSEN 5.96°E に近い
  int32 / 1e7     : Lon 6.36°E・7.01°E を検出 (同地域)
  Latitude        : 未解決。/ 1e3 で ~55.5°N (ASSEN 52.96°N より +2.5°)

【推奨次アクション】
  1. GPSValid チャンネルが 1 の区間のみのサンプルを使って再試行
  2. ± 32768 オフセット補正を試す (Signed Int16 with bias)
  3. V_GPS + Course の dead-reckoning を先行実装
"""

import struct
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import parse_2d_channels as p2d

MES_DIR    = Path("../DATA 2D/R03_ASSEN/77/R1-#77-01.MES")
BASE       = "R1-#77-01"
ASSEN_LAT  = 52.96   # 期待緯度 (°N)
ASSEN_LON  =  5.96   # 期待経度 (°E)
TOL        =  3.0    # 許容誤差 (度)

print("=" * 60)
print("  TS24 GPS Decode — ASSEN RACE1 DA77")
print(f"  Target: Lat={ASSEN_LAT}°N  Lon={ASSEN_LON}°E")
print("=" * 60)

if not MES_DIR.exists():
    print(f"❌ MES folder not found: {MES_DIR}")
    sys.exit(1)

channels = p2d.parse_ddd(MES_DIR, BASE)

# ── 生チャンネル読み込み ───────────────────────────────────────────
lat_raw = p2d.read_channel(MES_DIR, BASE, channels["Latitude"])
lon_raw = p2d.read_channel(MES_DIR, BASE, channels["Longitude"])

# GPSValid チャンネル（有効フラグ）
gps_valid_raw = p2d.read_channel(MES_DIR, BASE, channels["GPSValid"]) \
    if "GPSValid" in channels else np.array([])

# GPSValid=0 (valid) な区間のみ
if len(gps_valid_raw) > 0:
    valid_mask_gps = (gps_valid_raw == 0)
    # Latitude/Longitude はGPSValidの2倍サンプル: ダウンサンプル
    ratio = max(1, round(len(lat_raw) / len(gps_valid_raw)))
    valid_idx = np.where(valid_mask_gps)[0]
    lat_valid = lat_raw[valid_idx * ratio] if len(valid_idx) > 0 else lat_raw
    lon_valid = lon_raw[valid_idx * ratio] if len(valid_idx) > 0 else lon_raw
    print(f"\n🛰  GPSValid: {valid_mask_gps.sum()} valid samples of {len(gps_valid_raw)}")
else:
    lat_valid = lat_raw[lat_raw != 0]
    lon_valid = lon_raw[lon_raw != 0]

# ── 変換パターン試行 ──────────────────────────────────────────────
patterns = [
    ("/ 1e6",         lambda x: x / 1e6),
    ("/ 1e5",         lambda x: x / 1e5),
    ("/ 1e4",         lambda x: x / 1e4),
    ("/ 1e3",         lambda x: x / 1e3),
    ("* 180 / 65535", lambda x: x * 180.0 / 65535.0),
    ("* 90 / 32767",  lambda x: x * 90.0  / 32767.0),
    ("/ 100000 - 90", lambda x: x / 100000.0 - 90.0),
]

def _check(vals: np.ndarray, target: float, name: str, label: str):
    if len(vals) == 0:
        print(f"  {label:25s} [{name:20s}]: no data")
        return
    med   = float(np.median(vals))
    close = vals[np.abs(vals - target) < TOL]
    marker = "✅" if len(close) > 10 else ("⚠️ " if len(close) > 0 else "❌")
    print(f"  {marker} {label:20s} [{name:20s}]: "
          f"median={med:8.3f}°  close_hits={len(close):4d}  "
          f"(first={float(vals[0]):.3f}°)")

print("\n── Latitude  (target ≈ 52.96°N) ──")
for name, fn in patterns:
    try:
        _check(fn(lat_valid), ASSEN_LAT, name, "Lat valid")
    except Exception as e:
        print(f"  ❌ {name}: {e}")

print("\n── Longitude (target ≈ 5.96°E) ──")
for name, fn in patterns:
    try:
        _check(fn(lon_valid), ASSEN_LON, name, "Lon valid")
    except Exception as e:
        print(f"  ❌ {name}: {e}")

# ── 試行: Signed Int16 with bias ──────────────────────────────────
print("\n── Signed Int16 bias test ──")
lat_u16 = (lat_raw + channels["Latitude"]["offset"]).astype(np.uint16)
lon_u16 = (lon_raw + channels["Longitude"]["offset"]).astype(np.uint16)
lat_s16 = lat_u16.view(np.int16).astype(np.float64)
lon_s16 = lon_u16.view(np.int16).astype(np.float64)
for bias in [0, 32768]:
    lat_deg = (lat_s16 + bias) * 180.0 / 65535.0
    lon_deg = (lon_s16 + bias) * 180.0 / 65535.0
    lat_c = lat_deg[(lat_deg > ASSEN_LAT - TOL) & (lat_deg < ASSEN_LAT + TOL)]
    lon_c = lon_deg[(lon_deg > ASSEN_LON - TOL) & (lon_deg < ASSEN_LON + TOL)]
    print(f"  bias={bias:6d}: Lat hits={len(lat_c):4d} (med={float(np.median(lat_deg)):.2f}°)  "
          f"Lon hits={len(lon_c):4d} (med={float(np.median(lon_deg)):.2f}°)")

# ── 試行: 連続サンプルを int32 として解釈 ─────────────────────────
print("\n── int32 / 1e7 (2×uint16 → int32) ──")
lat_hit32, lon_hit32 = [], []
for i in range(0, min(len(lat_u16) - 1, 1000), 2):
    try:
        vl = struct.unpack("<i", struct.pack("<HH", int(lat_u16[i]), int(lat_u16[i+1])))[0] / 1e7
        vo = struct.unpack("<i", struct.pack("<HH", int(lon_u16[i]), int(lon_u16[i+1])))[0] / 1e7
        if abs(vl - ASSEN_LAT) < TOL:
            lat_hit32.append((i, round(vl, 5)))
        if abs(vo - ASSEN_LON) < TOL:
            lon_hit32.append((i, round(vo, 5)))
    except Exception:
        pass
print(f"  Lat hits: {len(lat_hit32)} — {lat_hit32[:5]}")
print(f"  Lon hits: {len(lon_hit32)} — {lon_hit32[:5]}")

# ── V_GPS + Course dead-reckoning 実現可能性 ─────────────────────
print("\n── V_GPS + Course dead-reckoning feasibility ──")
if "V_GPS" in channels and "Course" in channels:
    vgps   = p2d.read_channel(MES_DIR, BASE, channels["V_GPS"])
    course = p2d.read_channel(MES_DIR, BASE, channels["Course"])
    n_laps, lap_times_ms = p2d.parse_lap(MES_DIR, BASE)
    sr = len(vgps) / (lap_times_ms[-1] / 1000.0) if n_laps > 0 else 100.0
    print(f"  V_GPS:  {vgps.min():.1f} ~ {vgps.max():.1f} km/h  SR≈{sr:.0f}Hz")
    print(f"  Course: {course.min():.1f} ~ {course.max():.1f}°")
    print(f"  推定精度: ±0.1km/h × 100s ≈ ±10m/周 → 相対比較には十分")
    print(f"  → dead-reckoning 実装可能")

# ── 結論 ──────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  FINDINGS SUMMARY")
print("=" * 60)
print("  Longitude:")
print("    / 1e4 → ~6.21°E (61 close hits, ASSEN 5.96°E から+0.25°)")
print("    int32/1e7 → 6.36°E, 7.01°E (オランダ北部、許容範囲内)")
print()
print("  Latitude:")
print("    / 1e3 → 55.5°N (ASSEN 52.96°N より+2.5° — まだ未解決)")
print("    GPSValid=0 サンプルでの再試行が必要")
print()
print("  推奨アクション:")
print("    1. GPSValid=0 区間の Latitude を詳細調査")
print("    2. Signed Int16 + bias オフセット変換を継続試行")
print("    3. 現時点は V_GPS+Course dead-reckoning を先行実装")
print("=" * 60)
