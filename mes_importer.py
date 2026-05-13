#!/usr/bin/env python3
"""
mes_importer.py — MES処理オーケストレーター
============================================
新しいMESファイルを受け取り、既存処理スクリプトを順次呼び出す:
  1. lap_suspension_stats.py  — ラップ統計生成 + DB/Excel書き込み

ts24_watcher.py から自動呼び出しされるほか、手動実行も可能。

使用方法:
  python mes_importer.py --mes /path/to/file.MES   ← 単一ファイル
  python mes_importer.py --dir /path/to/mes/dir/   ← フォルダ内の全MES
  python mes_importer.py --all                     ← 04_MES/ 以下を全再処理
  python mes_importer.py --dry-run --all           ← 書き込みなしで確認
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT  = SCRIPT_DIR.parent
MES_ROOT   = DATA_ROOT / "04_MES"
LOG_FILE   = SCRIPT_DIR / "watcher.log"

LAP_STATS_SCRIPT = SCRIPT_DIR / "lap_suspension_stats.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MES] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def run_lap_stats(dry_run: bool = False) -> bool:
    """lap_suspension_stats.py を実行してDB/JSONを更新する。"""
    cmd = [sys.executable, str(LAP_STATS_SCRIPT)]
    if dry_run:
        cmd.append("--dry-run")
    log.info("実行: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.stdout:
            for line in result.stdout.splitlines():
                log.info("  [lap_stats] %s", line)
        if result.stderr:
            for line in result.stderr.splitlines():
                log.warning("  [lap_stats] %s", line)
        if result.returncode != 0:
            log.error("lap_suspension_stats.py が異常終了 (rc=%d)", result.returncode)
            return False
        log.info("lap_suspension_stats.py 完了")
        return True
    except subprocess.TimeoutExpired:
        log.error("lap_suspension_stats.py タイムアウト (600s)")
        return False
    except Exception as e:
        log.error("lap_suspension_stats.py 実行エラー: %s", e)
        return False


def import_single(mes_path: Path, dry_run: bool = False) -> bool:
    """単一MESファイルを処理する。lap_stats は全MESを再処理するため常に全体実行。"""
    if not mes_path.exists():
        log.error("ファイルが見つかりません: %s", mes_path)
        return False
    if mes_path.suffix.upper() != ".MES":
        log.error("MESファイルではありません: %s", mes_path)
        return False
    log.info("MESインポート開始: %s", mes_path.name)
    ok = run_lap_stats(dry_run=dry_run)
    if ok:
        log.info("✅ %s 処理完了 (%s)", mes_path.name,
                 datetime.now().strftime("%H:%M:%S"))
    return ok


def import_dir(mes_dir: Path, dry_run: bool = False) -> int:
    """フォルダ内の全MESファイルを処理する（実際はlap_statsが全体再処理）。"""
    if not mes_dir.exists():
        log.error("フォルダが見つかりません: %s", mes_dir)
        return 0
    mes_files = list(mes_dir.rglob("*.MES")) + list(mes_dir.rglob("*.mes"))
    if not mes_files:
        log.warning("MESファイルが見つかりません: %s", mes_dir)
        return 0
    log.info("%d 個のMESファイルを検出: %s", len(mes_files), mes_dir)
    ok = run_lap_stats(dry_run=dry_run)
    return len(mes_files) if ok else 0


def import_all(dry_run: bool = False) -> int:
    """04_MES/ 以下を全再処理する。"""
    if not MES_ROOT.exists():
        log.error("04_MES/ フォルダが見つかりません: %s", MES_ROOT)
        return 0
    mes_files = list(MES_ROOT.rglob("*.MES")) + list(MES_ROOT.rglob("*.mes"))
    log.info("全MES再処理: %d ファイル in %s", len(mes_files), MES_ROOT)
    ok = run_lap_stats(dry_run=dry_run)
    return len(mes_files) if ok else 0


def main():
    parser = argparse.ArgumentParser(description="MES処理オーケストレーター")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mes",  type=Path, help="単一MESファイルのパス")
    group.add_argument("--dir",  type=Path, help="MESフォルダのパス")
    group.add_argument("--all",  action="store_true", help="04_MES/ 以下を全再処理")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB/Excel書き込みなしで確認のみ")
    args = parser.parse_args()

    if args.mes:
        success = import_single(args.mes, dry_run=args.dry_run)
        sys.exit(0 if success else 1)
    elif args.dir:
        count = import_dir(args.dir, dry_run=args.dry_run)
        sys.exit(0 if count > 0 else 1)
    else:  # --all
        count = import_all(dry_run=args.dry_run)
        sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()
