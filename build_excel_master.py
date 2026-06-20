#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_excel_master.py v2 — エンジニア向け DB Master を「OLD形式を保持して修正済みデータで再生成」。

方針(2026-06-18, Tatsuki確定):
  OLD `TS24 DB Master Back UP.xlsx` をテンプレートとして読み込み、各シートの
  ヘッダー/書式/列幅/役割を保持したまま、データ行のみ修正済み ts24_unified.db で差し替える。
  → 現場で「不満→過去事例→最適解」を引ける分析ワークブックを、正しい数値で復活させる。

シート扱い:
  [再生成(flat)] RUN_LOG, SESSION_SUMMARY, TYRE_LOG, LAP_TIMES, PERFORMANCE_CORRELATION,
                 DYNAMICS_ANALYSIS, LAP_SUSPENSION, PROBLEM_LIBRARY, BEST_WORST_ANALYSIS
  [保持(static/手入力/別ソース)] SOLUTION_SEARCH(手順), CHASSIS_GEO(手入力), DB_LOG, TREND_ANALYSIS
     ※ DB_LOG/TREND_ANALYSIS は区分レイアウトが複雑なため今回は旧内容を保持(別途再生成を検討)。
"""
import copy
import sqlite3
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

DB = Path(__file__).parent.parent / "02_DATABASE"
TEMPLATE = DB / "TS24 DB Master Back UP.xlsx"
OUT = DB / "TS24 DB Master.xlsx"
con = sqlite3.connect(DB / "ts24_unified.db"); con.row_factory = sqlite3.Row


def fmt_lap(s):
    if s is None: return None
    try: s = float(s)
    except (TypeError, ValueError): return None
    m = int(s // 60); return f"{m}:{s-60*m:06.3f}"


def q(sql, p=()): return con.execute(sql, p).fetchall()


_HFILL = PatternFill("solid", fgColor="1F3864")   # 列ヘッダ濃紺
_GFILL = PatternFill("solid", fgColor="2E5496")   # グループ見出し
_HFONT = Font(color="FFFFFF", bold=True)
_CEN = Alignment(horizontal="center", vertical="center")

def build_clean_sheet(wb, name, groups, headers, rows):
    """空列を持たないクリーンなシートに作り直す(元位置を保持)。
    groups=[(label,span),...] 1行目グループ見出し / headers=2行目列名 / rows=3行目以降データ。"""
    idx = wb.sheetnames.index(name)
    wb.remove(wb[name]); ws = wb.create_sheet(name, idx)
    c = 1
    for label, span in groups:
        ws.cell(1, c, label)
        if span > 1:
            ws.merge_cells(start_row=1, start_column=c, end_row=1, end_column=c + span - 1)
        cell = ws.cell(1, c); cell.fill = _GFILL; cell.font = _HFONT; cell.alignment = _CEN
        c += span
    for i, h in enumerate(headers, 1):
        cell = ws.cell(2, i, h); cell.fill = _HFILL; cell.font = _HFONT; cell.alignment = _CEN
    for r, row in enumerate(rows, 3):
        for i, v in enumerate(row, 1):
            ws.cell(r, i, v)
    ws.freeze_panes = "A3"
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, min(len(str(h)) + 3, 18))
    return len(rows)


def repopulate(ws, data_start, rows, ncols):
    """data_start 行以降を rows(list of list)で差し替え。列書式は元 data_start 行から踏襲。"""
    # 0) データ域(>=data_start)に掛かる結合セルを解除(区分見出し等。MergedCell書込不可対策)
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row >= data_start:
            ws.unmerge_cells(str(rng))
    # 1) 元 data_start 行の各列スタイルを退避
    styles = {}
    for c in range(1, ncols + 1):
        src = ws.cell(data_start, c)
        styles[c] = (copy.copy(src.font), copy.copy(src.fill), copy.copy(src.border),
                     copy.copy(src.alignment), src.number_format)
    # 2) 既存データ行を全消去(値のみ)
    for r in range(data_start, ws.max_row + 1):
        for c in range(1, ncols + 1):
            ws.cell(r, c).value = None
    # 3) 新データ書込 + スタイル適用
    for i, row in enumerate(rows):
        r = data_start + i
        for c in range(1, ncols + 1):
            cell = ws.cell(r, c)
            cell.value = row[c - 1] if c - 1 < len(row) else None
            fnt, fil, brd, aln, nf = styles[c]
            cell.font = copy.copy(fnt); cell.fill = copy.copy(fil)
            cell.border = copy.copy(brd); cell.alignment = copy.copy(aln)
            cell.number_format = nf
    return len(rows)


wb = openpyxl.load_workbook(TEMPLATE)  # 書式込みで読込(バックアップ自体は不変、保存先は OUT)
report = []

# 不要シート削除 (Tatsuki確定 2026-06-18): BEST_WORST_ANALYSIS / SESSION_SUMMARY / TYRE_LOG / CHASSIS_GEO
for _sh in ["BEST_WORST_ANALYSIS", "SESSION_SUMMARY", "TYRE_LOG", "CHASSIS_GEO"]:
    if _sh in wb.sheetnames:
        wb.remove(wb[_sh]); report.append((_sh + " (削除)", "—"))

# ── RUN_LOG (row4+, 43col): runs 全setup + comment + 意思決定列 ──
RUN_FIELDS = ["run_id","rider","circuit","session","run_no","weather","track_temp","air_temp",
  "fork_type","f_set_c","f_set_r","f_tos_spring","f_tos_length","f_spr_l","f_spr_r","f_preload",
  "f_oil_level","f_comp","f_reb","f_offset","f_offset2","f_hgt_top","f_hgt_bot","shock_type",
  "r_set_c","r_set_r","r_spr","r_preload","r_comp","r_reb","r_tos_spring","r_tos_length","shock_len",
  "link","ride_hgt","swing_arm","tyre_front","tyre_rear","comment"]
# 意思決定列(sparse): problem_log.description / setup_decision_log.rationale/expected_effect/result_eval
pdesc = {r["run_id"]: r["description"] for r in q("SELECT run_id,description FROM problem_log WHERE run_id IS NOT NULL")}
dec = {r["run_id_to"]: r for r in q("SELECT run_id_to,rationale,expected_effect,result_eval FROM setup_decision_log WHERE run_id_to IS NOT NULL")}
rows = []
for r in q(f"SELECT {','.join(RUN_FIELDS)} FROM runs ORDER BY (date IS NULL), date,rider,session,run_no"):
    base = [r[f] for f in RUN_FIELDS]
    rid = r["run_id"]; d = dec.get(rid)
    base += [pdesc.get(rid), d["rationale"] if d else None,
             d["expected_effect"] if d else None, d["result_eval"] if d else None]
    rows.append(base)
report.append(("RUN_LOG", repopulate(wb["RUN_LOG"], 4, rows, 43)))

# ── LAP_TIMES (row3+, 17col) ──
rows = []
for r in q("""SELECT l.run_id,l.lap_id,r.round,r.circuit,r.date,r.session,r.rider,r.run_no,
   l.lap_no,l.lap_time_s,l.is_outlap,r.weather,r.air_temp,r.track_temp,r.tyre_front,r.tyre_rear
   FROM laps l JOIN runs r USING(run_id) ORDER BY r.date,r.rider,r.session,r.run_no,l.lap_no"""):
    rows.append([r["run_id"],r["lap_id"],r["round"],r["circuit"],r["date"],r["session"],r["rider"],
        r["run_no"],r["lap_no"], fmt_lap(r["lap_time_s"]), r["lap_time_s"],
        ("Y" if r["is_outlap"] else ""), r["weather"],r["air_temp"],r["track_temp"],
        r["tyre_front"],r["tyre_rear"]])
report.append(("LAP_TIMES", repopulate(wb["LAP_TIMES"], 3, rows, 17)))

# ── per-run lap_suspension 集計 (非outlap) ── PERFORMANCE_CORRELATION / DYNAMICS_ANALYSIS 共用
agg = {r["run_id"]: r for r in q("""
  SELECT ls.run_id, count(*) n,
    round(avg(ls.apex_susF_avg),2) apex_susf, round(avg(ls.apex_susR_avg),2) apex_susr,
    round(avg(ls.wf_f_apex_n),1) wf_f, round(avg(ls.wf_r_apex_n),1) wf_r,
    round(avg(ls.apex_spd_avg),1) apex_spd, round(avg(ls.apex_count),1) apex_cnt,
    round(avg(ls.brk_susF_avg),2) brk_susf, round(avg(ls.brk_susR_avg),2) brk_susr,
    round(avg(ls.brk_spd_avg),1) brk_spd, round(avg(ls.brk_count),1) brk_cnt,
    round(avg(ls.fullbrk_susF),2) fb_susf, round(avg(ls.fullbrk_susR),2) fb_susr, round(avg(ls.fullbrk_count),1) fb_cnt,
    round(avg(ls.ce_susF_avg),2) ce_susf, round(avg(ls.ce_susR_avg),2) ce_susr,
    round(avg(ls.ce_spd_avg),1) ce_spd, round(avg(ls.ce_count),1) ce_cnt,
    round(avg(ls.f_dive_spd),0) f_dive, round(avg(ls.f_reb_spd),0) f_reb,
    round(avg(ls.r_dive_spd),0) r_dive, round(avg(ls.r_reb_spd),0) r_reb,
    round(avg(ls.rear_light_brk),1) rear_light,
    round(avg(ls.brk_f_dive_spd_avg),0) brk_f_dive_avg, round(avg(ls.brk_f_dive_spd_peak),0) brk_f_dive_peak,
    round(avg(ls.ce_r_spd_avg),0) ce_r_avg, round(avg(ls.ce_r_spd_peak),0) ce_r_peak,
    round(avg(ls.ph12_rear0_s),2) ph12_rear0
  FROM lap_suspension ls JOIN laps l ON ls.lap_id=l.lap_id
  WHERE l.is_outlap=0 GROUP BY ls.run_id""")}

# ── PERFORMANCE_CORRELATION (row4+, 22col) + Rank/Gap/Tier ──
perf = {r["run_id"]: r for r in q("SELECT * FROM performance")}
runmeta = {r["run_id"]: r for r in q("SELECT run_id,rider,circuit,round,session,run_no,date FROM runs")}
lap_run_ids = {r["run_id"] for r in q("SELECT DISTINCT run_id FROM laps")}  # 実走Runのみ(setup-only除外)
# Rank/Gap/Tier: (round,circuit,rider) 内 best_lap_s 昇順
from collections import defaultdict
groups = defaultdict(list)
for rid, p in perf.items():
    if p["best_lap_s"] is not None:
        m = runmeta.get(rid)
        if m: groups[(m["round"], m["circuit"], m["rider"])].append((rid, p["best_lap_s"]))
rank_info = {}
for key, lst in groups.items():
    lst.sort(key=lambda x: x[1]); n = len(lst); best = lst[0][1]
    for i, (rid, bl) in enumerate(lst):
        tier = "FAST" if i < (n + 1) // 2 else "SLOW"
        rank_info[rid] = (f"{i+1}/{n}", round(bl - best, 3), tier)
rows = []
for rid, m in sorted(runmeta.items(), key=lambda kv: (kv[1]["date"] or "", kv[1]["rider"], kv[1]["session"])):
    if rid not in lap_run_ids: continue   # 実走(2D)のあるRunのみ
    p = perf.get(rid); a = agg.get(rid); ri = rank_info.get(rid, ("", "", ""))
    if not p: continue
    rows.append([rid, None, m["rider"], m["circuit"], m["date"], m["session"], m["run_no"],
        fmt_lap(p["best_lap_s"]), fmt_lap(p["run_avg_lap_s"]), p["n_laps"],
        a["apex_susf"] if a else None, a["apex_susr"] if a else None,
        a["wf_f"] if a else None, a["wf_r"] if a else None, a["apex_spd"] if a else None,
        None,  # APEX ax: 新スキーマ未保持
        a["brk_susf"] if a else None, a["brk_susr"] if a else None, a["brk_spd"] if a else None,
        ri[0], ri[1], ri[2]])
report.append(("PERFORMANCE_CORRELATION", repopulate(wb["PERFORMANCE_CORRELATION"], 4, rows, 22)))
# Fast/Slow を視覚的に強調: Tier列(22)を緑/赤で塗り、RUN_ID(1)・Tierを太字に
_FAST_F = PatternFill("solid", fgColor="C6EFCE"); _FAST_T = Font(color="006100", bold=True)
_SLOW_F = PatternFill("solid", fgColor="FFC7CE"); _SLOW_T = Font(color="9C0006", bold=True)
_pw = wb["PERFORMANCE_CORRELATION"]
for r in range(4, _pw.max_row + 1):
    tier = _pw.cell(r, 22).value
    if tier == "FAST": fill, fnt = _FAST_F, _FAST_T
    elif tier == "SLOW": fill, fnt = _SLOW_F, _SLOW_T
    else: continue
    for c in (1, 20, 21, 22):   # RUN_ID, Rank, Gap, Tier
        _pw.cell(r, c).fill = fill; _pw.cell(r, c).font = copy.copy(fnt)
    _pw.cell(r, 22).alignment = Alignment(horizontal="center")

# ── DYNAMICS_ANALYSIS: 新3エリア定義で埋まる列のみ(空列 SR/ax/Pit×4/Tyre×8 を廃止)・グループ見出し付き ──
DYN_GROUPS = [("INFO", 8), ("APEX (MID-CORNER)", 4), ("BRAKING ENTRY", 4), ("FULL BRAKING", 3),
              ("CORNER EXIT", 4), ("DAMPING speed mm/s + Rear-light%", 10)]
DYN_HEADERS = ["RUN_ID","Round","Date","Circuit","Session","Rider","Run","Laps",
    "Count","Spd(km/h)","SusF(mm)","SusR(mm)",
    "Count","Spd(km/h)","SusF(mm)","SusR(mm)",
    "Count","SusF(mm)","SusR(mm)",
    "Count","Spd(km/h)","SusF(mm)","SusR(mm)",
    "F-Dive","F-Reb","R-Dive","R-Reb","RearLight%",
    "Brk F-Dive Avg","Brk F-Dive Peak","CE R-Spd Avg","CE R-Spd Peak","PH1-2 Rear@0[s]"]
rows = []
for rid, m in sorted(runmeta.items(), key=lambda kv: (kv[1]["date"] or "", kv[1]["rider"], kv[1]["session"])):
    if rid not in lap_run_ids: continue   # 実走(2D)のあるRunのみ
    a = agg.get(rid); p = perf.get(rid)
    rows.append([rid, m["round"], m["date"], m["circuit"], m["session"], m["rider"], m["run_no"],
        p["n_laps"] if p else None,
        a["apex_cnt"] if a else None, a["apex_spd"] if a else None, a["apex_susf"] if a else None, a["apex_susr"] if a else None,
        a["brk_cnt"] if a else None, a["brk_spd"] if a else None, a["brk_susf"] if a else None, a["brk_susr"] if a else None,
        a["fb_cnt"] if a else None, a["fb_susf"] if a else None, a["fb_susr"] if a else None,
        a["ce_cnt"] if a else None, a["ce_spd"] if a else None, a["ce_susf"] if a else None, a["ce_susr"] if a else None,
        a["f_dive"] if a else None, a["f_reb"] if a else None, a["r_dive"] if a else None, a["r_reb"] if a else None,
        a["rear_light"] if a else None,
        a["brk_f_dive_avg"] if a else None, a["brk_f_dive_peak"] if a else None,
        a["ce_r_avg"] if a else None, a["ce_r_peak"] if a else None,
        a["ph12_rear0"] if a else None])
report.append(("DYNAMICS_ANALYSIS", build_clean_sheet(wb, "DYNAMICS_ANALYSIS", DYN_GROUPS, DYN_HEADERS, rows)))

# ── PROBLEM_LIBRARY (row4+, 7col): problem_library テーブル直 ──
rows = [[r["id"],r["phase_code"],r["phase_name"],r["fase_it"],r["complaint_it"],r["complaint_en"],r["tags"]]
        for r in q("SELECT id,phase_code,phase_name,fase_it,complaint_it,complaint_en,tags FROM problem_library ORDER BY id")]
report.append(("PROBLEM_LIBRARY", repopulate(wb["PROBLEM_LIBRARY"], 4, rows, 7)))

# ── LAP_SUSPENSION (per-lap 全件): 旧シートは雛形のみ。ヘッダ+全データを書く ──
ws = wb["LAP_SUSPENSION"]
LS_COLS = ["lap_id","run_id","round","circuit","session","rider","run_no","lap_no","date","lap_time_s","lap_time_fmt",
  "apex_count","apex_spd_avg","apex_susF_avg","apex_susR_avg","wf_f_apex_n","wf_r_apex_n",
  "brk_count","brk_spd_avg","brk_susF_avg","brk_susR_avg","wf_f_brk_n","wf_r_brk_n",
  "fullbrk_count","fullbrk_susF","fullbrk_susR",
  "ce_count","ce_spd_avg","ce_susF_avg","ce_susR_avg","wf_f_ce_n","wf_r_ce_n",
  "f_dive_spd","f_reb_spd","r_dive_spd","r_reb_spd","rear_light_brk",
  "brk_f_dive_spd_avg","brk_f_dive_spd_peak","ce_r_spd_avg","ce_r_spd_peak","ph12_rear0_s",
  "lap_susF_mean","lap_susF_min","lap_susF_max","lap_susR_mean"]
# 旧の title(row1)を保持、row2=ヘッダ、row3+=データ。全LS_COLS分のヘッダを書く
# (旧実装は ws.max_column=34 で頭打ち→ r_dive_spd 以降のヘッダが欠落していた)。
# スタイルは既存ヘッダ cell(2,1) から複製して書式を維持。
from copy import copy as _copyst
_h0 = ws.cell(2, 1)
for c in range(1, len(LS_COLS) + 1):
    cell = ws.cell(2, c)
    cell.value = LS_COLS[c-1]
    if c > 1:
        cell.font = _copyst(_h0.font); cell.fill = _copyst(_h0.fill)
        cell.alignment = _copyst(_h0.alignment); cell.border = _copyst(_h0.border)
ls_rows = [[r[c] for c in LS_COLS] for r in q(f"SELECT {','.join(LS_COLS)} FROM lap_suspension ORDER BY run_id,lap_no")]
report.append(("LAP_SUSPENSION", repopulate(ws, 3, ls_rows, len(LS_COLS))))

# ── 保持シート(変更なし): SOLUTION_SEARCH(手順), DB_LOG, TREND_ANALYSIS ──
for sh in ["SOLUTION_SEARCH","DB_LOG","TREND_ANALYSIS"]:
    if sh in wb.sheetnames:
        report.append((sh + " (保持/未再生成)", "—"))

con.close()
wb.save(OUT)
print(f"保存: {OUT}")
print(f"シート: {wb.sheetnames}")
for name, n in report:
    print(f"  {name:32} {n}")
