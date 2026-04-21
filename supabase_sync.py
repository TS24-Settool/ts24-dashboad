#!/usr/bin/env python3
"""
supabase_sync.py — TS24 Supabase → Mac 自動同期スクリプト
============================================================
機能:
  1. Supabase の pending テーブルから未処理データを取得
  2. メール通知を tatsuki1344@gmail.com に送信
  3. 5分ごとに自動チェック（バックグラウンド常駐）

実行方法:
  python3 supabase_sync.py          # 一度だけチェック
  python3 supabase_sync.py --watch  # 5分ごとに継続監視

注意: 承認はダッシュボードの「Approvals」タブから行います
============================================================
"""

import json
import time
import smtplib
import ssl
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "ts24_config.json"
CHECK_INTERVAL = 300  # 5分ごと

# ── Config ────────────────────────────────────────────────────
def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}

# ── Supabase API ──────────────────────────────────────────────
def supabase_request(method: str, url: str, key: str, data: dict = None) -> list:
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "return=representation",
    }
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else []
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
        return []
    except Exception as e:
        print(f"  Error: {e}")
        return []

def fetch_pending(supabase_url: str, service_key: str, table: str) -> list:
    url = f"{supabase_url}/rest/v1/{table}?status=eq.pending&select=*&order=submitted_at.asc"
    return supabase_request("GET", url, service_key)

def count_pending(supabase_url: str, service_key: str, table: str) -> int:
    url = f"{supabase_url}/rest/v1/{table}?status=eq.pending&select=id"
    headers = {
        "apikey":        service_key,
        "Authorization": f"Bearer {service_key}",
        "Prefer":        "count=exact",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return len(data)
    except Exception:
        return 0

# ── Email Notification ────────────────────────────────────────
def send_email(gmail_user: str, gmail_app_password: str,
               to_email: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, to_email, msg.as_string())

def build_email_body(sessions: list, laps: list) -> str:
    lines = [
        "TS24 ダッシュボード — 新しいデータが送信されました",
        "=" * 50,
        f"送信時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    if sessions:
        lines.append(f"📋 セッションレポート: {len(sessions)} 件")
        for s in sessions[:5]:
            lines.append(
                f"  [{s.get('submitted_by','?')}] "
                f"{s.get('session_date','?')} | {s.get('circuit','?')} | "
                f"{s.get('session_type','?')} | Rider: {s.get('rider','?')}"
            )
        if len(sessions) > 5:
            lines.append(f"  ... 他 {len(sessions)-5} 件")

    if laps:
        lines.append("")
        lines.append(f"⏱ ラップタイム: {len(laps)} 件")
        submitters = list(set(l.get("submitted_by","?") for l in laps))
        lines.append(f"  送信者: {', '.join(submitters)}")

    lines += [
        "",
        "=" * 50,
        "承認はダッシュボードの「✅ Approvals」タブから行ってください。",
        f"Dashboard URL: http://localhost:8501",
    ]
    return "\n".join(lines)

# ── Main Sync ─────────────────────────────────────────────────
def run_once() -> bool:
    """一回チェックを実行。新データがあれば True を返す。"""
    cfg = load_config()
    supabase_url = cfg.get("supabase_url", "")
    service_key  = cfg.get("supabase_service_key", "")
    gmail_user   = cfg.get("gmail_user", "")
    gmail_pwd    = cfg.get("gmail_app_password", "")
    notify_email = cfg.get("notification_email", "tatsuki1344@gmail.com")

    if not supabase_url or not service_key or service_key == "PASTE_SERVICE_ROLE_KEY_HERE":
        print("  ⚠️  supabase_service_key が設定されていません。")
        print("     Supabase: Settings > API > service_role キーを")
        print("     ts24_config.json の supabase_service_key に設定してください。")
        return False

    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] Supabase をチェック中...")

    sessions = fetch_pending(supabase_url, service_key, "pending_sessions")
    laps     = fetch_pending(supabase_url, service_key, "pending_lap_times")

    total = len(sessions) + len(laps)
    if total == 0:
        print("  承認待ちデータなし。")
        return False

    print(f"  ✅ 新着: セッション {len(sessions)} 件 / ラップ {len(laps)} 件")

    # メール通知
    if gmail_user and gmail_pwd:
        try:
            subject = f"[TS24] 新しいデータ送信あり（{total}件）"
            body    = build_email_body(sessions, laps)
            send_email(gmail_user, gmail_pwd, notify_email, subject, body)
            print(f"  📧 メール通知送信済み → {notify_email}")
        except Exception as e:
            print(f"  ⚠️  メール送信失敗: {e}")
    else:
        print("  ℹ️  gmail_user / gmail_app_password 未設定のためメール通知をスキップ。")

    return True

def run_watch():
    """5分ごとに継続監視。"""
    print("=" * 50)
    print("  TS24 Supabase 監視デーモン起動")
    print(f"  チェック間隔: {CHECK_INTERVAL // 60} 分")
    print("  停止: Ctrl+C")
    print("=" * 50)
    print()
    try:
        while True:
            run_once()
            print(f"  次回チェック: {CHECK_INTERVAL // 60} 分後")
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("\n監視を停止しました。")

# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    if "--watch" in sys.argv:
        run_watch()
    else:
        run_once()
