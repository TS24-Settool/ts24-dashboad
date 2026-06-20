#!/usr/bin/env python3
"""
import_all_race_results.py
全ラウンドのレース結果PDFからrace_resultsテーブルを正確なデータで再構築する。

処理対象:
  ROUND11 RACE1/RACE2 (Estoril, 2025)
  ROUND12 RACE1/RACE2 (Jerez, 2025)
  ROUND1  RACE1/RACE2 (Phillip Island, 2026)
  ROUND2  RACE1/RACE2 (Portimao, 2026)
  ROUND3  RACE1/RACE2 (Assen, 2026)
  ROUND4  RACE1/RACE2 (Balaton, 2026)

※ ROUND5 RACE1は既に正しいデータが入っているためスキップ
"""
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path('/sessions/eloquent-dazzling-bell/mnt/Data TS24 Claude')
SCRIPTS  = BASE_DIR / '05_SCRIPTS'
DB_PATH  = BASE_DIR / '02_DATABASE/ts24_unified.db'
sys.path.insert(0, str(SCRIPTS))
from parse_race_pdf import parse_race_pdf

# セッション定義: key → (round, circuit, session_type, date, pdf_path)
SESSIONS = [
    ('ROUND11', 'ESTORIL',       'RACE1', '2025-10-11', BASE_DIR/'07_RESULTS/ROUND11_ESTORIL_20251010/ROUND11_ESTORIL_RACE1.pdf'),
    ('ROUND11', 'ESTORIL',       'RACE2', '2025-10-12', BASE_DIR/'07_RESULTS/ROUND11_ESTORIL_20251010/ROUND11_ESTORIL_RACE2.pdf'),
    ('ROUND12', 'JEREZ',         'RACE1', '2025-10-18', BASE_DIR/'07_RESULTS/ROUND12_JEREZ_20251017/ROUND12_JEREZ_RACE1.pdf'),
    ('ROUND12', 'JEREZ',         'RACE2', '2025-10-19', BASE_DIR/'07_RESULTS/ROUND12_JEREZ_20251017/ROUND12_JEREZ_RACE2.pdf'),
    ('ROUND1',  'PHILLIP ISLAND','RACE1', '2026-02-21', BASE_DIR/'07_RESULTS/ROUND1_PHILLIPISLAND_20260220/ROUND1_PHILLIP_ISLAND_RACE1.pdf'),
    ('ROUND1',  'PHILLIP ISLAND','RACE2', '2026-02-22', BASE_DIR/'07_RESULTS/ROUND1_PHILLIPISLAND_20260220/ROUND1_PHILLIP_ISLAND_RACE2.pdf'),
    ('ROUND2',  'PORTIMAO',      'RACE1', '2026-03-28', BASE_DIR/'07_RESULTS/ROUND2_PORTIMAO_20260327/ROUND2_PORTIMAO_RACE1.pdf'),
    ('ROUND2',  'PORTIMAO',      'RACE2', '2026-03-29', BASE_DIR/'07_RESULTS/ROUND2_PORTIMAO_20260327/ROUND2_PORTIMAO_RACE2.pdf'),
    ('ROUND3',  'ASSEN',         'RACE1', '2026-04-18', BASE_DIR/'07_RESULTS/ROUND3_ASSEN_20260417/ROUND3_ASSEN_RACE1.pdf'),
    ('ROUND3',  'ASSEN',         'RACE2', '2026-04-19', BASE_DIR/'07_RESULTS/ROUND3_ASSEN_20260417/ROUND3_ASSEN_RACE2.pdf'),
    ('ROUND4',  'BALATON',       'RACE1', '2026-05-02', BASE_DIR/'07_RESULTS/ROUND4_BALATON_20260501/20260501-ROUND4-RACE1.pdf'),
    ('ROUND4',  'BALATON',       'RACE2', '2026-05-03', BASE_DIR/'07_RESULTS/ROUND4_BALATON_20260501/20260501-ROUND4-RACE2.pdf'),
]

def main():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    total_deleted = 0
    total_inserted = 0
    
    for rnd, circuit, sess, date, pdf_path in SESSIONS:
        pdf_name = Path(pdf_path).name
        print(f"\n{'='*55}")
        print(f"  {rnd} {sess} — {circuit} ({date})")
        print(f"  PDF: {pdf_name}")
        
        if not pdf_path.exists():
            print(f"  ⚠️  PDFが見つかりません: {pdf_path}")
            continue
        
        # 既存データを削除
        cur.execute("DELETE FROM race_results WHERE round=? AND session_type=?", (rnd, sess))
        deleted = cur.rowcount
        total_deleted += deleted
        print(f"  🗑  既存 {deleted} 行を削除")
        
        # PDFを解析
        try:
            riders, total_laps, winner_time = parse_race_pdf(pdf_path)
        except Exception as e:
            print(f"  ❌ PDF解析エラー: {e}")
            continue
        
        print(f"  📊 {len(riders)} 選手を検出 (全{total_laps}周, 優勝タイム={winner_time})")
        
        # DBに挿入
        inserted = 0
        for r in riders:
            # race_time: 優勝者は絶対タイム、その他はgap
            if r['pos'] == 1 and winner_time:
                race_time = winner_time
            else:
                race_time = f"+{r['gap']}" if r['gap'] else None
            
            cur.execute("""
                INSERT INTO race_results 
                  (round, circuit, session_type, date, position,
                   rider_num, rider_name, laps, race_time, gap,
                   best_lap, best_lap_s, source_file)
                VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,?)
            """, (
                rnd, circuit, sess, date, r['pos'],
                r['rider_num'], r['rider_name'], r['laps'],
                race_time, r['gap'],
                r['race_fl'], r['race_fl_s'],
                pdf_name,
            ))
            inserted += 1
        
        total_inserted += inserted
        
        # TS24ライダーの確認
        ja52 = next((r for r in riders if r['rider_num'] == 52), None)
        da77 = next((r for r in riders if r['rider_num'] == 77), None)
        
        if ja52:
            p = f"P{ja52['pos']}" if ja52['pos'] else 'RET'
            print(f"  ✅ JA52 (#52): {p}, FL={ja52['race_fl']}({ja52['race_fl_s']}s), gap={ja52['gap']}")
        else:
            print(f"  ⚠️  JA52 (#52) が見つかりません")
        
        if da77:
            p = f"P{da77['pos']}" if da77['pos'] else 'RET'
            print(f"  ✅  #77: {p}, FL={da77['race_fl']}({da77['race_fl_s']}s), gap={da77['gap']}, name={da77['rider_name']}")
        else:
            print(f"  ⚠️   #77 が見つかりません")
        
        print(f"  ✍️  {inserted} 行を挿入")
    
    conn.commit()
    conn.close()
    
    print(f"\n{'='*55}")
    print(f"  完了: 合計 {total_deleted} 行削除, {total_inserted} 行挿入")
    print(f"{'='*55}")

if __name__ == '__main__':
    main()
