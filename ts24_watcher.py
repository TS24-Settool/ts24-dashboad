#!/usr/bin/env python3
"""
ts24_watcher.py — TS24 自動監視デーモン
========================================
watchdog で以下のディレクトリを監視し、新規ファイルが追加されたとき
対応する処理スクリプトを自動実行する。

監視対象:
  04_MES/**/        → .MES 追加    → mes_importer.py --mes <file>
  01_REPORTS/**/    → .xlsx 追加   → report_importer.py --file <file>
  07_RESULTS/**/    → .pdf 追加    → pdf_result_extractor.py --file <file>

使用方法:
  python ts24_watcher.py             — デーモンとして起動（Ctrl+C で停止）
  python ts24_watcher.py --install   — macOS LaunchAgent plist を生成・インストール
  python ts24_watcher.py --uninstall — LaunchAgent を削除
  python ts24_watcher.py --status    — LaunchAgent の状態を確認（launchctl）

LaunchAgent インストール後の起動確認:
  launchctl list | grep ts24

依存: watchdog  (pip install watchdog)
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
# DATA_ROOTは常に固定パス（スクリプトをどこから実行しても正しく動作する）
DATA_ROOT    = Path.home() / "Desktop" / "Data TS24 Claude"
# インポートスクリプトは常に05_SCRIPTSフォルダを参照
SCRIPTS_DIR  = DATA_ROOT / "05_SCRIPTS"
LOG_FILE     = Path("/tmp/ts24_watcher.log")
PLIST_LABEL  = "com.ts24.watcher"
PLIST_PATH   = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"

# 監視ディレクトリ定義: (dir, extension, importer_script, extra_args)
WATCH_RULES: list[tuple[Path, str, Path, list[str]]] = [
    (DATA_ROOT / "DATA 2D",    ".MES",  SCRIPTS_DIR / "mes_importer.py",          []),
    (DATA_ROOT / "01_REPORTS", ".xlsx", SCRIPTS_DIR / "report_importer.py",       []),
    (DATA_ROOT / "07_RESULTS", ".pdf",  SCRIPTS_DIR / "pdf_result_extractor.py",  []),
]

# クールダウン: 同一ファイルの多重発火を防ぐ（秒）
_COOLDOWN_S = 10.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# watchdog イベントハンドラ
# ════════════════════════════════════════════════════════════════════

def _build_handler():
    """watchdog が利用可能なときだけ FileSystemEventHandler を構築する。"""
    try:
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        return None

    class _Handler(FileSystemEventHandler):
        def __init__(self, ext: str, script: Path, extra_args: list[str]):
            super().__init__()
            self._ext       = ext.lower()
            self._script    = script
            self._extra     = extra_args
            self._last_seen: dict[str, float] = {}

        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix.lower() != self._ext:
                return
            now = time.monotonic()
            key = str(path)
            if now - self._last_seen.get(key, 0) < _COOLDOWN_S:
                return
            self._last_seen[key] = now
            log.info("新規ファイル検出: %s", path.name)
            self._dispatch(path)

        def _dispatch(self, path: Path):
            # 大きなファイルが書き込み中の場合があるため少し待つ
            time.sleep(2)
            cmd = [sys.executable, str(self._script), "--file", str(path)] + self._extra
            log.info("実行: %s", " ".join(cmd))
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.stdout:
                    for line in result.stdout.splitlines():
                        log.info("  %s", line)
                if result.stderr:
                    for line in result.stderr.splitlines():
                        log.warning("  %s", line)
                if result.returncode != 0:
                    log.error("スクリプト異常終了 (rc=%d): %s",
                              result.returncode, self._script.name)
                else:
                    log.info("完了: %s", self._script.name)
            except subprocess.TimeoutExpired:
                log.error("タイムアウト (300s): %s", self._script.name)
            except Exception as e:
                log.error("実行エラー: %s — %s", self._script.name, e)

    return _Handler


# ════════════════════════════════════════════════════════════════════
# デーモン起動
# ════════════════════════════════════════════════════════════════════

def run_daemon():
    """watchdog オブザーバーを全監視ディレクトリに設定して起動する。"""
    try:
        from watchdog.observers import Observer
    except ImportError:
        log.error("watchdog がインストールされていません: pip install watchdog")
        sys.exit(1)

    HandlerClass = _build_handler()
    if HandlerClass is None:
        log.error("watchdog のインポートに失敗しました")
        sys.exit(1)

    observer = Observer()
    active_watches = []

    for watch_dir, ext, script, extra in WATCH_RULES:
        if not watch_dir.exists():
            log.warning("監視ディレクトリが存在しません（スキップ）: %s", watch_dir)
            continue
        handler = HandlerClass(ext=ext, script=script, extra_args=extra)
        observer.schedule(handler, str(watch_dir), recursive=True)
        active_watches.append((watch_dir, ext))
        log.info("監視開始: %s  (対象: *%s)", watch_dir, ext)

    if not active_watches:
        log.error("有効な監視ディレクトリが1つもありません。終了します。")
        sys.exit(1)

    observer.start()
    log.info("TS24 Watcher 起動完了 — Ctrl+C で停止")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("停止シグナル受信 — Watcher を終了します")
    finally:
        observer.stop()
        observer.join()
        log.info("Watcher 終了")


# ════════════════════════════════════════════════════════════════════
# LaunchAgent 管理
# ════════════════════════════════════════════════════════════════════

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{logfile}</string>

    <key>StandardErrorPath</key>
    <string>{logfile}</string>

    <key>WorkingDirectory</key>
    <string>{workdir}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
"""


def install_launchagent():
    """macOS LaunchAgent plist を生成して ~/Library/LaunchAgents/ に配置する。"""
    if sys.platform != "darwin":
        print("⚠️  LaunchAgent は macOS 専用です。")
        sys.exit(1)

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    python_exec = sys.executable
    plist_content = _PLIST_TEMPLATE.format(
        label   = PLIST_LABEL,
        python  = python_exec,
        script  = str(SCRIPT_DIR / "ts24_watcher.py"),
        logfile = str(LOG_FILE),
        workdir = str(SCRIPT_DIR),
    )
    PLIST_PATH.write_text(plist_content, encoding="utf-8")
    print(f"✅ plist 生成: {PLIST_PATH}")

    # launchctl ロード
    result = subprocess.run(
        ["launchctl", "load", "-w", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"✅ LaunchAgent ロード完了: {PLIST_LABEL}")
        print(f"   ログ: {LOG_FILE}")
        print(f"   確認: launchctl list | grep ts24")
    else:
        print(f"❌ ロード失敗: {result.stderr.strip()}")
        sys.exit(1)


def uninstall_launchagent():
    """LaunchAgent をアンロードして plist を削除する。"""
    if sys.platform != "darwin":
        print("⚠️  LaunchAgent は macOS 専用です。")
        sys.exit(1)

    if PLIST_PATH.exists():
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
        )
        PLIST_PATH.unlink()
        print(f"✅ LaunchAgent 削除完了: {PLIST_LABEL}")
    else:
        print(f"ℹ️  plist が見つかりません: {PLIST_PATH}")


def check_status():
    """launchctl list で状態を確認する。"""
    if sys.platform != "darwin":
        print("⚠️  LaunchAgent は macOS 専用です。")
        return
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True, text=True,
    )
    lines = [l for l in result.stdout.splitlines() if "ts24" in l.lower()]
    if lines:
        print("✅ LaunchAgent 稼働中:")
        for line in lines:
            print(f"   {line}")
    else:
        print("❌ ts24 LaunchAgent が見つかりません（未起動または未インストール）")
    print(f"\nログファイル: {LOG_FILE}")
    if LOG_FILE.exists():
        last = LOG_FILE.read_text(encoding="utf-8").splitlines()[-20:]
        print("── 最後の20行 ──")
        for l in last:
            print(f"  {l}")


# ════════════════════════════════════════════════════════════════════
# エントリーポイント
# ════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="TS24 ファイル監視デーモン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python ts24_watcher.py             デーモン起動
  python ts24_watcher.py --install   macOS LaunchAgent インストール
  python ts24_watcher.py --uninstall LaunchAgent 削除
  python ts24_watcher.py --status    稼働状態確認
        """,
    )
    parser.add_argument("--install",   action="store_true",
                        help="macOS LaunchAgent をインストールして自動起動を有効化")
    parser.add_argument("--uninstall", action="store_true",
                        help="LaunchAgent を削除して自動起動を無効化")
    parser.add_argument("--status",    action="store_true",
                        help="LaunchAgent の稼働状態を確認")
    args = parser.parse_args()

    if args.install:
        install_launchagent()
    elif args.uninstall:
        uninstall_launchagent()
    elif args.status:
        check_status()
    else:
        run_daemon()


if __name__ == "__main__":
    main()
