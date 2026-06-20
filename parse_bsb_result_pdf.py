#!/usr/bin/env python3
"""
BSB タイミングPDF → race_results / pdf_lap_times テーブル インポート
====================================================================
対象: ZYN British Superbike Championship 公式タイミングPDF

フォルダ命名規則: YYYYMMDD-ROUNDx-RESULT-BSB/
  例: 20260502-ROUND1-RESULT-BSB/
      ├── FP1.pdf
      ├── Q1.pdf
      ├── WUP.pdf
      └── RACE2.pdf  (RACE1.pdf, RACE2.pdf, SPRINT.pdf)

使い方:
  python parse_bsb_result_pdf.py                        ← 全BSBフォルダを自動処理
  python parse_bsb_result_pdf.py 20260502-ROUND1-RESULT-BSB/  ← 特定フォルダ
"""

import re
import sys
import math
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    import pdfplumber
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pdfplumber", "-q"])
    import pdfplumber

SCRIPT_DIR = Path(__file__).parent
DB_DIR     = SCRIPT_DIR.parent / "02_DATABASE"
BASE_DIR   = SCRIPT_DIR.parent   # Data TS24 Claude フォルダ
DB_PATH    = DB_DIR / "ts24_unified.db"
DATA_SCOPE = "COMPANY"

# ── 時間変換 ──────────────────────────────────────────
_BSB_LAP  = re.compile(r'(?<!\d)(\d):(\d{2})\.(\d{3})')    # "1:36.674" (lookbehind: 2桁タイムの部分マッチを防ぐ)
_BSB_RACE = re.compile(r'(\d+):(\d{2})\.(\d{3})')              # "26:00.546"

def lap_to_s(t):
    m = _BSB_LAP.search(str(t or ''))
    if m:
        return round(int(m.group(1))*60 + int(m.group(2)) + int(m.group(3))/1000, 3)
    return None

def race_time_to_s(t):
    m = _BSB_RACE.search(str(t or ''))
    if m:
        return round(int(m.group(1))*60 + int(m.group(2)) + int(m.group(3))/1000, 3)
    return None

def _f(v):
    try:
        x = float(str(v).strip())
        return None if math.isnan(x) else x
    except:
        return None

def _i(v):
    try: return int(float(str(v)))
    except: return None

# ── フォルダ名からメタ情報を取得 ─────────────────────
def meta_from_folder(folder: Path):
    """
    "20260502-ROUND1-RESULT-BSB" → (date, round, circuit)
    circuit は DB内の COMPANY セッションデータから補完
    """
    parts = folder.name.split('-')
    date_str  = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}" if len(parts)>0 else ""
    round_val = parts[1].upper() if len(parts)>1 else "UNK"

    # circuit: SQLite の ts24_sessions COMPANY データから推定
    circuit = _lookup_circuit(round_val)
    return date_str, round_val, circuit

def _lookup_circuit(round_val):
    """DBのCOMPANY sessionsからROUNDに対応するCIRCUITを取得"""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT circuit FROM ts24_sessions WHERE round=? AND data_scope='COMPANY' LIMIT 1",
            (round_val,)
        ).fetchone()
        conn.close()
        if row:
            return row[0]
    except:
        pass
    return "UNK"

# ── セッションタイプ判定 ──────────────────────────────
SESSION_MAP = {
    'FP1': 'FP1', 'FP2': 'FP2',  # 結果DBでは別セッションとして保持
    'Q1': 'QP', 'Q2': 'QP', 'QUALIFYING': 'QP',
    'WUP': 'WUP', 'WARMUP': 'WUP',
    'RACE1': 'RACE1', 'RACE2': 'RACE2',
    'RACE': 'RACE', 'SPRINT': 'SPRINT',
}

def session_type_from_filename(fname):
    stem = Path(fname).stem.upper()  # "FP1", "RACE2", etc.
    return SESSION_MAP.get(stem, stem)

def is_race_session(session_type):
    return session_type in ('RACE', 'RACE1', 'RACE2', 'SPRINT')

# ── BSB PDF パーサー ────────────────────────────────
# 3文字国コード (NAT判定用)
_NAT = re.compile(r'\b([A-Z]{3})\b')
_COUNTRY_CODES = {
    'GBR','IRL','AUS','ITA','FRA','ESP','GER','NED','BEL','POR','SWE','FIN','NOR','DEN',
    'USA','CAN','RSA','JPN','CHN','NZL','SUI','AUT','CZE','SVK','HUN','POL','TUR','GRE',
}

def _extract_words_by_row(pdf_path, word_y_tol=3, row_gap=7):
    """
    スキャンライン法でPDF wordsを行ごとにクラスタリング。
    同一行の単語top値は最大~2px変動するため、固定バケット法より堅牢。
    row_gap: この値より大きいtop差を「別行」と判断 (行間隔~10px なので 7 が適切)
    """
    with pdfplumber.open(pdf_path) as pdf:
        words = pdf.pages[0].extract_words(x_tolerance=3, y_tolerance=word_y_tol)
    if not words:
        return []
    words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))
    clusters = []
    cur = []
    cur_max = None
    for w in words_sorted:
        t = w['top']
        if cur_max is None or t - cur_max > row_gap:
            if cur:
                clusters.append(cur)
            cur = [w]
            cur_max = t
        else:
            cur.append(w)
            cur_max = max(cur_max, t)
    if cur:
        clusters.append(cur)
    return [
        {'y': min(w['top'] for w in c),
         'text': ' '.join(w['text'] for w in sorted(c, key=lambda x: x['x0']))}
        for c in clusters
    ]

def _split_camel(name):
    """
    "DeanHARRISON" → "Dean HARRISON"
    (RACE PDFでは名前が結合されることがある)
    """
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    return result

# サーキット名正規化マップ (PDF内テキスト → DB格納名)
_CIRCUIT_FROM_PDF = [
    (re.compile(r'Oulton Park', re.I),        'OULTONPARK'),
    (re.compile(r'Donington Park', re.I),     'DONINGTON'),
    (re.compile(r'Thruxton', re.I),           'THRUXTON'),
    (re.compile(r'Knockhill', re.I),          'KNOCKHILL'),
    (re.compile(r'Snetterton', re.I),         'SNETTERTON'),
    (re.compile(r'Brands Hatch', re.I),       'BRANDS HATCH'),
    (re.compile(r'Cadwell Park', re.I),       'CADWELL PARK'),
    (re.compile(r'Silverstone', re.I),        'SILVERSTONE'),
    (re.compile(r'Phillip Island', re.I),     'PHILLIP ISLAND'),
]

def _circuit_from_pdf(rows):
    """PDF行テキストからサーキット名を自動検出"""
    for row in rows:
        for pat, name in _CIRCUIT_FROM_PDF:
            if pat.search(row['text']):
                return name
    return None

_HAS_LAPTIME = re.compile(r'(?<!\d)\d:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3}')

def _merge_split_rows(rows):
    """
    PDF抽出時に分割された行をマージ。
    条件: データ行 (^\d+\s で始まる) がラップタイムなし、
          かつ直後の行がラップタイムを含む場合にマージ。
    例:
      "7 55 7 Dean HARRISON GBR Honda..."  (タイムなし)
      "1:31.554 16 16 0.755..."            (タイムあり)
      → "7 55 7 Dean HARRISON GBR Honda... 1:31.554 16 16 0.755..."
    "10" や "25" など単独数字行 (スペースなし) はスキップ対象外。
    """
    merged = []
    i = 0
    while i < len(rows):
        text = rows[i]['text'].strip()
        if (re.match(r'^\d+\s', text)
                and not _HAS_LAPTIME.search(text)
                and i + 1 < len(rows)):
            next_text = rows[i + 1]['text'].strip()
            if _HAS_LAPTIME.search(next_text):
                merged.append({'y': rows[i]['y'], 'text': text + ' ' + next_text})
                i += 2
                continue
        merged.append(rows[i])
        i += 1
    return merged

def parse_bsb_pdf(pdf_path, session_type, round_val, circuit, date_str):
    """
    BSB タイミングPDF 1枚をパースして race_results リストを返す。

    返り値: [dict, ...]  (race_results テーブル互換)
    """
    raw_rows = _extract_words_by_row(str(pdf_path))
    # サーキットが不明な場合、PDFから自動検出
    if circuit == 'UNK':
        detected = _circuit_from_pdf(raw_rows)
        if detected:
            circuit = detected
    rows = _merge_split_rows(raw_rows)
    results = []
    is_race = is_race_session(session_type)

    for row in rows:
        text = row['text'].strip()

        # データ行の判定: 先頭が数字 (POS)
        if not re.match(r'^\d+\s', text):
            continue

        tokens = text.split()
        if len(tokens) < 6:
            continue

        try:
            pos = int(tokens[0])
        except ValueError:
            continue

        try:
            rider_num = int(tokens[1])
        except ValueError:
            # "81*CUP" のような特殊記法 (ペナルティフラグ) に対応
            m_num = re.match(r'^(\d+)', tokens[1])
            if m_num:
                rider_num = int(m_num.group(1))
                # "81*CUP" → tokens を ["81", "CUP", ...] に正規化
                suffix = tokens[1][m_num.end():]
                extra = re.sub(r'[^A-Z0-9]', '', suffix.upper())
                tokens = [tokens[0], str(rider_num)] + ([extra] if extra else []) + tokens[2:]
            else:
                continue

        # エッジケース: マージ後に "POS CL NO NAME..." になる場合
        # (PDFで POS/CL が先行する行に分離→マージ時 tokens[1]=CL=pos値)
        # rider_num == pos かつ tokens[2] が別の整数なら tokens[2] が実際の NO
        if rider_num == pos and len(tokens) > 2:
            try:
                alt_num = int(tokens[2])
                if alt_num != pos:
                    rider_num = alt_num
            except (ValueError, IndexError):
                pass

        if is_race:
            # RACE形式: POS NO [CL] [CUP [PIC]] NAME(merged) NAT ENTRY LAPS TIME...
            # CL は整数 (上位は省略), CUPクラスは "CUP" テキスト
            if len(tokens) < 4:
                continue
            name_idx = 2
            # CL (整数) をスキップ
            try:
                int(tokens[name_idx])
                name_idx += 1
            except (ValueError, IndexError):
                pass
            # CUP テキストと PIC番号をスキップ
            if name_idx < len(tokens) and tokens[name_idx] == 'CUP':
                name_idx += 1
                if name_idx < len(tokens):
                    try:
                        int(tokens[name_idx])
                        name_idx += 1
                    except (ValueError, IndexError):
                        pass
            if name_idx >= len(tokens):
                continue
            raw_name = tokens[name_idx]
            rider_name = _split_camel(raw_name)   # "BillyMcCONNELL" → "Billy Mc CONNELL"
            idx = name_idx + 1  # NAT follows name
        else:
            # FP/QP/WUP形式: POS NO [CL] [CUP PIC] NAME NAT ENTRY TIME ON LAPS GAP DIFF MPH
            # CL列は整数 (通常は順位と同じ), CUPクラスは"CUP"テキスト+PIC番号
            # 行によってはCLが別行に分離されてtoken[2]が名前になることもある
            nat_idx = None
            for j in range(2, min(2+8, len(tokens))):
                if tokens[j] in _COUNTRY_CODES:
                    nat_idx = j
                    break
            if nat_idx is None:
                continue
            # 名前の開始位置: 先頭の数字トークンとCUPトークンをスキップ
            name_start = 2
            while name_start < nat_idx:
                v = tokens[name_start]
                try:
                    int(float(v))  # 数値 (CL or PIC) → スキップ
                    name_start += 1
                except (ValueError, TypeError):
                    if v == 'CUP':  # CUPクラス表記 → スキップ
                        name_start += 1
                    else:
                        break
            # CUPトークンと数字を名前から除外 (マージ行でCUPが末尾に混入するケース対応)
            name_tokens = [t for t in tokens[name_start:nat_idx]
                           if t != 'CUP' and not re.match(r'^\d+$', t)]
            rider_name = ' '.join(name_tokens)
            idx = nat_idx

        # NAT
        nat = tokens[idx] if idx < len(tokens) and tokens[idx] in _COUNTRY_CODES else ""
        idx += 1

        # ENTRY (team/bike): 数字が来るまでの残りトークンをチェック
        # 残りからタイム・数値パターンを探す
        lap_times_found = []
        gap_val = None
        total_laps = None
        race_time_str = None
        best_lap_str = None
        grid_pos = None

        remaining = tokens[idx:]
        remaining_text = ' '.join(remaining)

        if is_race:
            # RACE: [ENTRY] LAPS TIME [GAP [DIFF]] MPH BEST ON GRD ↑↓
            # MPH (85-115の浮動小数) を軸にBEFORE/AFTER に分割して構造的に解析
            #
            # P1(トップ):  TIME MPH BEST ON GRD  (GAP/DIFFなし)
            # P2+(小差):   TIME GAP DIFF MPH BEST ON GRD (GAP=秒数float)
            # P2+(大差):   TIME GAP DIFF MPH BEST ON GRD (GAP=M:SS.mmm形式)

            # LAPS: 最初の短い整数
            nums = re.findall(r'[\d:\.]+', remaining_text)
            for n in nums:
                if re.match(r'^\d{1,2}$', n):
                    total_laps = int(n)
                    break

            # TIME (総合タイム): 最初の MM+:SS.mmm
            race_t = re.search(r'\d{2,}:\d{2}\.\d{3}', remaining_text)
            if race_t:
                race_time_str = race_t.group()

            # MPH の位置を特定 (85-115の浮動小数)
            mph_end = -1
            mph_start = -1
            for m in re.finditer(r'(?<!\d)(\d{2,3}\.\d{1,2})(?!\d)', remaining_text):
                try:
                    v = float(m.group())
                    if 85.0 <= v <= 115.0:
                        mph_start = m.start()
                        mph_end = m.end()
                        break
                except ValueError:
                    pass

            # BEST LAP: MPH 以降の最初の M:SS.mmm
            if mph_end >= 0:
                after_mph = remaining_text[mph_end:]
                bl_m = _BSB_LAP.search(after_mph)
                if bl_m:
                    best_lap_str = f"{bl_m.group(1)}:{bl_m.group(2)}.{bl_m.group(3)}"
            # MPH が見つからない場合は最後の M:SS.mmm を使用
            if best_lap_str is None:
                best_laps = _BSB_LAP.findall(remaining_text)
                if best_laps:
                    m1, m2, m3 = best_laps[-1]
                    best_lap_str = f"{m1}:{m2}.{m3}"

            # GAP: TIME と MPH の間に存在
            if race_t and mph_start >= 0:
                between = remaining_text[race_t.end():mph_start]
                # まず M:SS.mmm 形式の大ギャップを確認
                large_gap_m = _BSB_LAP.search(between)
                if large_gap_m:
                    gap_val = lap_to_s(f"{large_gap_m.group(1)}:{large_gap_m.group(2)}.{large_gap_m.group(3)}")
                else:
                    # 小さい float (秒数) を探す
                    gap_floats = re.findall(r'(?<!\d)(\d+\.\d+)(?!\d)', between)
                    for g in gap_floats:
                        gv = float(g)
                        if 0.001 < gv < 200:
                            gap_val = gv
                            break
        else:
            # FP/QP/WUP: TIME ON LAPS GAP DIFF MPH
            lap_matches = _BSB_LAP.findall(remaining_text)
            if lap_matches:
                m1, m2, m3 = lap_matches[0]
                best_lap_str = f"{m1}:{m2}.{m3}"
            # LAPS: 2桁整数
            lap_nums = re.findall(r'\b(\d{1,3})\b', remaining_text)
            # ONとLAPSの2つが並ぶ → 後ろがLAPS
            if len(lap_nums) >= 2:
                try:
                    total_laps = int(lap_nums[1])
                except:
                    pass
            # GAP: ラップタイムパターンを除外してから検索
            gap_text = re.sub(r'\d:\d{2}\.\d{3}', '', remaining_text)
            gaps = re.findall(r'(\d+\.\d{3})', gap_text)
            for g in gaps:
                gv = float(g)
                if 0 < gv < 60:   # BSBセッションギャップは通常60秒以内
                    gap_val = gv
                    break

        best_lap_s = lap_to_s(best_lap_str)

        results.append({
            'round':        round_val,
            'circuit':      circuit,
            'session_type': session_type,
            'date':         date_str,
            'position':     pos,
            'rider_num':    rider_num,
            'rider_name':   rider_name,
            'laps':         total_laps,
            'race_time':    race_time_str,
            'gap':          gap_val,
            'best_lap_s':   best_lap_s,
            'grid_pos':     grid_pos,
            'data_scope':   DATA_SCOPE,
        })

    return results


def import_bsb_result_folder(folder: Path):
    """BSBリザルトフォルダ1件をDBにインポート"""
    folder = Path(folder)
    print(f"\n{'='*60}")
    print(f"インポート: {folder.name}")
    print(f"{'='*60}")

    date_str, round_val, circuit = meta_from_folder(folder)
    print(f"  DATE: {date_str}  ROUND: {round_val}  CIRCUIT: {circuit}")

    if circuit == "UNK":
        print(f"  [WARN] CIRCUITが不明。先にimport_company_bsb.pyでエンジニアレポートをインポートしてください。")

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"  [WARN] PDFファイルが見つかりません")
        return False

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_inserted = 0
    total_skipped = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for pdf_path in pdfs:
        session_type = session_type_from_filename(pdf_path.name)
        print(f"\n  [{pdf_path.name}] → session={session_type}")

        try:
            results = parse_bsb_pdf(pdf_path, session_type, round_val, circuit, date_str)
        except Exception as e:
            print(f"    [ERROR] パース失敗: {e}")
            continue

        print(f"    {len(results)} エントリを読み取り")

        # DH55 (rider_num=55) のデータを最初に表示
        dh55 = [r for r in results if r['rider_num'] == 55]
        for r in dh55:
            print(f"    → DH55: P{r['position']} | BestLap={r['best_lap_s']}s | Gap={r['gap']} | Laps={r['laps']}")

        # DB重複チェック & 挿入
        inserted = 0
        skipped = 0
        for r in results:
            # 重複チェック: round + circuit + session_type + rider_num
            existing = cur.execute("""
                SELECT result_id FROM race_results
                WHERE round=? AND circuit=? AND session_type=? AND rider_num=? AND data_scope='COMPANY'
            """, (r['round'], r['circuit'], r['session_type'], r['rider_num'])).fetchone()

            if existing:
                skipped += 1
                continue

            gap_str = str(r['gap']) if r['gap'] is not None else None
            cur.execute("""
                INSERT INTO race_results
                (round, circuit, session_type, date, position, rider_num, rider_name,
                 laps, gap, best_lap_s, data_scope, imported_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r['round'], r['circuit'], r['session_type'], r['date'],
                r['position'], r['rider_num'], r['rider_name'],
                r['laps'], gap_str, r['best_lap_s'],
                DATA_SCOPE, now,
            ))
            inserted += 1

        print(f"    DB: {inserted}件挿入, {skipped}件スキップ")
        total_inserted += inserted
        total_skipped += skipped

    conn.commit()
    conn.close()
    print(f"\n  ✓ 完了: 合計 {total_inserted}件挿入, {total_skipped}件スキップ")
    return True


def main():
    if len(sys.argv) >= 2:
        target = Path(sys.argv[1])
        if not target.is_absolute():
            for base in [Path.cwd(), BASE_DIR]:
                if (base / target).exists():
                    target = base / target
                    break
        if not target.exists():
            print(f"[ERROR] フォルダが見つかりません: {sys.argv[1]}")
            sys.exit(1)
        import_bsb_result_folder(target)
    else:
        # BASE_DIR直下の *-RESULT-BSB フォルダを全て自動処理
        folders = sorted(BASE_DIR.glob("*-RESULT-BSB"))
        if not folders:
            print(f"[INFO] {BASE_DIR} に *-RESULT-BSB フォルダが見つかりません。")
            sys.exit(0)
        print(f"[INFO] {len(folders)} フォルダを処理します。")
        for f in folders:
            import_bsb_result_folder(f)

    print("\n完了!")


if __name__ == "__main__":
    main()
