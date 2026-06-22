#!/usr/bin/env python3
"""
TS24 DB Master safe refresh wrapper

目的: Workbench で入力した `setup_decision_log`（→ `SETUP_EFFECTS`）等を反映するため、
`build_excel_master.py` を使って `02_DATABASE/TS24 DB Master.xlsx` を**安全に**再生成する。

安全策（このラッパーが追加する保護）:
  1. 事前チェック: 正本DB / builder / テンプレートの存在を確認。
  2. Excel オープン検出: `~$TS24 DB Master.xlsx` ロックファイル + `lsof`。掴まれていれば中止。
  3. バックアップ: 既存 xlsx を `02_DATABASE/backups/` へ退避してから再生成。
  4. ログ: `05_SCRIPTS/reports/db_master_refresh_<ts>.log` に全手順を記録。
  5. exit code 伝播: `build_excel_master.py` が失敗したらその終了コードを返す。
  6. 事後検証: 生成物の mtime/サイズ/主要シート存在、および正本DB件数の不変を確認。

このラッパーがしないこと（スコープ外・禁止）:
  - 正本DB `ts24_unified.db` の業務テーブル書込（build_excel_master.py は DB を SELECT のみ）。
  - Supabase cleanup / sync。Phase 2B。LaunchAgent / 自動定期実行。Workbench UI 変更。origin push。

`TS24 DB Master.xlsx` は DB 由来の派生成果物であり正本ではない（CLAUDE.md §23/§26, Workbench Identity）。

終了コード: 0=成功 / 1=事前チェック失敗 / 2=Excel使用中で中止 / 3=事後検証失敗 /
            その他=build_excel_master.py の終了コードを伝播
"""
import argparse
import datetime as _dt
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR  = Path(__file__).resolve().parent
DB_DIR      = SCRIPT_DIR.parent / "02_DATABASE"
DB_PATH     = DB_DIR / "ts24_unified.db"
XLSX        = DB_DIR / "TS24 DB Master.xlsx"
TEMPLATE    = DB_DIR / "TS24 DB Master Back UP.xlsx"
LOCK        = DB_DIR / "~$TS24 DB Master.xlsx"
BUILDER     = SCRIPT_DIR / "build_excel_master.py"
BACKUP_DIR  = DB_DIR / "backups"
REPORTS_DIR = SCRIPT_DIR / "reports"

KEY_SHEETS  = ["WEEKEND_SUMMARY_HELPER", "SIMILAR_CASES", "SETUP_EFFECTS",
               "RUN_LOG", "DYNAMICS_ANALYSIS", "LAP_SUSPENSION"]
DB_TABLES   = ["runs", "laps", "lap_suspension", "race_results"]


class Log:
    """ファイルとコンソールの両方へ追記（部分ログがクラッシュ時にも残る）。"""
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")
        self.path = path

    def __call__(self, msg, level="INFO"):
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {level:5s} {msg}"
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def db_counts():
    """正本DBを read-only(mode=ro) で開いて業務テーブル件数を取得。"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in DB_TABLES}
    finally:
        conn.close()


def excel_in_use(log):
    """Excel が xlsx を掴んでいるか検出。(in_use: bool, 理由: str)"""
    if LOCK.exists():
        return True, f"Office ロックファイルが存在: {LOCK.name}"
    if not XLSX.exists():
        return False, "xlsx 未作成（初回生成）"
    try:
        r = subprocess.run(["lsof", "--", str(XLSX)],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return True, "lsof がオープン中のハンドルを検出"
        return False, "lsof: 使用中プロセスなし"
    except FileNotFoundError:
        log("lsof が利用できないため open 検出をスキップ（保存失敗時にエラーで判別）", "WARN")
        return False, "lsof 不在（検出スキップ）"


def fmt_size(n):
    return f"{n:,} bytes"


def main():
    ap = argparse.ArgumentParser(description="TS24 DB Master を安全に再生成するラッパー")
    ap.add_argument("--timeout", type=int, default=600,
                    help="build_excel_master.py のタイムアウト秒（既定600）")
    args = ap.parse_args()

    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORTS_DIR.mkdir(exist_ok=True)
    log = Log(REPORTS_DIR / f"db_master_refresh_{ts}.log")

    try:
        log("=== TS24 DB Master safe refresh 開始 ===")
        log(f"DB     : {DB_PATH}")
        log(f"xlsx   : {XLSX}")
        log(f"builder: {BUILDER}")

        # 1. 事前チェック ------------------------------------------------------
        for p, name in [(DB_PATH, "正本DB"), (BUILDER, "builder"), (TEMPLATE, "テンプレート")]:
            if not p.exists():
                log(f"{name} が見つからない: {p}", "ERROR")
                return 1
        log("事前チェック OK（DB / builder / テンプレート 存在）")

        # 2. Excel オープン検出 ------------------------------------------------
        in_use, why = excel_in_use(log)
        if in_use:
            log(f"Excel が使用中のため中止: {why}。Excel を閉じてから再実行してください。", "ERROR")
            return 2
        log(f"Excel オープン検出: {why}")

        # 正本DB件数（事前・read-only） ---------------------------------------
        counts_before = db_counts()
        log(f"正本DB件数(before): {counts_before}")

        # 3. バックアップ ------------------------------------------------------
        backup_path = None
        if XLSX.exists():
            BACKUP_DIR.mkdir(exist_ok=True)
            backup_path = BACKUP_DIR / f"TS24_DB_Master.pre_refresh_{ts}.xlsx"
            shutil.copy2(XLSX, backup_path)  # mtime 保持でコピー
            log(f"バックアップ作成: {backup_path} ({fmt_size(backup_path.stat().st_size)})")
            pre_mtime = XLSX.stat().st_mtime
        else:
            log("既存 xlsx なし → バックアップ省略（初回生成）", "WARN")
            pre_mtime = 0.0

        # 4. 再生成（build_excel_master.py を subprocess 実行・exit code 伝播） --
        log("build_excel_master.py を実行中 ...")
        try:
            r = subprocess.run(
                [sys.executable, str(BUILDER)],
                cwd=str(SCRIPT_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            log(f"build_excel_master.py がタイムアウト（{args.timeout}s）", "ERROR")
            return 1
        if r.stdout:
            log("----- build stdout -----")
            for ln in r.stdout.rstrip().splitlines():
                log(f"  {ln}")
        if r.stderr.strip():
            log("----- build stderr -----")
            for ln in r.stderr.rstrip().splitlines():
                log(f"  {ln}", "WARN")
        if r.returncode != 0:
            log(f"build_excel_master.py 失敗 (exit {r.returncode})。"
                f"Excel が開いていると保存に失敗します。バックアップは保持: {backup_path}", "ERROR")
            return r.returncode  # exit code 伝播
        log("build_excel_master.py 成功 (exit 0)")

        # 5. 事後検証 ----------------------------------------------------------
        ok = True
        if not XLSX.exists():
            log("生成後に xlsx が存在しない", "ERROR")
            return 3
        st = XLSX.stat()
        log(f"生成物: {XLSX.name} / {fmt_size(st.st_size)} / mtime={_dt.datetime.fromtimestamp(st.st_mtime)}")
        if st.st_size <= 0:
            log("xlsx サイズが 0", "ERROR"); ok = False
        if pre_mtime and st.st_mtime <= pre_mtime:
            log("xlsx の mtime が更新されていない（再生成されていない可能性）", "ERROR"); ok = False

        try:
            import openpyxl
            wb = openpyxl.load_workbook(XLSX, read_only=True)
            sheets = list(wb.sheetnames)
            wb.close()
            missing = [s for s in KEY_SHEETS if s not in sheets]
            if missing:
                log(f"主要シート欠落: {missing}", "ERROR"); ok = False
            else:
                log(f"主要シート確認 OK: {KEY_SHEETS}")
        except Exception as e:
            log(f"シート検証に失敗: {e}", "ERROR"); ok = False

        # 正本DB件数（事後）＝不変であること --------------------------------
        counts_after = db_counts()
        log(f"正本DB件数(after) : {counts_after}")
        if counts_after != counts_before:
            log(f"⚠ 正本DB件数が変化した: before={counts_before} after={counts_after}", "ERROR")
            ok = False
        else:
            log("正本DB件数 不変 OK（canonical business table 無変更）")

        if not ok:
            log("事後検証に失敗。バックアップから復旧可能: "
                f"{backup_path}", "ERROR")
            return 3

        log("=== 完了: DB Master を安全に再生成しました ===")
        return 0
    finally:
        log(f"ログ: {log.path}")
        log.close()


if __name__ == "__main__":
    sys.exit(main())
