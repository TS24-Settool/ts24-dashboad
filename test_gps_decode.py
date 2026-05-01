#!/usr/bin/env python3
"""
test_gps_decode.py — 2D Race Logger GPS座標デコード調査
=======================================================
ASSEN の座標: 緯度 52.96°N、経度 5.96°E

実行方法:
  python test_gps_decode.py
"""

import struct
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import parse_2d_channels as p2d

MES_DIR = Path("../DATA 2D/R03_ASSEN/77/R1-#77-01.MES")
BASE    = "R1-#77-01"

ASSEN_LAT = 52.96   # 期待緯度
ASSEN_LON =  5.96   # 期待経度
LAT_TOL   =  3.0    # 許容誤差 (度)
LON_TOL   =  3.0

print("=" * 60)
print("  TS24 GPS Decode Investigation — ASSEN R1 DA77")
print("=" * 60)

if not MES_DIR.exists():
    print(f"❌ MES folder not found: {MES_DIR}")
    sys.exit(1)

channels = p2d.parse_ddd(MES_DIR, BASE)

# ── チャンネル一覧表示 ─────────────────────────────────────────────
gps_chs = {k: v for k, v in channels.items()
           if any(x in k.upper() for x in
                  ['GPS','LAT','LON','COURSE','V_GPS','HEADING','NMEA','CSEC'])}
print("\n🛰  GPS-related channels:")
for k, v in sorted(gps_chs.items()):
    raw = p2d.read_channel(MES_DIR, BASE, v)
    pct = np.percentile(raw, [0, 25, 50, 75, 100]) if len(raw) > 0 else [0]*5
    print(f"  {k:20s} ext={v['ext']:4s} scale={v['scale']:.6f} offset={v['offset']:4d} "
          f"len={len(raw):7d}  "
          f"range=[{pct[0]:.3f},{pct[4]:.3f}]  p50={pct[2]:.4f}")

# ── Latitude / Longitude 生 uint16 確認 ────────────────────────────
print("\n── Latitude raw uint16 inspection ──")
lat_info = channels.get("Latitude")
lon_info = channels.get("Longitude")

if lat_info is None or lon_info is None:
    print("❌ Latitude/Longitude channels not found")
    sys.exit(1)

# read_channel は (uint16 - offset) * scale を返す
# offset=1, scale=1.0 → raw_physical = uint16 - 1
# 元のuint16を復元: uint16 = raw_physical + 1
lat_raw = p2d.read_channel(MES_DIR, BASE, lat_info)   # = (uint16 - 1) * 1
lon_raw = p2d.read_channel(MES_DIR, BASE, lon_info)

lat_u16 = (lat_raw + lat_info["offset"]).astype(np.uint16)
lon_u16 = (lon_raw + lon_info["offset"]).astype(np.uint16)

print(f"  lat_u16 len={len(lat_u16)}  lon_u16 len={len(lon_u16)}")
print(f"  lat_u16 range: {lat_u16.min()} ~ {lat_u16.max()}")
print(f"  lon_u16 range: {lon_u16.min()} ~ {lon_u16.max()}")
print(f"  lat_u16 first 8: {lat_u16[:8].tolist()}")
print(f"  lon_u16 first 8: {lon_u16[:8].tolist()}")

# ── 各デコード方式を試す ──────────────────────────────────────────────
print("\n── Decode attempt: 2×uint16 → float32 (Little Endian) ──")

FORMATS = [
    ("<f",  "LE float32"),
    (">f",  "BE float32"),
    ("<I",  "LE uint32"),
    (">I",  "BE uint32"),
    ("<i",  "LE int32"),
    (">i",  "BE int32"),
]

def try_decode(u16_a: np.ndarray, label: str, expected_lo: float, expected_hi: float):
    """2サンプルペアをfloat32などにデコードして期待範囲と照合"""
    print(f"\n  [{label}] expecting {expected_lo:.1f} ~ {expected_hi:.1f}")
    found_any = False
    n = len(u16_a) // 2

    for fmt, fmt_name in FORMATS:
        hits = []
        for i in range(min(n, 1000)):
            a = int(u16_a[i*2])   & 0xFFFF
            b = int(u16_a[i*2+1]) & 0xFFFF
            try:
                val = struct.unpack(fmt, struct.pack("<HH", a, b))[0]
                if expected_lo <= val <= expected_hi:
                    hits.append((i, val))
            except Exception:
                pass
        if hits:
            vals = [h[1] for h in hits[:20]]
            print(f"    ✅ {fmt_name:12s}: {len(hits)} hits in first 1000 pairs  "
                  f"example={vals[0]:.6f}  median={np.median(vals):.6f}")
            found_any = True
        else:
            print(f"    ❌ {fmt_name:12s}: no hits")
    return found_any

lat_found = try_decode(lat_u16, "Latitude  (52~56°N)", 50.0, 56.0)
lon_found = try_decode(lon_u16, "Longitude (3~9°E)",   3.0,   9.0)

# ── 試行2: 4サンプルグループ ──────────────────────────────────────────
print("\n── Decode attempt: 4×uint16 → float32 ──")
FORMATS_4 = [("<f", "LE float32 [0:2]"), (">f", "BE float32 [0:2]"),
             ("<f", "LE float32 [1:3]"), (">f", "BE float32 [1:3]"),
             ("<f", "LE float32 [2:4]"), (">f", "BE float32 [2:4]")]

for chunk_start, (fmt, fmt_name) in [(0, ("<f", "LE [0:2]")), (0, (">f", "BE [0:2]")),
                                      (1, ("<f", "LE [1:3]")), (1, (">f", "BE [1:3]"))]:
    hits_lat, hits_lon = [], []
    for i in range(min(len(lat_u16)//4, 500)):
        base_i = i * 4 + chunk_start
        if base_i + 2 > len(lat_u16):
            break
        a_lat = int(lat_u16[base_i])   & 0xFFFF
        b_lat = int(lat_u16[base_i+1]) & 0xFFFF
        a_lon = int(lon_u16[base_i])   & 0xFFFF
        b_lon = int(lon_u16[base_i+1]) & 0xFFFF
        try:
            v_lat = struct.unpack(fmt, struct.pack("<HH", a_lat, b_lat))[0]
            v_lon = struct.unpack(fmt, struct.pack("<HH", a_lon, b_lon))[0]
            if 50.0 <= v_lat <= 56.0:
                hits_lat.append(v_lat)
            if 3.0 <= v_lon <= 9.0:
                hits_lon.append(v_lon)
        except Exception:
            pass
    if hits_lat:
        print(f"  ✅ Lat {fmt_name}: {len(hits_lat)} hits  median={np.median(hits_lat):.5f}°")
    if hits_lon:
        print(f"  ✅ Lon {fmt_name}: {len(hits_lon)} hits  median={np.median(hits_lon):.5f}°")

# ── 試行3: Lat_dez / Lon_dez (scale=0の謎チャンネル) の生バイト ───────
print("\n── Raw bytes of Lat_dez (ext=A45) ──")
lat_dez_path = MES_DIR / f"{BASE}.A45"
if lat_dez_path.exists():
    raw_bytes = lat_dez_path.read_bytes()
    print(f"  File size: {len(raw_bytes)} bytes")
    n_u16 = len(raw_bytes) // 2
    u16s = struct.unpack(f"<{n_u16}H", raw_bytes[:n_u16*2])
    print(f"  First 10 uint16: {list(u16s[:10])}")
    # float32として試す
    n_f32 = len(raw_bytes) // 4
    if n_f32 > 0:
        f32s = struct.unpack(f"<{n_f32}f", raw_bytes[:n_f32*4])
        lat_hits = [v for v in f32s[:200] if 50.0 <= v <= 56.0]
        lon_hits = [v for v in f32s[:200] if 3.0 <= v <= 9.0]
        print(f"  As LE float32 — lat hits(50-56°): {lat_hits[:5]}")
        print(f"  As LE float32 — lon hits(3-9°):   {lon_hits[:5]}")
else:
    print(f"  File not found: {lat_dez_path}")

# ── 試行4: V_GPS を使ったDead Reckoning可能性 ─────────────────────────
print("\n── V_GPS + Course dead-reckoning feasibility ──")
vgps_info = channels.get("V_GPS")
course_info = channels.get("Course")
if vgps_info and course_info:
    vgps   = p2d.read_channel(MES_DIR, BASE, vgps_info)
    course = p2d.read_channel(MES_DIR, BASE, course_info)
    n_laps, lap_times_ms = p2d.parse_lap(MES_DIR, BASE)
    sr = len(vgps) / (lap_times_ms[-1] / 1000.0) if n_laps > 0 else 100.0
    print(f"  V_GPS: {vgps.min():.1f} ~ {vgps.max():.1f} km/h  SR≈{sr:.1f}Hz")
    print(f"  Course: {course.min():.1f} ~ {course.max():.1f} °")
    # Dead-reckoning精度: ±1m/s速度誤差 × 100s → ±100m → ASSEN1周4km → ±2.5%
    print(f"  Dead-reckoning: V_GPS+Course積分で位置推定可能")
    print(f"  推定精度: V_GPS精度±0.1km/h → 1周で±数十m（相対比較には十分）")

# ── 結論 ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  RESULT SUMMARY")
print("=" * 60)
if lat_found or lon_found:
    print("✅ GPS float32 decode: 成功 — parse_2d_channels.py に実装可能")
else:
    print("❌ GPS float32 direct decode: 失敗")
    print("   → 代替案1: Lat_dez/Lon_dez の raw bytes を直接読む")
    print("   → 代替案2: V_GPS + Course の dead-reckoning 積分")
    print("   → 代替案3: 時間軸正規化のみ（0〜1 lap_progress）で Lap Overlay 実装")
    print()
    print("   【推奨】時間軸正規化 Lap Overlay を先行実装済み。")
    print("   GPS座標は別途 Lat_dez bytes 解析で継続調査。")
print("=" * 60)
