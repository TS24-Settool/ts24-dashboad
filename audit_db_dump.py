#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_db_dump.py — ts24_unified.db の全数値整合性を監査用に網羅ダンプする。
マルチエージェント監査の入力。判定はせず「数値 + 事前フラグ候補」を出力する。
出力: /tmp/ts24_audit_data.md
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "02_DATABASE" / "ts24_unified.db"
OUT = Path("/tmp/ts24_audit_data.md")

# サーキット長(m)。レイアウト確認用。
TRACK_M = {"PHILLIPISLAND":4448, "PORTIMAO":4592, "ASSEN":4555, "BALATON":4115,
           "MOST":4212, "ARAGON":5077, "JEREZ":4423, "CREMONA":3768, "MISANO":4226,
           "MAGNYCOURS":4411, "ESTORIL":4182, "DONINGTON":4023}

con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
L = []
def w(s=""): L.append(s)
def q(sql, p=()): return con.execute(sql, p).fetchall()

w("# TS24 ts24_unified.db 数値整合性 監査データ")
w(f"DB: {DB}")
w("各セクションは数値と事前フラグ候補(⚠)のみ。判定はエージェントが行う。\n")

# ── 0. テーブル件数 ──
w("## 0. テーブル件数 / 参照整合性")
for t in ["events","runs","laps","lap_metrics","lap_suspension","performance",
          "race_results","pdf_lap_times","run_tags","tags","best_worst_pairs"]:
    try: n=q(f"SELECT count(*) c FROM {t}")[0]["c"]
    except Exception as e: n=f"ERR {e}"
    w(f"- {t}: {n}")
w("\n### orphan/参照チェック (0であるべき)")
checks = {
 "laps.run_id not in runs": "SELECT count(*) c FROM laps WHERE run_id NOT IN(SELECT run_id FROM runs)",
 "lap_metrics.lap_id not in laps": "SELECT count(*) c FROM lap_metrics WHERE lap_id NOT IN(SELECT lap_id FROM laps)",
 "lap_suspension.run_id not in runs": "SELECT count(*) c FROM lap_suspension WHERE run_id NOT IN(SELECT run_id FROM runs)",
 "lap_suspension.lap_id not in laps": "SELECT count(*) c FROM lap_suspension WHERE lap_id NOT IN(SELECT lap_id FROM laps)",
 "performance.run_id not in runs": "SELECT count(*) c FROM performance WHERE run_id NOT IN(SELECT run_id FROM runs)",
 "runs.event_id not in events (has_2d側)": "SELECT count(*) c FROM runs WHERE event_id IS NOT NULL AND event_id NOT IN(SELECT event_id FROM events)",
 "laps count vs lap_suspension count": "SELECT (SELECT count(*) FROM laps)-(SELECT count(*) FROM lap_suspension) c",
 "lap_metrics rows vs laps*3": "SELECT (SELECT count(*) FROM lap_metrics)-(SELECT count(*) FROM laps)*3 c",
 "performance rows vs runs": "SELECT (SELECT count(*) FROM performance)-(SELECT count(*) FROM runs) c",
}
for name,sql in checks.items():
    w(f"- {name}: {q(sql)[0]['c']}")

# ── 1. ラップタイム物理妥当性 ──
w("\n## 1. ラップタイム 物理妥当性 (is_outlap=0)")
w("track_len/median から平均速度を推定。>330km/h は物理的に不可能(=stray疑い)。")
w("| round | circuit | n | min | p10 | median | max | track_m | min→km/h | med→km/h |")
w("|---|---|--|--|--|--|--|--|--|--|")
for r in q("""SELECT round,circuit, count(*) n, min(lap_time_s) mn, max(lap_time_s) mx,
              avg(lap_time_s) av FROM laps l JOIN runs r USING(run_id)
              WHERE is_outlap=0 AND lap_time_s>20 GROUP BY round,circuit ORDER BY round"""):
    circ=r["circuit"]; tl=TRACK_M.get(circ)
    times=sorted(x["lap_time_s"] for x in q("""SELECT lap_time_s FROM laps l JOIN runs r USING(run_id)
              WHERE r.round=? AND r.circuit=? AND is_outlap=0 AND lap_time_s>20""",(r["round"],circ)))
    med=times[len(times)//2] if times else None
    p10=times[max(0,len(times)//10)] if times else None
    mnk = round(tl/r['mn']*3.6,0) if tl and r['mn'] else "?"
    medk = round(tl/med*3.6,0) if tl and med else "?"
    flag=" ⚠min非現実" if (tl and r['mn'] and tl/r['mn']*3.6>330) else ""
    w(f"| {r['round']} | {circ} | {r['n']} | {r['mn']:.1f} | {p10:.1f} | {med:.1f} | {r['mx']:.1f} | {tl} | {mnk} | {medk} |{flag}")

w("\n### ⚠ 個別candidate stray (is_outlap=0 かつ track_len基準で平均>330km/hを要する短ラップ)")
rows=q("""SELECT l.run_id,l.lap_no,l.lap_time_s,r.circuit FROM laps l JOIN runs r USING(run_id)
          WHERE is_outlap=0 AND lap_time_s>20 ORDER BY lap_time_s""")
cnt=0
for r in rows:
    tl=TRACK_M.get(r["circuit"])
    if tl and r["lap_time_s"] and tl/r["lap_time_s"]*3.6 > 330:
        w(f"- {r['run_id']} L{r['lap_no']} = {r['lap_time_s']}s → {round(tl/r['lap_time_s']*3.6)}km/h"); cnt+=1
if not cnt: w("- なし")

w("\n### best_lap_s(2D) vs race_results best_lap(PDF) 突合 (DA77/JA52・同round/session)")
w("差>1.0s は不整合候補。")
for r in q("""SELECT p.run_id,p.rider,p.round,p.session,p.best_lap_s lap2d, rr.best_lap_s pdf
   FROM performance p JOIN race_results rr
     ON rr.round=p.round AND rr.session_type=p.session
    AND rr.rider_num=CASE p.rider WHEN 'JA52' THEN 52 WHEN 'DA77' THEN 77 END
   WHERE p.best_lap_s IS NOT NULL AND rr.best_lap_s IS NOT NULL
   ORDER BY abs(p.best_lap_s-rr.best_lap_s) DESC LIMIT 25"""):
    d=abs((r["lap2d"] or 0)-(r["pdf"] or 0)); flag=" ⚠" if d>1.0 else ""
    w(f"- {r['run_id']}: 2D={r['lap2d']} PDF={r['pdf']} Δ={d:.3f}{flag}")

# ── 2. lap_metrics 3エリア ──
w("\n## 2. lap_metrics 3エリア (フィルタ範囲内であるべき=構造的保証)")
AREAS={"MID_CORNER":{"SUSP_FRONT":(50,100),"SUSP_REAR":(8,40),"BRAKE_FRONT":(-0.3,3),"THROTTLE":(-0.5,5)},
       "FULL_BRAKING":{"SUSP_FRONT":(90,130),"SUSP_REAR":(-0.5,2),"BRAKE_FRONT":(9,20)},
       "CORNER_EXIT":{"SUSP_FRONT":(0,70),"SUSP_REAR":(2,30),"THROTTLE":(50,100),"BRAKE_FRONT":(-0.5,0)}}
for area,conds in AREAS.items():
    row=q("""SELECT count(*) c, sum(CASE WHEN n=0 THEN 1 ELSE 0 END) zero,
             sum(CASE WHEN susf IS NULL THEN 1 ELSE 0 END) nullf,
             min(susf) mnf,max(susf) mxf,min(susr) mnr,max(susr) mxr,
             min(brake) mnb,max(brake) mxb,min(thr) mnt,max(thr) mxt
             FROM lap_metrics WHERE area=?""",(area,))[0]
    w(f"\n### {area}  rows={row['c']} n=0:{row['zero']} susfNULL:{row['nullf']}")
    w(f"- susf [{row['mnf']},{row['mxf']}] (定義 {conds.get('SUSP_FRONT')})")
    w(f"- susr [{row['mnr']},{row['mxr']}] (定義 {conds.get('SUSP_REAR')})")
    w(f"- brake [{row['mnb']},{row['mxb']}] (定義 {conds.get('BRAKE_FRONT')})")
    w(f"- thr [{row['mnt']},{row['mxt']}] (定義 {conds.get('THROTTLE')})")
    # 範囲外フラグ
    for ch,col in [("SUSP_FRONT","susf"),("SUSP_REAR","susr"),("BRAKE_FRONT","brake"),("THROTTLE","thr")]:
        if ch in conds:
            lo,hi=conds[ch]
            oob=q(f"SELECT count(*) c FROM lap_metrics WHERE area=? AND {col} IS NOT NULL AND ({col}<? OR {col}>?)",(area,lo-0.01,hi+0.01))[0]["c"]
            if oob: w(f"  ⚠ {col} 範囲外 {oob}件 (定義{lo}〜{hi})")

# ── 3. lap_suspension 派生整合 ──
w("\n## 3. lap_suspension 派生整合 (lap_metrics/laps/runs と一致すべき)")
w("### apex_susF_avg vs lap_metrics MID_CORNER.susf (一致すべき)")
mismatch=q("""SELECT count(*) c FROM lap_suspension ls
  JOIN lap_metrics m ON m.lap_id=ls.lap_id AND m.area='MID_CORNER'
  WHERE ls.apex_susF_avg IS NOT NULL AND m.susf IS NOT NULL
    AND abs(ls.apex_susF_avg-m.susf)>0.05""")[0]["c"]
w(f"- apex_susF≠MID_CORNER.susf: {mismatch}件")
w("### lap_susF_mean vs laps.susf_mean (一致すべき)")
mm2=q("""SELECT count(*) c FROM lap_suspension ls JOIN laps l USING(lap_id)
  WHERE ls.lap_susF_mean IS NOT NULL AND l.susf_mean IS NOT NULL AND abs(ls.lap_susF_mean-l.susf_mean)>0.05""")[0]["c"]
w(f"- lap_susF_mean≠laps.susf_mean: {mm2}件")
w("### WheelForce: wf_f_apex_n ≈ apex_susF_avg×(f_spr_l+f_spr_r)/2 (サンプル10件)")
for r in q("""SELECT ls.lap_id,ls.apex_susF_avg sf,ls.wf_f_apex_n wf,r.f_spr_l fl,r.f_spr_r fr,
              ls.apex_susR_avg sr,ls.wf_r_apex_n wfr,r.r_spr rr
   FROM lap_suspension ls JOIN runs r ON ls.run_id=r.run_id
   WHERE ls.wf_f_apex_n IS NOT NULL AND r.f_spr_l IS NOT NULL LIMIT 10"""):
    try:
        exp=r["sf"]*((float(r["fl"])+float(r["fr"]))/2)
        ok="OK" if abs(exp-r["wf"])<1 else "⚠"
        expr=r["sr"]*float(r["rr"])*0.5 if r["sr"] and r["rr"] else None
        okr=("OK" if (expr and abs(expr-(r['wfr'] or 0))<1) else "⚠") if expr else "-"
        w(f"- {r['lap_id']}: WF_F={r['wf']} exp={exp:.1f}[{ok}]  WF_R={r['wfr']} exp={expr and round(expr,1)}[{okr}]")
    except Exception as e:
        w(f"- {r['lap_id']}: calc err {e}")

# ── 4. performance ──
w("\n## 4. performance 整合")
w("### best_lap_s vs min(laps is_outlap=0) (一致すべき)")
bad=q("""SELECT p.run_id,p.best_lap_s pb,m.mn FROM performance p
  JOIN (SELECT run_id,min(lap_time_s) mn FROM laps WHERE is_outlap=0 GROUP BY run_id) m USING(run_id)
  WHERE p.best_lap_s IS NOT NULL AND abs(p.best_lap_s-m.mn)>0.05""")
w(f"- best_lap_s≠min(非outlap): {len(bad)}件")
for r in bad[:15]: w(f"  ⚠ {r['run_id']}: perf={r['pb']} min非outlap={r['mn']}")
w("### run_avg_lap_s < best_lap_s (あり得ない)")
inv=q("SELECT run_id,best_lap_s,run_avg_lap_s FROM performance WHERE best_lap_s IS NOT NULL AND run_avg_lap_s IS NOT NULL AND run_avg_lap_s<best_lap_s-0.001")
w(f"- avg<best: {len(inv)}件")
for r in inv[:10]: w(f"  ⚠ {r['run_id']}: best={r['best_lap_s']} avg={r['run_avg_lap_s']}")
w(f"### session_position 設定数: "+str(q('SELECT count(*) c FROM performance WHERE session_position IS NOT NULL')[0]['c']))

# ── 5. runs / setup ──
w("\n## 5. runs / setup")
w("### source 内訳")
for r in q("SELECT source,count(*) c FROM runs GROUP BY source ORDER BY c DESC"):
    w(f"- {r['source']}: {r['c']}")
w("### run_id 重複")
dup=q("SELECT run_id,count(*) c FROM runs GROUP BY run_id HAVING c>1")
w(f"- 重複run_id: {len(dup)}")
for r in dup: w(f"  ⚠ {r['run_id']} x{r['c']}")
w("### 自然キー(date,round,circuit,session,rider,run_no) 重複")
dk=q("SELECT date,round,circuit,session,rider,run_no,count(*) c FROM runs GROUP BY date,round,circuit,session,rider,run_no HAVING c>1")
w(f"- 重複: {len(dk)}")
for r in dk: w(f"  ⚠ {r['date']}/{r['round']}/{r['circuit']}/{r['session']}/{r['rider']}/R{r['run_no']} x{r['c']}")
w("### has_2d vs 実laps / n_laps vs 実laps")
mm=q("""SELECT r.run_id,r.has_2d,r.n_laps, (SELECT count(*) FROM laps WHERE run_id=r.run_id) actual
        FROM runs r""")
h_bad=[x for x in mm if (x["has_2d"]==1) != (x["actual"]>0)]
n_bad=[x for x in mm if (x["n_laps"] or 0)!=x["actual"]]
w(f"- has_2d と実lap有無の不一致: {len(h_bad)}")
for r in h_bad[:10]: w(f"  ⚠ {r['run_id']}: has_2d={r['has_2d']} actual_laps={r['actual']}")
w(f"- n_laps と実lap数の不一致: {len(n_bad)}")
for r in n_bad[:15]: w(f"  ⚠ {r['run_id']}: n_laps={r['n_laps']} actual={r['actual']}")
w("### created_at/updated_at NULL")
w(f"- runs NULL: {q('SELECT count(*) c FROM runs WHERE created_at IS NULL OR updated_at IS NULL')[0]['c']}")
w(f"- laps NULL: {q('SELECT count(*) c FROM laps WHERE created_at IS NULL OR updated_at IS NULL')[0]['c']}")

# ── 6. race_results / pdf_lap_times ──
w("\n## 6. race_results / pdf_lap_times")
w("### race_results: session_type別 件数 / position範囲 (DA77/JA52)")
for r in q("""SELECT session_type, count(*) c, min(position) mn, max(position) mx,
   sum(CASE WHEN position IS NULL THEN 1 ELSE 0 END) nullp
   FROM race_results WHERE rider_num IN(52,77) GROUP BY session_type ORDER BY session_type"""):
    w(f"- {r['session_type']}: n={r['c']} pos[{r['mn']},{r['mx']}] null={r['nullp']}")
w("### position NULL の行 (DA77/JA52)")
for r in q("SELECT round,session_type,rider_num,best_lap FROM race_results WHERE rider_num IN(52,77) AND position IS NULL"):
    w(f"  - {r['round']}/{r['session_type']}/#{r['rider_num']} best={r['best_lap']}")
w("### pdf_lap_times: lap_time_s 異常 (<20 or >400)")
ab=q("SELECT count(*) c FROM pdf_lap_times WHERE lap_time_s IS NOT NULL AND (lap_time_s<20 OR lap_time_s>400)")[0]["c"]
w(f"- 異常lap_time_s: {ab}件")

# ── 7. setup 値 spot (Original由来の数値範囲) ──
w("\n## 7. setup 数値レンジ (runs, 物理的に妥当か)")
for col,lo,hi in [("f_spr_l",7,12),("f_spr_r",7,12),("r_spr",70,110),("f_comp",0,30),
                  ("f_reb",0,30),("r_comp",0,30),("r_reb",0,30),("ride_hgt",0,50),
                  ("track_temp",0,70),("air_temp",-5,45)]:
    vals=[x[col] for x in q(f"SELECT {col} FROM runs WHERE {col} IS NOT NULL")]
    nums=[]
    for v in vals:
        try: nums.append(float(str(v)))
        except: pass
    if nums:
        oob=[n for n in nums if n<lo or n>hi]
        w(f"- {col}: n={len(nums)} range[{min(nums)},{max(nums)}] 想定[{lo},{hi}] 範囲外{len(oob)}件"+(" ⚠" if oob else ""))

# ── 8. 異常候補Runのラップ明細 (2D best vs PDF best のΔ>1.5s) ──
w("\n## 8. 異常候補Runのラップ明細 (best_lap_s(2D) と PDF best のΔ>1.5s の run を精査用に展開)")
w("各runの全lap(lap_no, lap_time_s, is_outlap)を列挙。根因(stray/全outlap/外れ値)の判定材料。")
flagged=q("""SELECT p.run_id,p.rider,p.round,p.session,p.best_lap_s lap2d, rr.best_lap_s pdf,
   (SELECT mes_file FROM laps WHERE run_id=p.run_id LIMIT 1) mes
   FROM performance p JOIN race_results rr
     ON rr.round=p.round AND rr.session_type=p.session
    AND rr.rider_num=CASE p.rider WHEN 'JA52' THEN 52 WHEN 'DA77' THEN 77 END
   WHERE p.best_lap_s IS NOT NULL AND rr.best_lap_s IS NOT NULL
     AND abs(p.best_lap_s-rr.best_lap_s)>1.5
   ORDER BY abs(p.best_lap_s-rr.best_lap_s) DESC""")
for f in flagged:
    w(f"\n### {f['run_id']}  (2D best={f['lap2d']} / PDF best={f['pdf']} / mes={f['mes']})")
    laps=q("SELECT lap_no,lap_time_s,is_outlap FROM laps WHERE run_id=? ORDER BY lap_no",(f["run_id"],))
    w("  laps: "+", ".join(f"L{l['lap_no']}={l['lap_time_s']}{'(out)' if l['is_outlap'] else ''}" for l in laps))
if not flagged: w("- なし")

con.close()
OUT.write_text("\n".join(L), encoding="utf-8")
print(f"書込: {OUT}  ({len(L)} 行)")
print("\n".join(L[:60]))
