#!/usr/bin/env python3
"""
extraction_scan.py — TS24 Phase 2A Extraction Pipeline (scan → registry → queue)

設計書: reports/phase2_extraction_pipeline_design_20260620.md (rev.2)。

Phase 2A の範囲のみ:
  - DATA 2D / 01_REPORTS / 07_RESULTS を scan
  - ファイル検出（tier・種別・除外・安定性・2D は manifest hash）
  - source_file_registry に登録（status: discovered / incomplete / gated / unknown）
  - 'discovered' を import_queue に投入（status: pending）
  - 検出チェックを data_quality_log に detect_* で記録
  - analysis_run_log に scan 実行を1行記録
  - 冪等（sha256 / manifest hash で変更検出）

やらないこと（Phase 2B 以降）:
  - scratch DB 生成・データ抽出・Quality Gate
  - **正本の「業務テーブル」への書き込みは一切しない**
  本スクリプトが書くのは「管理テーブル」のみ（rev.2 §0.1 で許可）:
    source_file_registry / import_queue / data_quality_log / analysis_run_log

実行: python3 extraction_scan.py            (引数なし = 全域 MAINTENANCE scan・従来動作)
      python3 extraction_scan.py --dry-run  (検出のみ・DB書込なし)
      python3 extraction_scan.py --db <path> / --no-backup / --min-age <sec>
      python3 extraction_scan.py --manifest <event_manifest.json>
          (LIVE event-scoped scan: manifest 宣言 raw root のみ走査・round 一致の
           reports/results のみ・queue 投入も event 内に限定。§75 Event Control Plane B-2。
           --manifest 無指定時の挙動は従来と完全同一=後方互換)
exit: 0=成功 / 1=DB無効 / 2=管理テーブル未作成 / 5=manifest 検証・scope 失敗（fail-closed・無書込）
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "05_SCRIPTS"
DEFAULT_DB = ROOT / "02_DATABASE" / "ts24_unified.db"
DATA_2D = ROOT / "DATA 2D"
REPORTS = ROOT / "01_REPORTS"
RESULTS = ROOT / "07_RESULTS"

# 業務テーブル（書込禁止・防御チェック用）
BUSINESS_TABLES = {
    "runs", "laps", "lap_suspension", "lap_metrics", "race_results", "pdf_lap_times",
    "performance", "problem_log", "setup_decision_log", "events", "tags", "run_tags",
    "best_worst_pairs", "round_brief", "problem_library", "lap_observation_log",
}
MGMT_TABLES = {"source_file_registry", "import_queue", "data_quality_log", "analysis_run_log"}

# 半端コピー・一時ファイル除外（rev.2 §3.1）
EXCLUDE_NAME = re.compile(
    r"(^~\$)|(^\._)|(\.tmp$)|(\.partial$)|(\.crdownload$)|(\.download$)|(\.icloud$)|(^\.DS_Store$)",
    re.I,
)
# 2D outing の manifest: 全バイト hash する小メタ拡張子
MANIFEST_FULL_EXT = {".DDD", ".LAP", ".HED", ".SEC", ".STI", ".IST", ".CAL", ".LDD", ".UDM"}
STABLE_AGE_SEC_DEFAULT = 10  # mtime がこの秒数より新しいファイル＝コピー中の可能性→不安定

PDF_SESSION_RE = re.compile(r"(\d{8})-(ROUND\d+|TEST\d+)-([A-Z0-9]+)", re.I)


# ───────────────────────── build_master_db 再利用 ─────────────────────────
def load_bmdb():
    """build_master_db.py を絶対パスで読み込み、検出関数を再利用する。
    モジュールの相対パス定数を絶対化（importlib ロード時の __file__ 相対対策）。"""
    spec = importlib.util.spec_from_file_location("bmdb", str(SCRIPTS / "build_master_db.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    # 相対化されうる定数を絶対パスに固定
    for attr, val in (("ROOT", ROOT), ("DATA_2D", DATA_2D), ("REPORTS", REPORTS)):
        if hasattr(m, attr):
            setattr(m, attr, val)
    return m


# ───────────────────────── ハッシュ・安定性 ─────────────────────────
def sha256_file(p: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def sha256_head(p: Path, n=4096) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read(n))
    return h.hexdigest()


def is_excluded(name: str) -> bool:
    return bool(EXCLUDE_NAME.search(name))


def file_stable(p: Path, min_age: int, now: float) -> bool:
    """mtime が min_age 秒より古ければ安定とみなす（コピー中でない proxy）。
    watch モードでの 2回サンプル法の代替（scan モード用）。"""
    try:
        return (now - p.stat().st_mtime) >= min_age
    except OSError:
        return False


def manifest_hash(files: list[Path], deep: bool = False,
                  deep_all: bool = False) -> tuple[str, int, str]:
    """2D outing の manifest hash。
    既定(stat-only): 各ファイル (name,size,mtime) を正規化連結して sha256。**中身は読まない**
      → iCloud のデータレス(未ダウンロード)ファイルでダウンロードを誘発せず、ハング/遅延しない
        (2A=「抽出しない・疑うだけ」の原則。検出に内容読込は不要)。差分検出は size/mtime で十分。
    deep=True(--deep-hash): 小メタ拡張子のみ全バイト sha256 を併用(全ファイルDL済が前提)。
    deep_all=True(live manifest scan・fingerprint_policy='content'): **全ファイル**を全バイト
      sha256（同名同サイズ差替=adversarial シナリオ1 を live event で検出。走査は当該イベント
      1個のみ=有界。全ファイルDL済前提=live weekend の運用条件）。
    戻り: (sha256, ファイル数, 構成メモ)。"""
    if deep_all:
        lines = []
        n = 0
        for p in sorted(files, key=lambda x: x.name.lower()):
            try:
                lines.append(f"{p.name}|{p.stat().st_size}|FULL|{sha256_file(p)}")
                n += 1
            except OSError:
                continue
        blob = "\n".join(lines)
        return (hashlib.sha256(blob.encode()).hexdigest(), n,
                f"manifest: content(full-hash all) {n} files")
    lines = []
    full = stat = 0
    for p in sorted(files, key=lambda x: x.name.lower()):
        try:
            st = p.stat()  # メタデータのみ。データレスでも内容DLを誘発しない
        except OSError:
            continue
        if deep and p.suffix.upper() in MANIFEST_FULL_EXT:
            lines.append(f"{p.name}|{st.st_size}|FULL|{sha256_file(p)}")
            full += 1
        else:
            # mtime は iCloud 同期がバックグラウンドで更新し jitter するため除外。
            # name|size + ファイル集合で変更検出（logger 出力は再exportで size/集合が変わる）。
            lines.append(f"{p.name}|{st.st_size}|SIZE")
            stat += 1
    blob = "\n".join(lines)
    note = (f"manifest: {full} full-hash(meta) + {stat} size-only = {full+stat} files"
            if deep else f"manifest: size-only(name,size) {stat} files")
    return hashlib.sha256(blob.encode()).hexdigest(), full + stat, note


def stat_sig(p: Path, deep: bool = False) -> str:
    """単一ファイルの変更フィンガープリント。既定は size ベース(中身を読まない)。
    mtime は iCloud 同期 jitter のため除外。deep=True で全バイト sha256。レポート/PDF 用。"""
    if deep:
        return sha256_file(p)
    try:
        st = p.stat()
        return "stat:" + hashlib.sha256(f"{st.st_size}".encode()).hexdigest()[:32]
    except OSError:
        return ""


# ───────────────────────── 検出結果コンテナ ─────────────────────────
class Detected:
    __slots__ = ("file_id", "file_path", "file_name", "file_type", "file_size",
                 "file_mtime", "sha256", "rider", "circuit", "round", "session",
                 "status", "notes", "target_kind", "checks", "ekey")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))
        if self.checks is None:
            self.checks = []  # (check_name, result, severity, detail)


def add_check(d: Detected, name, result, severity, detail):
    d.checks.append((name, result, severity, detail))


# ───────────────────────── DATA 2D 検出 ─────────────────────────
def scan_2d(bmdb, min_age: int, now: float, deep: bool = False,
            manifest: dict | None = None) -> list[Detected]:
    """manifest=None（既定）= 従来どおり全イベント走査（後方互換・挙動不変）。
    manifest 指定時（live event-scoped scan・§75 B-2）:
      - manifest.event_key の 1 イベントのみ走査（event-external ソースは構造的に対象外）
      - allowed_sessions 外の session / expected_outings 外の outing stem は 'gated'
        （queue へは入らない = fail-closed）
      - fingerprint_policy='content' なら全ファイル全バイト hash（同名差替検出）"""
    out = []
    try:
        events = bmdb.discover_events()
    except Exception as e:
        print(f"[WARN] discover_events 失敗: {e}", file=sys.stderr)
        return out
    m_sessions = m_expected = None
    m_deep_all = False
    if manifest is not None:
        events = {k: v for k, v in events.items() if k == manifest["event_key"]}
        m_sessions = set(manifest["allowed_sessions"])
        if manifest.get("expected_outings") is not None:
            m_expected = set(manifest["expected_outings"])
        m_deep_all = manifest.get("fingerprint_policy", "content") == "content"
    for name, ev in events.items():
        try:
            outings = bmdb.discover_outings(ev["dir"])
        except Exception as e:
            print(f"[WARN] discover_outings({name}) 失敗: {e}", file=sys.stderr)
            continue
        # event_circuit は openpyxl を開くため重い。HEDゲートが要る copia/loose が
        # ある時だけ計算する（大半の nested-only イベントでは省略＝高速化）。
        ev_circ = ""
        if any(t in ("copia", "loose") for (_m, _b, t) in outings):
            try:
                ev_circ = bmdb.event_circuit(ev)
            except Exception:
                pass
        for mes_path, base, tier in outings:
            ddd = mes_path / f"{base}.DDD"
            lap = mes_path / f"{base}.LAP"
            files = sorted(mes_path.glob(f"{base}.*"))
            files = [f for f in files if f.is_file() and not is_excluded(f.name)]
            rep_path = ddd if ddd.exists() else (files[0] if files else mes_path)
            ekey = f"{name}/{base}"  # event/base（同一なら物理コピー＝後で重複疑い記録）
            # file_id は物理パス由来（コピーが複数あれば別行＝台帳として正直に登録）
            file_id = "2d:" + hashlib.sha256(str(rep_path).encode()).hexdigest()[:16]
            d = Detected(
                file_id=file_id, file_path=str(rep_path), file_name=f"{ekey} ({tier})",
                file_type="2d_outing", target_kind="2d_extract",
                rider=ev.get("rider"), round=ev.get("round"), circuit=ev_circ or None,
                session=None, checks=[], ekey=ekey,
            )
            # 必須随伴チェック
            if not ddd.exists() or not lap.exists():
                d.status = "incomplete"
                miss = [x for x, ok in ((".DDD", ddd.exists()), (".LAP", lap.exists())) if not ok]
                d.notes = f"tier={tier}; 必須欠落={miss}"
                add_check(d, "detect_incomplete", "WARNING", "warn",
                          f"{file_id}: 必須随伴ファイル欠落 {miss}")
                out.append(d)
                continue
            # 安定性（コピー中？）
            unstable = [f.name for f in files if not file_stable(f, min_age, now)]
            if unstable:
                d.status = "incomplete"
                d.notes = f"tier={tier}; 不安定(コピー中?)={unstable[:5]}"
                add_check(d, "detect_unstable", "WARNING", "warn",
                          f"{file_id}: mtime<{min_age}s のファイル {len(unstable)}件 → 保留")
                out.append(d)
                continue
            # manifest hash（既定 stat-only=中身を読まない / live content policy は全バイト）
            mh, nfiles, mnote = manifest_hash(files, deep=deep, deep_all=m_deep_all)
            d.sha256 = mh
            try:
                st = ddd.stat()
                d.file_size = st.st_size
                d.file_mtime = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
            except OSError:
                pass
            # manifest scope gate（live scan のみ・fail-closed: gated は queue へ入らない。
            # hash 計算後に置く = gated 行も fingerprint を保持し registry/receipt で追跡可能）
            if manifest is not None:
                try:
                    sess = bmdb.session_canon_2d(base, ev.get("round") or "")
                except Exception:
                    sess = None
                d.session = sess
                if sess not in m_sessions:
                    d.status = "gated"
                    d.notes = f"tier={tier}; session={sess!r} not in manifest allowed_sessions; {mnote}"
                    add_check(d, "detect_session_not_allowed", "FAIL", "critical",
                              f"{file_id}: session={sess!r} は manifest 許可外 "
                              f"({sorted(m_sessions)}) → gated(Tatsuki判断)")
                    out.append(d)
                    continue
                if m_expected is not None and base not in m_expected:
                    d.status = "gated"
                    d.notes = f"tier={tier}; outing {base!r} not in manifest expected_outings; {mnote}"
                    add_check(d, "detect_outing_not_expected", "FAIL", "critical",
                              f"{file_id}: outing stem {base!r} は manifest 宣言集合外 → gated")
                    out.append(d)
                    continue
            # HED 矛盾（copia/loose のみゲート。nested は HED 陳腐化のため不問＝本体方針踏襲）
            note = f"tier={tier}; {mnote}"
            if tier in ("copia", "loose") and ev_circ:
                try:
                    hc, tlen, fast = bmdb._hed_meta(mes_path, base)
                except Exception:
                    hc = ""
                if hc and hc != ev_circ:
                    d.status = "gated"
                    note += f"; HED_circuit={hc}!=event={ev_circ}"
                    add_check(d, "detect_hed_circuit_mismatch", "WARNING", "warn",
                              f"{file_id}: HED circuit={hc} != event={ev_circ} → gated(Tatsuki判断)")
                    d.notes = note
                    out.append(d)
                    continue
            d.status = "discovered"
            d.notes = note
            out.append(d)
    # 同一 event/base が複数物理パスに存在（_Copy / サブフォルダ等）→ 重複を疑い記録
    from collections import defaultdict as _dd
    groups = _dd(list)
    for d in out:
        groups[d.ekey].append(d)
    for ekey, members in groups.items():
        if len(members) > 1:
            paths = [m.file_path for m in members]
            for m in members:
                add_check(m, "detect_duplicate_base", "WARNING", "warn",
                          f"{ekey}: 同一base が {len(members)} パスに存在（コピー疑い）: {paths}")
                m.notes = (m.notes or "") + f"; dup_base x{len(members)}"
    return out


# ───────────────────────── 01_REPORTS 検出 ─────────────────────────
def scan_reports(min_age: int, now: float, deep: bool = False) -> list[Detected]:
    out = []
    if not REPORTS.exists():
        return out
    for p in sorted(REPORTS.rglob("*.xlsx")):
        if not p.is_file() or is_excluded(p.name):
            continue
        rel = str(p.relative_to(ROOT))
        is_company = "COMPANY" in str(p).upper()
        d = Detected(
            file_id="report:" + hashlib.sha256(str(p).encode()).hexdigest()[:16],
            file_path=rel, file_name=p.name,
            file_type="report_company" if is_company else "report",
            target_kind="report_import", checks=[],
        )
        # 命名からメタ
        m = PDF_SESSION_RE.search(p.stem)
        if m:
            d.round = m.group(2).upper()
            d.rider = m.group(3).upper()
        try:
            st = p.stat()
            d.file_size = st.st_size
            d.file_mtime = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        except OSError:
            pass
        if not file_stable(p, min_age, now):
            d.status = "incomplete"
            d.notes = "不安定(コピー中?)"
            add_check(d, "detect_unstable", "WARNING", "warn", f"{rel}: mtime<{min_age}s → 保留")
            out.append(d)
            continue
        # 2A は中身を読まない: 種別は配置/拡張子で確定。シート構造の検証(DAY1/REPORT等)は
        # 内容読込が要るため Phase 2B に委譲(openpyxl は iCloud データレスでハングしうる)。
        d.sha256 = stat_sig(p, deep=deep)
        d.status = "discovered"
        d.notes = ("COMPANY/BSB" if is_company else "report") + "; 構造検証は2Bで実施"
        out.append(d)
    return out


# ───────────────────────── 07_RESULTS 検出 ─────────────────────────
def _is_pdf(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return f.read(5).startswith(b"%PDF")
    except OSError:
        return False


def scan_results(min_age: int, now: float, deep: bool = False) -> list[Detected]:
    out = []
    if not RESULTS.exists():
        return out
    for p in sorted(RESULTS.rglob("*")):
        if not p.is_file() or is_excluded(p.name):
            continue
        is_pdf_ext = p.suffix.lower() == ".pdf"
        # 拡張子なし PDF はマジック判定（rev.2 §2 必須要件）
        extless_pdf = (p.suffix == "" and _is_pdf(p))
        if not (is_pdf_ext or extless_pdf):
            continue
        rel = str(p.relative_to(ROOT))
        is_bsb = "-RESULT-BSB" in str(p).upper()
        d = Detected(
            file_id="result:" + hashlib.sha256(str(p).encode()).hexdigest()[:16],
            file_path=rel, file_name=p.name,
            # chrono/classification の細分は内容読みが要るため Phase 2B に委譲（2Aは抽出しない）
            file_type="result_bsb" if is_bsb else "result_pdf",
            target_kind="pdf_extract", checks=[],
        )
        m = PDF_SESSION_RE.search(p.name)
        if m:
            d.round = m.group(2).upper()
            d.session = m.group(3).upper()
        try:
            st = p.stat()
            d.file_size = st.st_size
            d.file_mtime = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        except OSError:
            pass
        if not file_stable(p, min_age, now):
            d.status = "incomplete"
            d.notes = "不安定(コピー中?)"
            add_check(d, "detect_unstable", "WARNING", "warn", f"{rel}: mtime<{min_age}s → 保留")
            out.append(d)
            continue
        d.sha256 = stat_sig(p, deep=deep)
        d.status = "discovered"
        d.notes = ("拡張子なしPDF(%PDF判定); " if extless_pdf else "") + ("BSB" if is_bsb else "PDF")
        out.append(d)
    return out


# ───────────────────────── DB 反映（管理テーブルのみ） ─────────────────────────
def assert_mgmt_only():
    # 防御: 本スクリプトは業務テーブルに一切 INSERT/UPDATE しない（コードレビュー用の明示）。
    assert not (BUSINESS_TABLES & MGMT_TABLES)


def backup_db(db_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = db_path.parent / f"_backup_extraction_scan_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / db_path.name
    shutil.copy2(db_path, dest)
    return dest


def upsert(conn, detected: list[Detected], analysis_run_id: str, now_iso: str,
           self_heal: bool = True):
    """self_heal=True（既定・従来動作）: 全 registry を対象に discovered→queued 整合。
    live manifest scan は self_heal=False（event 外の行に一切触れない）。"""
    cur = conn.cursor()
    ins = upd = unchanged = queued = 0
    for d in detected:
        row = cur.execute(
            "SELECT sha256, status FROM source_file_registry WHERE file_path=?",
            (d.file_path,),
        ).fetchone()
        if row is None:
            cur.execute(
                """INSERT INTO source_file_registry
                   (file_id,file_path,file_name,file_type,file_size,file_mtime,sha256,
                    rider,circuit,round,session,discovered_at,status,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d.file_id, d.file_path, d.file_name, d.file_type, d.file_size, d.file_mtime,
                 d.sha256, d.rider, d.circuit, d.round, d.session, now_iso, d.status, d.notes),
            )
            ins += 1
            _log_checks(cur, d, analysis_run_id, now_iso)
        else:
            old_sha, old_status = row
            # None==None（incomplete等の未hash）も不変扱い → 毎回の偽「更新」を防ぐ。
            # incomplete→discovered の前進時は sha256 が None→実hash になり下の更新分岐へ。
            if old_sha == d.sha256:
                unchanged += 1
                add_check(d, "detect_duplicate", "PASS", "info", f"{d.file_id}: 既登録・hash不変")
                _log_checks(cur, d, analysis_run_id, now_iso, only=("detect_duplicate",))
                # 既登録だが status を最新検出に追随（incomplete→discovered 等の前進のみ反映）
                if old_status in ("incomplete",) and d.status == "discovered":
                    cur.execute("UPDATE source_file_registry SET status='discovered', notes=?, "
                                "file_size=?, file_mtime=? WHERE file_path=?",
                                (d.notes, d.file_size, d.file_mtime, d.file_path))
                continue
            # hash 変化＝更新 → discovered に戻し再評価
            cur.execute(
                """UPDATE source_file_registry SET file_name=?,file_type=?,file_size=?,file_mtime=?,
                   sha256=?,rider=?,circuit=?,round=?,session=?,status=?,notes=? WHERE file_path=?""",
                (d.file_name, d.file_type, d.file_size, d.file_mtime, d.sha256, d.rider, d.circuit,
                 d.round, d.session, d.status, d.notes, d.file_path),
            )
            upd += 1
            add_check(d, "detect_updated", "WARNING", "warn",
                      f"{d.file_id}: hash変化（{old_sha} → {d.sha256}）→ 再評価")
            _log_checks(cur, d, analysis_run_id, now_iso)
        # queue 投入（discovered のみ・既存 open 行が無ければ）。
        # 既に open 行がある場合も registry を 'queued' に揃える（status整合）。
        if d.status == "discovered":
            open_row = cur.execute(
                """SELECT 1 FROM import_queue WHERE file_id=?
                   AND status IN ('pending','processing','awaiting_gate') LIMIT 1""",
                (d.file_id,),
            ).fetchone()
            if open_row is None:
                cur.execute(
                    """INSERT INTO import_queue
                       (file_id,file_path,target_kind,priority,status,enqueued_at,notes)
                       VALUES (?,?,?,?, 'pending', ?, ?)""",
                    (d.file_id, d.file_path, d.target_kind, 100, now_iso, "Phase2A scan"),
                )
                queued += 1
            cur.execute("UPDATE source_file_registry SET status='queued' WHERE file_path=?",
                        (d.file_path,))
    # 自己修復: open queue 行を持つ discovered を queued に整合（移行/中断時の取り残し対策）
    # live manifest scan では skip（event 外 registry 行への副作用ゼロを保証）
    if self_heal:
        cur.execute(
            """UPDATE source_file_registry SET status='queued'
               WHERE status='discovered' AND file_id IN
                 (SELECT file_id FROM import_queue
                  WHERE status IN ('pending','processing','awaiting_gate'))"""
        )
    conn.commit()
    return ins, upd, unchanged, queued


def _log_checks(cur, d: Detected, analysis_run_id, now_iso, only=None):
    for (name, result, severity, detail) in d.checks:
        if only and name not in only:
            continue
        cur.execute(
            """INSERT INTO data_quality_log
               (analysis_run_id,check_name,scope,scope_id,result,severity,detail,checked_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (analysis_run_id, name, "source_file", d.file_id, result, severity, detail, now_iso),
        )


def main() -> int:
    assert_mgmt_only()
    ap = argparse.ArgumentParser(
        description="TS24 Phase 2A: 検出→registry→queue（業務テーブル不変）。"
                    "引数なし=全域 MAINTENANCE scan（従来動作）/ --manifest=LIVE event-scoped scan")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true", help="検出のみ・DB書込なし")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--min-age", type=int, default=STABLE_AGE_SEC_DEFAULT,
                    help=f"安定とみなす mtime 経過秒（既定{STABLE_AGE_SEC_DEFAULT}）")
    ap.add_argument("--deep-hash", action="store_true",
                    help="全バイト sha256 を併用（全ファイルDL済前提・iCloudデータレスでは遅延/ハング注意）")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="Event Manifest JSON（02_DATABASE/event_manifests/*.json）。指定時は "
                         "LIVE event-scoped scan: manifest 宣言 raw root のみ走査・round 一致の "
                         "reports/results のみ・queue 投入も event 内に限定（§75 B-2）。"
                         "無指定 = 全域 MAINTENANCE scan（従来動作・後方互換）")
    args = ap.parse_args()

    now = time.time()
    now_iso = datetime.now().isoformat(timespec="seconds")

    # ── LIVE manifest モード（fail-closed・検証不合格なら scan 前に exit 5） ──
    manifest = None
    if args.manifest is not None:
        try:
            import event_manifest as evm
        except ImportError:
            sys.path.insert(0, str(SCRIPTS))
            import event_manifest as evm
        try:
            manifest = evm.load_manifest(args.manifest, verify_hash=True, require_hash=True)
        except evm.ManifestError as e:
            print(f"[FATAL] manifest 検証失敗（fail-closed・scan/queue 無変更）: {e}", file=sys.stderr)
            return 5
        raw_root = ROOT / manifest["raw_2d_root"]
        if not raw_root.is_dir():
            print(f"[FATAL] manifest raw_2d_root が存在しません（fail-closed）: {raw_root}",
                  file=sys.stderr)
            return 5
        print(f"[INFO] LIVE event-scoped scan: {manifest['event_key']} "
              f"v{manifest['manifest_version']} hash={manifest['content_hash'][:12]}… "
              f"policy={manifest['fingerprint_policy']} allowed={manifest['allowed_sessions']}")

    bmdb = load_bmdb()

    mode = "deep-hash(全バイト)" if args.deep_hash else "stat-only(size,mtime・中身読まない)"
    if manifest is not None and manifest.get("fingerprint_policy", "content") == "content":
        mode = "content(全ファイル全バイト・live manifest)"
    print(f"[INFO] Phase 2A scan 開始（業務テーブルには書き込みません / 同一性={mode}）")
    det2d = scan_2d(bmdb, args.min_age, now, deep=args.deep_hash, manifest=manifest)
    detrep = scan_reports(args.min_age, now, deep=args.deep_hash)
    detres = scan_results(args.min_age, now, deep=args.deep_hash)
    if manifest is not None:
        # event-scoped filter: round 一致の reports/results のみ（event-external は live 対象外）
        rnd = manifest["round"]
        riders = set(manifest["riders"])
        detrep = [d for d in detrep if d.round == rnd and d.rider in riders]
        detres = [d for d in detres if d.round == rnd]
    detected = det2d + detrep + detres

    # サマリ
    from collections import Counter
    by_status = Counter(d.status for d in detected)
    by_type = Counter(d.file_type for d in detected)
    print(f"[INFO] 検出: 2D={len(det2d)} report={len(detrep)} pdf={len(detres)} 合計={len(detected)}")
    print(f"[INFO] status別: {dict(by_status)}")
    print(f"[INFO] type別  : {dict(by_type)}")

    if args.dry_run:
        print("[DRY-RUN] DB 書込なし。検出サンプル（先頭10）:")
        for d in detected[:10]:
            print(f"  [{d.status:11}] {d.file_type:20} {d.file_id}  {d.notes or ''}")
        return 0

    db = args.db
    if not db.exists() or db.stat().st_size == 0:
        print(f"[FATAL] DB が無効: {db}", file=sys.stderr)
        return 1
    if not args.no_backup:
        print(f"[INFO] バックアップ: {backup_db(db)}")

    conn = sqlite3.connect(str(db))
    # 管理テーブル存在チェック（Phase1未実行なら停止）
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = MGMT_TABLES - have
    if missing:
        print(f"[FATAL] 管理テーブル未作成: {missing} → 先に create_quality_tables.py", file=sys.stderr)
        conn.close()
        return 2

    analysis_run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_extraction_scan"
    run_scope = manifest["event_key"] if manifest is not None else "ALL"
    params = {"min_age": args.min_age}
    if manifest is not None:
        params["manifest"] = str(args.manifest)
        params["manifest_content_hash"] = manifest["content_hash"]
    conn.execute(
        """INSERT INTO analysis_run_log
           (analysis_run_id,script_name,agent,target_db,target_table,run_scope,
            rows_in,started_at,status,params_json,notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (analysis_run_id, "extraction_scan.py", "Extraction", "unified",
         "source_file_registry,import_queue", run_scope, len(detected), now_iso, "running",
         json.dumps(params),
         "LIVE event-scoped scan（業務テーブル不変）" if manifest is not None
         else "Phase2A scan（業務テーブル不変）"),
    )
    conn.commit()

    ins, upd, unchanged, queued = upsert(conn, detected, analysis_run_id, now_iso,
                                         self_heal=(manifest is None))

    # ── live scan の ledger 受領書（event_state_ledger があるときのみ・後方互換） ──
    if manifest is not None:
        try:
            import event_manifest as evm
            if evm.tables_exist(conn):
                identities = [
                    dict(event_key=manifest["event_key"],
                         outing_stem=d.ekey.split("/", 1)[1] if d.ekey else d.file_name,
                         fingerprint=d.sha256, status=d.status)
                    for d in det2d
                ]
                evm.append_ledger(
                    conn, manifest["event_key"], scope="event", scope_id=None,
                    state="registered",
                    reason=f"live scan: 2d={len(det2d)} report={len(detrep)} pdf={len(detres)} "
                           f"new={ins} updated={upd} unchanged={unchanged} queued={queued}",
                    actor="extraction_scan.py", analysis_run_id=analysis_run_id,
                    manifest_version=manifest["manifest_version"],
                    manifest_content_hash=manifest["content_hash"],
                    receipt=dict(identities=identities, min_age=args.min_age,
                                 fingerprint_policy=manifest.get("fingerprint_policy")))
                for d in det2d:
                    if d.status in ("gated", "incomplete"):
                        evm.append_ledger(
                            conn, manifest["event_key"], scope="outing",
                            scope_id=d.ekey.split("/", 1)[1] if d.ekey else d.file_name,
                            state="quarantined", reason=d.notes or d.status,
                            actor="extraction_scan.py", analysis_run_id=analysis_run_id,
                            manifest_version=manifest["manifest_version"],
                            manifest_content_hash=manifest["content_hash"])
                conn.commit()
        except Exception as e:
            print(f"[WARN] ledger 記録失敗（scan 結果自体は有効）: {e}", file=sys.stderr)

    conn.execute(
        """UPDATE analysis_run_log SET finished_at=?, status='success',
           rows_inserted=?, rows_updated=?, rows_out=?, notes=? WHERE analysis_run_id=?""",
        (datetime.now().isoformat(timespec="seconds"), ins, upd, queued,
         f"new={ins} updated={upd} unchanged={unchanged} queued={queued}", analysis_run_id),
    )
    conn.commit()
    conn.close()

    print(f"[DONE] registry: 新規{ins} / 更新{upd} / 不変{unchanged}  | queue投入(pending): {queued}")
    print(f"[INFO] analysis_run_id={analysis_run_id}")
    print("[INFO] 業務テーブルは一切変更していません（管理テーブルのみ）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
