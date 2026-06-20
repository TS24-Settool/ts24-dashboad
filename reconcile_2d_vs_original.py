#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reconcile_2d_vs_original.py  (read-only)
DATA 2D の .MES と Data_Base_TS24_ORIGINAL.xlsx の Run を突合し、カバレッジを報告する。
DBには一切書き込まない。マッピング精度を確認するための診断ツール。
"""
import re, sys, importlib.util
from pathlib import Path
from collections import defaultdict, Counter

SCRIPT_DIR = Path(__file__).parent
ROOT       = SCRIPT_DIR.parent
DATA_2D    = ROOT / "DATA 2D"
ORIGINAL   = ROOT / "04_REFERENCE" / "Data_Base_TS24_ORIGINAL.xlsx"

# ── parse_2d_channels から低レベル関数を借りる ──
spec = importlib.util.spec_from_file_location("p2d", SCRIPT_DIR / "parse_2d_channels.py")
p2d  = importlib.util.module_from_spec(spec); spec.loader.exec_module(p2d)
parse_hed            = p2d.parse_hed
_event_key_from_path = p2d._event_key_from_path
_build_event_meta    = p2d._build_event_meta

# ─────────────────────────────────────────────
#  正規化
# ─────────────────────────────────────────────
def circuit_canon(c):
    if not c: return ""
    u = re.sub(r"[^A-Z0-9]", "", str(c).upper())
    table = {
        "PHILIPISLAND":"PHILLIPISLAND", "PHILLIPISLAND":"PHILLIPISLAND",
        "PHILLIPISISLAND":"PHILLIPISLAND",
        "BALATON":"BALATON", "BALATONPARK":"BALATON",
        "MOTORLANDARAGON":"ARAGON", "ARAGON":"ARAGON",
        "MAGNYCOURS":"MAGNYCOURS",
        "WORKSHOP":"PHILLIPISLAND", "AUSTRALIA":"PHILLIPISLAND",
    }
    return table.get(u, u)

_ROUND_NORM = {f"R0{i}":f"ROUND{i}" for i in range(1,10)}
_ROUND_NORM.update({f"R{i}":f"ROUND{i}" for i in range(1,12)})
_ROUND_NORM.update({f"R1{i}":f"ROUND1{i}" for i in range(0,3)})
_ROUND_NORM.update({f"T0{i}":f"TEST{i}" for i in range(1,7)})
_ROUND_NORM.update({f"T{i}":f"TEST{i}" for i in range(1,7)})
_ROUND_NORM.update({f"TEST{i}":f"TEST{i}" for i in range(1,7)})

def round_canon(ekey, folder):
    for src in (ekey, folder):
        if not src: continue
        u = src.upper()
        m = re.search(r"(ROUND\s*\d+|TEST\s*\d+|R\d+|T\d+)", u)
        if m:
            tok = re.sub(r"\s+","",m.group(1))
            if tok in _ROUND_NORM: return _ROUND_NORM[tok]
            if tok.startswith("ROUND") or tok.startswith("TEST"): return tok
    return ""

def session_canon_2d(base, rnd):
    """2Dファイル名 base + round から Original語彙のsessionへ。"""
    pre = re.match(r"^([A-Za-z]+\d*)", base)
    pre = pre.group(1).upper() if pre else ""
    is_test = rnd.startswith("TEST")
    # 日 (test): D1/L1->DAY1, D2/L2->DAY2
    day = None
    md = re.match(r"^(D|L)(\d)", pre)
    if md: day = f"DAY{md.group(2)}"
    # race weekend sessions
    if re.match(r"^F", pre):  return "FP"
    if re.match(r"^Q", pre):  return "QP"
    if re.match(r"^WUP?2", pre) or pre in ("WU2",): return "WUP2"
    if re.match(r"^WUP?1", pre) or pre in ("WU1",): return "WUP1"
    if re.match(r"^WUP?$", pre) or pre in ("WU",): return "WUP1"
    if re.match(r"^R1", pre) or pre=="RACE1": return "RACE1"
    if re.match(r"^R2", pre) or pre=="RACE2": return "RACE2"
    if re.match(r"^SP", pre): return "SP"
    if is_test and day: return f"{rnd}_{day}"
    if is_test: return f"{rnd}_DAY1"
    return pre

def session_canon_orig(s, rider=None):
    u = re.sub(r"\s+"," ", str(s).strip().upper())
    m = re.match(r"^TEST\s*(\d)\s*DAY\s*(\d)$", u)
    if m: return f"TEST{m.group(1)}_DAY{m.group(2)}"
    return re.sub(r"\s+","",u)

def key(rider, circuit_c, session_c, run):
    try: n = int(float(run))
    except Exception: n = 1
    return f"{rider}|{circuit_c}|{session_c}|R{n}"

# ─────────────────────────────────────────────
#  Original 読み込み
# ─────────────────────────────────────────────
import openpyxl
wb = openpyxl.load_workbook(ORIGINAL, read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(min_row=2, values_only=True))
hdr = [str(h).strip().upper() if h else "" for h in rows[0]]
iR,iC,iS,iN = hdr.index("RIDER"),hdr.index("CIRCUIT"),hdr.index("SESSION"),hdr.index("RUN")
orig_keys = {}
for r in rows[1:]:
    if not r or r[iR] is None: continue
    rider=str(r[iR]).strip(); circ=circuit_canon(r[iC]); sess=session_canon_orig(r[iS]); run=r[iN]
    k = key(rider, circ, sess, run)
    orig_keys[k] = (rider, str(r[iC]).strip(), str(r[iS]).strip(), run)
print(f"[Original] {len(orig_keys)} 一意Run")

# ─────────────────────────────────────────────
#  DATA 2D 走査 (metadata only)
# ─────────────────────────────────────────────
event_meta = _build_event_meta(DATA_2D)
NOISE = re.compile(r"ACCENSIONE|RD\d+-S\d+|-KAW_|^D0-", re.I)

mes_files = [p for p in DATA_2D.rglob("*.MES")]
twoD_keys = defaultdict(list)
skipped = Counter()
unmatched_2d = []
sess_2d_files = Counter()   # (rider,circuit,session) -> 2Dファイル数
for p in mes_files:
    name = p.name
    if "_COPY" in str(p):       skipped["copy"]+=1; continue
    if "DATA WSSP KAWASAKI" in str(p): skipped["legacy"]+=1; continue
    if NOISE.search(name):      skipped["noise"]+=1; continue
    base = name[:-4]
    # rider
    up = (name + " " + p.parent.name).upper()
    rider = "JA52" if ("JA52" in up or "#52" in up or "-52" in up or p.parent.name in("52","JA52")) else ("DA77" if ("DA77" in up or "#77" in up or "-77" in up or p.parent.name in("77","DA77")) else "")
    if not rider:
        try:
            hed = parse_hed(p, base); rn = hed.get("Rider Number","")
            rider = "DA77" if "77" in rn else ("JA52" if "52" in rn else "")
        except Exception: pass
    if not rider: skipped["norider"]+=1; continue
    ekey = _event_key_from_path(p)
    folder = p.parents[len(p.parents)-1-0].name if False else ""
    # use top event folder under DATA 2D
    rel = p.relative_to(DATA_2D)
    top = rel.parts[0] if rel.parts else ""
    rnd = round_canon(ekey, top)
    circ = circuit_canon(event_meta.get(ekey,{}).get("circuit","")) if ekey else ""
    if not circ:
        # infer circuit from top folder via none; try hed
        try:
            hed = parse_hed(p, base); circ = circuit_canon(hed.get("Circuit",""))
        except Exception: pass
    sess = session_canon_2d(base, rnd)
    run_m = re.search(r"-(\d+)$", base)
    run = int(run_m.group(1)) if run_m else 1
    k = key(rider, circ, sess, run)
    twoD_keys[k].append(str(rel))
    sess_2d_files[(rider, circ, sess)] += 1
    if k not in orig_keys:
        unmatched_2d.append((k, str(rel)))

# Original: (rider,circuit,session) -> run数
from collections import Counter as _C
orig_sess_runs = _C()
for k in orig_keys:
    rd,ci,se,_ = k.split("|")
    orig_sess_runs[(rd,ci,se)] += 1

print(f"[2D] .MES総数={len(mes_files)} | skip={dict(skipped)} | 一意2Dキー={len(twoD_keys)}")

matched = [k for k in orig_keys if k in twoD_keys]
orig_no_2d = [k for k in orig_keys if k not in twoD_keys]
print(f"\n=== カバレッジ ===")
print(f"Original Run のうち 2Dあり : {len(matched)}/{len(orig_keys)}")
print(f"Original Run のうち 2Dなし : {len(orig_no_2d)}")
print(f"2Dキーのうち Original未該当: {len(set(k for k,_ in unmatched_2d))}")

print(f"\n--- 2Dなし Original Run (最大40) ---")
for k in sorted(orig_no_2d)[:40]:
    print("  ", k)

print(f"\n--- Original未該当の2Dキー (最大25) ---")
seen=set()
for k,rel in unmatched_2d:
    if k in seen: continue
    seen.add(k)
    print(f"   {k}   ({rel})")
    if len(seen)>=25: break

# Original 重複キー (247 vs 一意235 の差)
print(f"\n--- Original 重複キー (同一 rider|circuit|session|run が複数行) ---")
allk=_C()
for r in rows[1:]:
    if not r or r[iR] is None: continue
    allk[key(str(r[iR]).strip(), circuit_canon(r[iC]), session_canon_orig(r[iS]), r[iN])]+=1
for k,c in allk.items():
    if c>1: print(f"   x{c}  {k}")

# セッション別: 2Dファイル数 vs Original Run数 (両方に存在するもの)
print(f"\n--- (rider,circuit,session): 2Dファイル数 vs OriginalRun数 ---")
allsess = sorted(set(list(sess_2d_files.keys())+list(orig_sess_runs.keys())))
for s in allsess:
    n2 = sess_2d_files.get(s,0); no = orig_sess_runs.get(s,0)
    if n2 and no:
        flag = "  <<< 不一致" if n2!=no else ""
        print(f"   {s[0]:5} {s[1]:14} {s[2]:14} | 2D={n2:2}  Orig={no:2}{flag}")
