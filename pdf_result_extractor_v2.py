#!/usr/bin/env python3
"""
pdf_result_extractor_v2.py — WorldSSP 公式リザルト PDF 抽出（PyMuPDF・堅牢版）
=============================================================================
旧 pdf_result_extractor.py / pdf_chrono_extractor.py は pdfplumber の
**ページ単位** 処理（page.extract_tables() / _extract_chronological_page(page)）
だったため、ラップタイム表（Chronological Analysis）が複数ページにまたがると
継続ページ側のラップを取りこぼしていた。継続ページにはライダーヘッダーが
無いため、ページごとに状態（in_section）がリセットされ、ラップ行が捨てられる。

v2 の方針:
  1. **全ページのテキストを読み順で連結** してから解析する
     （ページ境界をまたぐライダー区間・ラップ列を取りこぼさない）。
  2. ページの繰り返しヘッダー/フッター（"Chronological Analysis ...",
     "TT Circuit ...", "P = Pits In/Out ...", copyright 等）を除去してから連結。
  3. 公式 Results 分類（順位・ゼッケン・名前・ベストラップ）と、
     Chronological Analysis のラップ毎タイムの両方に対応。
  4. 正規表現で行を頑健にパース。Chronological のライダーヘッダー
     "77 D. AEGERTER (1'37.350)" + "6°" を権威源として順位・ベストを取る
     （Results ページはレイアウトが PDF 生成系で大きく異なるため、
      ラップ表が存在する場合は Chronological を優先する）。

対象ライダー: DA77（#77）・JA52（#52）。--all-riders で全員。

使用方法:
  python3 pdf_result_extractor_v2.py --file FILE.pdf [--dry-run]
  python3 pdf_result_extractor_v2.py --dir  DIR/     [--dry-run]
  python3 pdf_result_extractor_v2.py --all           [--dry-run]
  python3 pdf_result_extractor_v2.py --file FILE.pdf --all-riders
  python3 pdf_result_extractor_v2.py --file FILE.pdf --laps          # ラップ明細も出力
  python3 pdf_result_extractor_v2.py --file FILE.pdf --db /tmp/x.db  # 書込先DB指定

依存: PyMuPDF (import fitz)
注意: 既定では DB へ書き込まない（--write 指定時のみ書込）。検証時は --dry-run
      もしくは --db /tmp/pdf_test.db を使い、本番 DB を汚さないこと。
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT = SCRIPT_DIR.parent
RESULTS_ROOT = DATA_ROOT / "07_RESULTS"
DEFAULT_DB = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"

TARGET_RIDERS = {77, 52}

# 抽出器バージョン（staging の来歴列 extractor_version に記録）
EXTRACTOR_VERSION = "pdf_result_extractor_v2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PDFv2] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── 時刻文字列 → 秒 ─────────────────────────────────────────────────────────

def parse_time_s(val: str | None) -> float | None:
    """ 1'37.350 / 1:37.350 / 37.350 → 秒(float) """
    if not val:
        return None
    s = str(val).strip().strip("CP* ")
    m = re.match(r"(\d+)[:'](\d{1,2})[.,](\d+)", s)
    if m:
        return round(int(m.group(1)) * 60 + int(m.group(2)) + float("0." + m.group(3)), 3)
    try:
        return round(float(s.replace(",", ".")), 3)
    except Exception:
        return None


# ── ファイル名 / 本文からメタ情報を推定 ─────────────────────────────────────

_CIRCUITS = [
    "PHILLIP_ISLAND", "PHILLIP ISLAND", "ASSEN", "JEREZ", "PORTIMAO",
    "PORTIMÃO", "CREMONA", "MISANO", "MAGNY", "ESTORIL", "DONINGTON",
    "MOST", "BARCELONA", "SAN_JUAN", "ARAGON", "BALATON", "BALATON_PARK",
]

_SESSION_PATTERNS = [
    ("RACE2", r"RACE\s*2|RACE2"),
    ("RACE1", r"RACE\s*1|RACE1"),
    ("SP", r"SUPERPOLE|TISSOT\s+SUPERPOLE|\bSP\b"),
    ("QP", r"\bQP\b|QUALIF"),
    ("WUP2", r"WARM\s*UP\s*2|WUP2"),
    ("WUP1", r"WARM\s*UP\s*1|WUP1|WARM\s*UP"),
    ("FP2", r"\bFP2\b|FREE\s+PRACTICE\s*2"),
    ("FP1", r"\bFP1\b|FREE\s+PRACTICE\s*1"),
    ("FP", r"\bFP\b|FREE\s+PRACTICE"),
    ("RACE", r"\bRACE\b"),
]


def _meta_from_filename(pdf_path: Path) -> dict:
    name = pdf_path.stem.upper()
    parent = pdf_path.parent.name.upper()
    blob = f"{parent} {name}"
    meta: dict = {"round": None, "circuit": None, "session_type": None, "date": None}

    m = re.search(r"(\d{8})", blob)
    if m:
        d = m.group(1)
        meta["date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    flat = blob.replace("_", "").replace(" ", "")
    for c in _CIRCUITS:
        if c.replace("_", "").replace(" ", "") in flat:
            meta["circuit"] = c.replace("_", " ")
            break

    for stype, pat in _SESSION_PATTERNS:
        if re.search(pat, blob):
            meta["session_type"] = stype
            break

    m2 = re.search(r"ROUND\s*(\d+)", blob)
    if m2:
        meta["round"] = f"ROUND{int(m2.group(1))}"

    return meta


def _meta_from_text(full_text: str, meta: dict) -> dict:
    """ ファイル名で取れなかった項目を本文から補完する。 """
    head = full_text[:2500]

    if not meta.get("circuit"):
        m = re.search(
            r"(Phillip Island|Balaton Park|Portim[aã]o|Assen|Aragon|Jerez|"
            r"Estoril|Most|Cremona|Misano|Donington)", head, re.I)
        if m:
            meta["circuit"] = m.group(1).upper().replace("PORTIMÃO", "PORTIMAO")
        else:
            m = re.search(r"([A-Z][\w ]+?)\s+\d[.,]\d{3}\s*m", head)
            if m:
                meta["circuit"] = re.sub(r"\bCircuit\b", "", m.group(1), flags=re.I).strip().upper()

    if not meta.get("round"):
        m = re.search(r"Round\s*(\d+)|ROUND\s*(\d+)", head, re.I)
        if m:
            meta["round"] = f"ROUND{int(m.group(1) or m.group(2))}"

    if not meta.get("session_type"):
        for stype, pat in _SESSION_PATTERNS:
            if re.search(pat, head, re.I):
                meta["session_type"] = stype
                break

    if not meta.get("date"):
        m = re.search(r"(\d{2}/\d{2}/\d{4})", head)
        if m:
            try:
                meta["date"] = datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                pass

    return meta


# ── ページ連結（ヘッダー/フッターのボイラープレートを除去） ───────────────────

# 各ページに必ず現れる定型行（除去対象）。これを消してから連結することで
# あるライダーのラップ区間が次ページ先頭に続く場合でも 1 本のストリームになる。
_BOILERPLATE = re.compile(
    r"^(WorldSSP|"
    # 各ラウンドの見出し行（"Pirelli Dutch Round, 17-19 April 2026" /
    # "Czech Round, 15-17 May 2026" 等）。生成系によりラップ表の途中に
    # ページヘッダーとして再出現するため、必ず除去する（区間を分断させない）。
    r".*Round,\s*\d.*\d{4}.*|"
    r"\d+\s*/\s*\d+|\d{3}/\d{2}|4\.\d+|2\.\d+|3\.\d+|"
    r"Chronological Analysis.*|Best Laps.*|Best Sectors.*|Lap Chart.*|"
    r"Results .*|Riders Standings.*|Manufacturers Standing.*|Teams Standings.*|"
    r"Start at .*|P = Pits In/Out.*|"
    r"These data/results cannot.*|now known or herein.*|the public within.*|"
    r"© DORNA.*|\d{2}/\d{2}/\d{4})\s*$"
)
# サーキット見出し（"TT Circuit Assen 4.542 m" / "Jerez 4.423 m" / "Balaton Park Circuit 4.075 m"）
_CIRCUIT_HEAD = re.compile(r".*\d[.,]\d{3}\s*m\s*$")
# Chronological の列見出し（Lap / Seg / km/h / Local Time）
_COLHEAD = re.compile(r"^(Lap|Seg\.\d.*|km/h|Local Time|Lap Time)\s*$")


def concat_pages(doc: fitz.Document) -> list[str]:
    """ 全ページを読み順で連結し、ボイラープレート除去した行リストを返す。 """
    out: list[str] = []
    for pg in doc:
        for raw in pg.get_text().split("\n"):
            line = raw.rstrip()
            if not line.strip():
                continue
            if _BOILERPLATE.match(line.strip()):
                continue
            if _CIRCUIT_HEAD.match(line.strip()) and re.search(r"\d[.,]\d{3}\s*m", line):
                continue
            out.append(line)
    return out


# ── Chronological Analysis 解析（複数ページ連結後） ─────────────────────────

# ライダーヘッダー: "77 D. AEGERTER (1'37.350)"
_RIDER_HDR = re.compile(
    r"^(\d{1,3})\s+([A-Z]\.\s*[A-Z][\w'’\-]+(?:\s+[\w'’\-]+)*)\s+\((\d+'\d{2}\.\d{3})\)\s*$"
)
# 順位: "6°"
_POSDEG = re.compile(r"^(\d{1,2})°\s*$")
# リタイア等のステータス（順位の代わりに現れる）
_STATUS = re.compile(r"^(RET|DNS|DNF|DSQ|NC)\s*$")
# ラップ番号（行頭の小さな整数のみ）
_LAPNO = re.compile(r"^\s*(\d{1,2})\s*$")
# ラップタイムを含むセグメント行: "      31.655     1'43.208"
# 行は分秒形式 m'ss.mmm で終わるが、ローカルタイム "14:02'15.506" のように
# 先頭に HH: が付くものは除外する（ローカルタイムを誤ってラップタイムにしない）。
_LAPTIME_INLINE = re.compile(r"^(?!\s*\d{1,2}:)(?:.*\s)?(\d{1,2}'\d{2}\.\d{3})\s*[CP]*\s*$")
_SEG = re.compile(r"^\s*\d{1,2}\.\d{3}\s*[CP]*\s*$")
_SPEED = re.compile(r"^\s*\d{3},\d\s*$")
# 値取り出し用（pdf_lap_times 互換列の抽出に使用）:
#   _SEG_VAL    … 単独セグメント行 "      27.502"
#   _COMBINED_SEG … セグメント + ラップタイムが同一行 "      22.316     1'37.997"
#   _SPEED_VAL  … 速度行 "254,1"（European 小数点 → 254.1）
_SEG_VAL = re.compile(r"^\s*(\d{1,2}\.\d{3})\s*[CP]*\s*$")
_COMBINED_SEG = re.compile(r"^\s*(\d{1,2}\.\d{3})\s+\d{1,2}'\d{2}\.\d{3}\s*[CP]*\s*$")
_SPEED_VAL = re.compile(r"^\s*(\d{3},\d)\s*$")
# 速度が行頭にあり後続にローカルタイム等が続くレイアウト（MISANO 系: "240,0 14:04'03.535"）
_SPEED_LEAD = re.compile(r"^\s*(\d{3},\d)\s+")
# 「速度 + ローカルタイム」が同一行 = MISANO 系レイアウトの確実な指標（PDF 単位で判定）。
# この系はセグメント読み順がラップ間で不安定なため seg1..seg4 を写像しない。
_SPEED_LOCALTIME = re.compile(r"^\s*\d{3},\d\s+\d{1,2}:\d{2}'\d{2}\.\d{3}\s*$")


def _map_segments(raw_segs: list[float], lap_time_s: float | None,
                  tol: float = 0.05) -> tuple:
    """
    Chronological のセグメント値（PyMuPDF 読み順）を pdf_lap_times の
    seg1..seg4 へ写像する。

    2D/Dorna 公式リザルトの Chronological レイアウトでは、1ラップの
    セグメント値が読み順 [r0, r1(=ラップタイムと同一行), r2, r3] で並び、
    実測較正（ASSEN/BALATON/JEREZ の pdf_lap_times と全一致）により
      seg1 = r2, seg2 = r3, seg3 = r0, seg4 = r1
    が確定している。

    **品質保全のため、4 セグメント揃い、かつ sum(segs) ≈ lap_time_s
    （許容 tol 秒）を満たすラップのみ写像する。** それ以外（スタート
    ラップ等でセグメントが 3 個しか無い／合計が合わない）は推測せず
    (None, None, None, None) を返す（捏造・誤割当を防ぐ）。
    """
    if (len(raw_segs) == 4 and lap_time_s is not None
            and abs(sum(raw_segs) - lap_time_s) <= tol):
        return (raw_segs[2], raw_segs[3], raw_segs[0], raw_segs[1])
    return (None, None, None, None)
# ローカルタイム "14:02'15.506" — HH:MM'SS.mmm（時刻）。
# 生成系により速度と同一行になる場合がある（"275,5 14:02'52.539"）ため、
# 行末がローカルタイムであれば一致させる（行頭限定にしない）。
_LOCALTIME = re.compile(r"(?:^|\s)\d{1,2}:\d{2}'\d{2}\.\d{3}\s*$")
_RACETIME = re.compile(r"^Race Time\b")
# Chronological 区間の終端センチネル（後続の集計表に入ったら閉じる）。
# WUP/FP など Race Time 行が無いセッションで、最後のライダー区間が
# "Best Laps & Speed" 表へ流れ込むのを防ぐ。
_SECTION_END = re.compile(
    r"^(Rider|Nat|No\.|Bike|Best Lap|SPD|Best Laps.*|Best Sectors.*|"
    r"Weather Report.*|Records|Pole \(SP\).*|"
    r"TOTAL LEADER LAPS|LAP LEADERS|Lap Chart.*)\s*$"
)


def parse_chronological(lines: list[str], all_riders: bool,
                        seg_trust: bool = True) -> dict[int, dict]:
    """
    連結済み行リストから Chronological Analysis を解析。
    返り値: {rider_num: {position, rider_num, rider_name, best_lap, best_lap_s,
                         laps: [ {lap_no, lap_time, lap_time_s, is_cancelled, ...} ]}}
    複数ページにまたがる同一ライダーのラップ列も、連結ストリーム上では
    途切れず連続するため、次のライダーヘッダーが来るまで全ラップを収集する。

    seg_trust=False のとき seg1..seg4 は写像せず NULL のままにする
    （MISANO 系レイアウト＝セグメント読み順が不安定で位置→sector が保証できない）。
    lap_no/lap_time/lap_time_s/is_cancelled/is_pit/speed/local_time は両系で取得する。
    """
    riders: dict[int, dict] = {}
    i = 0
    n = len(lines)
    cur: dict | None = None

    while i < n:
        line = lines[i].strip()

        hm = _RIDER_HDR.match(line)
        if hm:
            num = int(hm.group(1))
            # 直後（または近傍）に "N°"（順位）または "RET" 等（ステータス）が来る
            pos = None
            status = None
            for j in range(i + 1, min(i + 3, n)):
                pm = _POSDEG.match(lines[j].strip())
                if pm:
                    pos = int(pm.group(1))
                    break
                sm = _STATUS.match(lines[j].strip())
                if sm:
                    status = sm.group(1)
                    break
            best = hm.group(3)
            cur = {
                "position": pos,
                "status": status,
                "rider_num": num,
                "rider_name": hm.group(2).strip(),
                "best_lap": best,
                "best_lap_s": parse_time_s(best),
                "laps": [],
            }
            if all_riders or num in TARGET_RIDERS:
                riders[num] = cur
            else:
                cur = None  # 対象外ライダーの区間はラップ収集しない
            i += 1
            continue

        if cur is not None:
            # ライダー区間の終端センチネル: chrono の後に続く集計表
            # （"Best Laps & Speed" 等）に入ったら区間を閉じる。
            # それらは "Rider"/"Nat"/"Best Lap" 等のワード行や Round 見出しで始まる。
            if _SECTION_END.match(line):
                cur = None
                i += 1
                continue

            # ラップ番号行を起点に、その先のセグメント群からラップタイムを拾う
            lm = _LAPNO.match(lines[i])
            if lm:
                lap_no = int(lm.group(1))
                lap_time = None
                cancelled = False
                pit = False
                local_time_seen = False
                local_time = None
                speed = None
                raw_segs: list[float] = []  # PyMuPDF 読み順のセグメント値
                # ラップブロックは「ラップ番号 → セグメント群（うち1行にラップタイム）
                # → 速度 → ローカルタイム」で構成され、必ずローカルタイムで終わる。
                # ローカルタイムで閉じないブロックは集計表のノイズ → 不採用。
                # ローカルタイム "14:02'15.506" は _LAPTIME_INLINE の lookahead で除外。
                k = i + 1
                while k < n:
                    raw = lines[k]
                    s = raw.strip()
                    if _RIDER_HDR.match(s) or _RACETIME.match(s) or _SECTION_END.match(s):
                        break
                    lt_m = _LOCALTIME.search(s)
                    if lt_m:
                        local_time_seen = True
                        ltt = re.search(r"\d{1,2}:\d{2}'\d{2}\.\d{3}", s)
                        local_time = ltt.group(0) if ltt else lt_m.group(0).strip()
                        # MISANO 系: ローカルタイム行の先頭に「C(取消)/P(ピット)」フラグと速度が付く
                        # 例 "C 231,8 14:30'54.853" / "240,0 14:04'03.535"。
                        head = s[:ltt.start()] if ltt else ""
                        if "C" in head:
                            cancelled = True
                        if "P" in head:
                            pit = True
                        if speed is None:
                            sm = re.search(r"(\d{3},\d)", head)
                            if sm:
                                speed = float(sm.group(1).replace(",", "."))
                        k += 1
                        break
                    if _LAPNO.match(raw):
                        # 次のラップ番号（速度 246,4 等は _LAPNO に当たらない）
                        break
                    # 速度専用行（254,1）= ASSEN 系レイアウト
                    sp_m = _SPEED_VAL.match(raw)
                    if sp_m:
                        speed = float(sp_m.group(1).replace(",", "."))
                        k += 1
                        continue
                    # セグメント + ラップタイム同一行（読み順 r1 のセグメントを保持）
                    cs_m = _COMBINED_SEG.match(raw)
                    if lap_time is None:
                        tm = _LAPTIME_INLINE.match(raw)
                        if tm:
                            lap_time = tm.group(1)
                            tail = s.split(lap_time, 1)[-1]
                            cancelled = "C" in tail
                            pit = pit or ("P" in tail)
                            if cs_m:
                                raw_segs.append(float(cs_m.group(1)))
                            k += 1
                            continue
                    elif s == "C":
                        # ASSEN系では C（Lap Time Cancelled）が Seg.4 の後の独立行に出る
                        cancelled = True
                        k += 1
                        continue
                    elif s == "P":
                        pit = True
                        k += 1
                        continue
                    # 単独セグメント行（27.502 等）— 読み順を保持
                    seg_m = _SEG_VAL.match(raw)
                    if seg_m:
                        raw_segs.append(float(seg_m.group(1)))
                        if "P" in s:
                            pit = True
                    k += 1
                if lap_time and local_time_seen:
                    lts = parse_time_s(lap_time)
                    # seg1..seg4 は **較正済みレイアウト（seg_trust=True）のみ**写像する。
                    # MISANO 系（PDF 単位で _SPEED_LOCALTIME を検出 → seg_trust=False）は
                    # セグメント読み順がラップ間で不安定なため誤割当を避け NULL のままにする
                    # （sum は不変でも seg1↔seg3 等のラベルが狂うリスク）。lap_time/best/speed は両系で正。
                    if seg_trust:
                        seg1, seg2, seg3, seg4 = _map_segments(raw_segs, lts)
                    else:
                        seg1 = seg2 = seg3 = seg4 = None
                    cur["laps"].append({
                        "lap_no": lap_no,
                        "lap_time": lap_time,
                        "lap_time_s": lts,
                        "is_cancelled": int(cancelled),
                        "is_pit": int(pit),
                        "is_outlap": 0,   # race chrono にアウトラップ概念なし。FP/QP の精緻化は将来課題
                        "speed": speed,
                        "local_time": local_time,
                        "seg1": seg1, "seg2": seg2, "seg3": seg3, "seg4": seg4,
                        "raw_segs": raw_segs,
                    })
                    i = k
                    continue
        i += 1

    return riders


# ── 公式 Results 分類の解析（Chronological が無い場合のフォールバック） ───────

# Results ページ（reading-order）でのライダー行: "77 D. AEGERTER"
_RES_RIDER = re.compile(r"^(\d{1,3})\s+([A-Z]\.\s*[A-Z][\w'’\-]+(?:\s+[\w'’\-]+)*)\s*$")
_POS_TOKEN = re.compile(r"^(\d{1,2}|RET|DNS|DNF|DSQ)\s*[P*]?\s*$")
_LAPTIME_TOKEN = re.compile(r"^\s*(\d+'\d{2}\.\d{3})\s*$")


def parse_results_block(lines: list[str], all_riders: bool) -> dict[int, dict]:
    """
    Results ページ（reading-order）の繰り返しブロックを解析。
    "<pos>" の直後に "<num> <name>" が来るパターンを利用。ベストラップは
    ライダー行の後に現れる最初の 2 つのラップタイムのうち、後者
    （= Fastest Lap 列）を採用する（ASSEN 系フォーマットで検証）。
    Chronological が取れた場合は使わない（順位/ベストは Chronological を優先）。
    """
    riders: dict[int, dict] = {}
    n = len(lines)
    for i in range(n):
        rm = _RES_RIDER.match(lines[i].strip())
        if not rm:
            continue
        num = int(rm.group(1))
        if not all_riders and num not in TARGET_RIDERS:
            continue
        name = rm.group(2).strip()
        # 直前の数行から順位トークンを探す
        pos = None
        for j in range(i - 1, max(-1, i - 4), -1):
            pm = _POS_TOKEN.match(lines[j].strip())
            if pm:
                v = pm.group(1)
                pos = int(v) if v.isdigit() else None
                break
        # 直後の数行からラップタイムを最大 2 つ収集
        times = []
        for j in range(i + 1, min(n, i + 10)):
            tm = _LAPTIME_TOKEN.match(lines[j].strip())
            if tm:
                times.append(tm.group(1))
            if len(times) >= 2:
                break
            if _RES_RIDER.match(lines[j].strip()):
                break
        best = times[1] if len(times) >= 2 else (times[0] if times else None)
        riders[num] = {
            "position": pos,
            "status": None,
            "rider_num": num,
            "rider_name": name,
            "best_lap": best,
            "best_lap_s": parse_time_s(best),
            "laps": [],
        }
    return riders


# ── PDF 1 ファイル抽出 ──────────────────────────────────────────────────────

def extract_pdf(pdf_path: Path, all_riders: bool = False) -> dict:
    """
    返り値: {"meta": {...}, "source": "chronological"|"results"|"none",
             "riders": {num: {...}} }
    riders[num]["laps"] には複数ページにまたがる全ラップが入る。
    """
    doc = fitz.open(str(pdf_path))
    full_text = "".join(pg.get_text() for pg in doc)
    meta = _meta_from_filename(pdf_path)
    meta = _meta_from_text(full_text, meta)

    has_chrono = "Chronological Analysis" in full_text
    lines = concat_pages(doc)
    doc.close()

    # レイアウト判定（PDF 単位）: 「速度 + ローカルタイム」同一行が現れる = MISANO 系。
    # この系はセグメント読み順が不安定なため seg1..seg4 を写像しない（seg_trust=False）。
    seg_trust = not any(_SPEED_LOCALTIME.match(l.strip()) for l in lines)
    meta["seg_layout"] = "assen" if seg_trust else "misano"

    riders: dict[int, dict] = {}
    source = "none"
    if has_chrono:
        riders = parse_chronological(lines, all_riders, seg_trust=seg_trust)
        # ラップが 1 本でも取れていれば chronological を採用
        if any(r["laps"] for r in riders.values()) or riders:
            source = "chronological"
    if not riders:
        riders = parse_results_block(lines, all_riders)
        if riders:
            source = "results"

    return {"meta": meta, "source": source, "riders": riders}


# ── DB（race_results 互換） ─────────────────────────────────────────────────

def _ensure_tables(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS race_results (
        result_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        round         TEXT,
        circuit       TEXT,
        session_type  TEXT,
        date          TEXT,
        position      INTEGER,
        rider_num     INTEGER,
        rider_name    TEXT,
        nationality   TEXT,
        team          TEXT,
        bike          TEXT,
        laps          INTEGER,
        race_time     TEXT,
        gap           TEXT,
        best_lap      TEXT,
        best_lap_s    REAL,
        sector1       TEXT,
        sector2       TEXT,
        sector3       TEXT,
        source_file   TEXT,
        imported_at   TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS pdf_lap_times_v2 (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        round         TEXT,
        circuit       TEXT,
        session_type  TEXT,
        date          TEXT,
        position      INTEGER,
        rider_num     INTEGER,
        rider_name    TEXT,
        lap_no        INTEGER,
        seg1 REAL, seg2 REAL, seg3 REAL, seg4 REAL,   -- 4セグ揃い & sum≈laptime のみ充填(他はNULL)
        lap_time      TEXT,
        lap_time_s    REAL,
        speed         REAL,
        local_time    TEXT,
        is_outlap     INTEGER DEFAULT 0,
        is_pit        INTEGER DEFAULT 0,
        is_cancelled  INTEGER DEFAULT 0,
        source_file   TEXT,
        extractor_version TEXT,
        imported_at   TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def write_to_db(result: dict, source_file: str, db_path: Path,
                write_laps: bool = False) -> tuple[int, int]:
    conn = sqlite3.connect(str(db_path))
    _ensure_tables(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    m = result["meta"]
    n_res = n_lap = 0
    for num, r in sorted(result["riders"].items(), key=lambda kv: (kv[1].get("position") or 999)):
        laps = r.get("laps", [])
        conn.execute(
            """INSERT INTO race_results
               (round, circuit, session_type, date, position, rider_num,
                rider_name, laps, best_lap, best_lap_s, source_file, imported_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m.get("round"), m.get("circuit"), m.get("session_type"), m.get("date"),
             r.get("position"), num, r.get("rider_name"),
             len(laps) or None, r.get("best_lap"), r.get("best_lap_s"),
             source_file, now),
        )
        n_res += 1
        if write_laps:
            for lp in laps:
                conn.execute(
                    """INSERT INTO pdf_lap_times_v2
                       (round, circuit, session_type, date, position, rider_num,
                        rider_name, lap_no, seg1, seg2, seg3, seg4, lap_time, lap_time_s,
                        speed, local_time, is_outlap, is_pit, is_cancelled,
                        source_file, extractor_version, imported_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (m.get("round"), m.get("circuit"), m.get("session_type"), m.get("date"),
                     r.get("position"), num, r.get("rider_name"),
                     lp["lap_no"], lp.get("seg1"), lp.get("seg2"), lp.get("seg3"), lp.get("seg4"),
                     lp["lap_time"], lp["lap_time_s"], lp.get("speed"), lp.get("local_time"),
                     lp.get("is_outlap", 0), lp.get("is_pit", 0), lp["is_cancelled"],
                     source_file, EXTRACTOR_VERSION, now),
                )
                n_lap += 1
    conn.commit()
    conn.close()
    return n_res, n_lap


# ── 出力（dry-run / 標準出力） ───────────────────────────────────────────────

def print_result(pdf_path: Path, result: dict, show_laps: bool):
    m = result["meta"]
    log.info("FILE: %s", pdf_path.name)
    log.info("  meta: round=%s circuit=%s session=%s date=%s  [source=%s]",
             m.get("round"), m.get("circuit"), m.get("session_type"),
             m.get("date"), result["source"])
    if not result["riders"]:
        log.info("  対象ライダーなし")
        return
    for num, r in sorted(result["riders"].items(), key=lambda kv: (kv[1].get("position") or 999)):
        laps = r.get("laps", [])
        valid = [lp for lp in laps if not lp["is_cancelled"]]
        pos_disp = r.get("position") if r.get("position") is not None else (r.get("status") or "-")
        log.info("  #%-3d %-22s pos=%-4s best=%s (%ss)  laps=%d (valid=%d)",
                 num, r.get("rider_name"), pos_disp,
                 r.get("best_lap"), r.get("best_lap_s"), len(laps), len(valid))
        if show_laps and laps:
            for lp in laps:
                flag = " C" if lp["is_cancelled"] else ""
                log.info("      L%-2d %s (%ss)%s", lp["lap_no"], lp["lap_time"],
                         lp["lap_time_s"], flag)


# ── エントリポイント ────────────────────────────────────────────────────────

def process(pdf_path: Path, args) -> dict | None:
    if not pdf_path.exists():
        log.error("ファイルが見つかりません: %s", pdf_path)
        return None
    try:
        result = extract_pdf(pdf_path, all_riders=args.all_riders)
    except Exception as e:
        log.error("抽出エラー: %s — %s", pdf_path.name, e)
        return None

    print_result(pdf_path, result, show_laps=args.laps)

    if args.write and not args.dry_run:
        n_res, n_lap = write_to_db(result, str(pdf_path), args.db, write_laps=args.laps)
        log.info("  → DB書込: results=%d laps=%d (%s)", n_res, n_lap, args.db)
    elif args.dry_run:
        log.info("  [dry-run] DB書込なし")
    return result


def main():
    ap = argparse.ArgumentParser(description="WorldSSP PDF リザルト抽出 v2 (PyMuPDF・複数ページ堅牢)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", type=Path, help="単一PDF")
    g.add_argument("--dir", type=Path, help="フォルダ内の全PDF")
    g.add_argument("--all", action="store_true", help="07_RESULTS/ 以下を全スキャン")
    ap.add_argument("--all-riders", action="store_true", help="全ライダー抽出（既定はDA77/JA52）")
    ap.add_argument("--laps", action="store_true", help="ラップ明細も出力/書込")
    ap.add_argument("--write", action="store_true", help="DBへ書き込む（既定は書込なし）")
    ap.add_argument("--dry-run", action="store_true", help="DB書込なしで確認のみ")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="書込先DB（既定: ts24_unified.db）")
    args = ap.parse_args()

    targets: list[Path] = []
    if args.file:
        targets = [args.file]
    elif args.dir:
        targets = sorted(args.dir.glob("*.pdf"))
    else:
        if not RESULTS_ROOT.exists():
            log.error("07_RESULTS/ が見つかりません: %s", RESULTS_ROOT)
            sys.exit(1)
        targets = sorted(RESULTS_ROOT.rglob("*.pdf"))

    log.info("対象: %d ファイル  (write=%s db=%s)", len(targets), args.write, args.db)
    tot_res = tot_lap = 0
    for p in targets:
        r = process(p, args)
        if r:
            tot_res += len(r["riders"])
            tot_lap += sum(len(x["laps"]) for x in r["riders"].values())
    log.info("合計: riders=%d laps=%d", tot_res, tot_lap)


if __name__ == "__main__":
    main()
