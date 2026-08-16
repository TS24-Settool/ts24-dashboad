#!/usr/bin/env python3
"""
event_manifest.py — TS24 Event Control Plane: Event Manifest library (Phase B-1)
=================================================================================
設計: CLAUDE.md §75 / reports/race_weekend_event_control_plane_readiness_20260711.md /
      reports/event_manifest_schema_proposal_20260711.json（schema v1）

役割:
  - 02_DATABASE/event_manifests/<event_key>.json の load / validate / seal（content_hash）
  - DB ミラー event_manifest への register（immutable version）/ activate（exactly-one-active）
  - event_state_ledger への追記（append-only・receipt JSON）
  - extraction_scan.py（--manifest live scan）/ session_extract_staging.py（apply guard）から
    import されて使われる。**このモジュール自身は業務テーブルに一切触れない。**

安全原則:
  - validate は fail-closed: 必須欠落・パターン不一致・キー間矛盾・content_hash 改竄は ManifestError。
  - register: 同一 (event_key, manifest_version) は同 content_hash なら no-op、異なれば拒否
    （locked/registered 後の書換えは新 version のみ）。status='active' の直接登録は不可
    （activate_manifest() の明示操作のみ）。
  - activate: DB の partial unique index + 事前チェックの二重で「active は同時に1件」を強制。
  - ledger: UPDATE/DELETE はトリガで拒否（create_event_control_tables.py）。

CLI（開発・運用補助）:
  python3 event_manifest.py validate <file.json>
  python3 event_manifest.py seal <file.json>                 # content_hash を計算して書込
  python3 event_manifest.py register <file.json> --db <db>
  python3 event_manifest.py activate <event_key> --db <db> [--version N] [--actor NAME]
  python3 event_manifest.py show-active --db <db>
注意: Track B フェーズでは正本DBへの register/activate は別GO（scratch DB のみ）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = ROOT / "02_DATABASE" / "event_manifests"
SCHEMA_VERSION = 1

STATUS_ENUM = ("draft", "approved", "active", "locked", "closed")
FINGERPRINT_ENUM = ("stat", "content")
LEDGER_STATES = (
    "discovered", "registered", "candidate_ready", "staged", "verified",
    "reportable", "finalized",
    "failed", "warning_accepted", "skipped", "superseded", "quarantined",
)
LEDGER_SCOPES = ("event", "session", "outing", "manifest", "source")

EVENT_KEY_RE = re.compile(r"^(\d{8})-(ROUND\d+|TEST\d+)-([A-Z]{2}\d{2})$")
WEEKEND_KEY_RE = re.compile(r"^(\d{8})-(ROUND\d+|TEST\d+)$")
ROUND_RE = re.compile(r"^(ROUND\d+|TEST\d+)$")
RIDER_RE = re.compile(r"^[A-Z]{2}\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_FIELDS = (
    "schema_version", "manifest_version", "event_key", "weekend_key", "date",
    "round", "circuit", "riders", "raw_2d_root", "allowed_sessions", "status",
)
# content_hash 計算から除外するキー（hash 自身とコメント系）
HASH_EXCLUDED_KEYS = ("content_hash",)


class ManifestError(Exception):
    """Manifest validation / enforcement failure（fail-closed 用）"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ───────────────────────── canonical JSON / content hash ─────────────────────
def canonical_payload(manifest: dict) -> str:
    """content_hash 計算用の canonical JSON（hash 対象キーのみ・sort_keys・区切り固定）。
    '_' 始まりのキー（コメント/メモ）と content_hash は hash 対象外。"""
    body = {k: v for k, v in manifest.items()
            if k not in HASH_EXCLUDED_KEYS and not k.startswith("_")}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_content_hash(manifest: dict) -> str:
    return hashlib.sha256(canonical_payload(manifest).encode("utf-8")).hexdigest()


# ───────────────────────── validate / load ────────────────────────────────────
def validate_manifest(manifest: dict, *, verify_hash: bool = True,
                      require_hash: bool = False) -> list[str]:
    """検証エラーのリストを返す（空=合格）。fail-closed 判断は呼び出し側 or load_manifest。"""
    errs: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest is not a JSON object"]
    for f in REQUIRED_FIELDS:
        if f not in manifest or manifest[f] in (None, "", []):
            errs.append(f"required field missing/empty: {f}")
    if errs:
        return errs

    if manifest["schema_version"] != SCHEMA_VERSION:
        errs.append(f"schema_version must be {SCHEMA_VERSION} (got {manifest['schema_version']!r})")
    mv = manifest["manifest_version"]
    if not isinstance(mv, int) or mv < 1:
        errs.append(f"manifest_version must be integer >= 1 (got {mv!r})")

    ek, wk, rnd, date = (manifest["event_key"], manifest["weekend_key"],
                         manifest["round"], manifest["date"])
    m_ek = EVENT_KEY_RE.match(str(ek))
    if not m_ek:
        errs.append(f"event_key pattern mismatch: {ek!r} (expect YYYYMMDD-ROUNDx-RIDER)")
    if not WEEKEND_KEY_RE.match(str(wk)):
        errs.append(f"weekend_key pattern mismatch: {wk!r}")
    if not ROUND_RE.match(str(rnd)):
        errs.append(f"round pattern mismatch: {rnd!r}")
    if not DATE_RE.match(str(date)):
        errs.append(f"date must be ISO YYYY-MM-DD: {date!r}")

    riders = manifest["riders"]
    if (not isinstance(riders, list) or not riders
            or any(not RIDER_RE.match(str(r)) for r in riders)
            or len(set(riders)) != len(riders)):
        errs.append(f"riders must be non-empty unique array of RIDER codes: {riders!r}")

    sessions = manifest["allowed_sessions"]
    if (not isinstance(sessions, list) or not sessions
            or len(set(sessions)) != len(sessions)
            or any(not isinstance(s, str) or not s for s in sessions)):
        errs.append(f"allowed_sessions must be non-empty unique array of strings: {sessions!r}")

    if manifest["status"] not in STATUS_ENUM:
        errs.append(f"status must be one of {STATUS_ENUM}: {manifest['status']!r}")
    fp = manifest.get("fingerprint_policy", "content")
    if fp not in FINGERPRINT_ENUM:
        errs.append(f"fingerprint_policy must be one of {FINGERPRINT_ENUM}: {fp!r}")
    eo = manifest.get("expected_outings")
    if eo is not None and (not isinstance(eo, list) or any(not isinstance(x, str) for x in eo)):
        errs.append(f"expected_outings must be null or array of strings: {eo!r}")

    circuit = str(manifest["circuit"])
    if not circuit or not re.match(r"^[A-Z0-9]+$", circuit):
        errs.append(f"circuit must be canonical upper-case token (TRACK_M key): {circuit!r}")

    # キー間整合（event_key = date+round+rider / weekend_key = date+round / rider ∈ riders）
    if m_ek and WEEKEND_KEY_RE.match(str(wk)):
        d8, ek_round, ek_rider = m_ek.group(1), m_ek.group(2), m_ek.group(3)
        if str(wk) != f"{d8}-{ek_round}":
            errs.append(f"weekend_key {wk!r} != event_key derived {d8}-{ek_round}")
        if ek_round != str(rnd):
            errs.append(f"round {rnd!r} != event_key round {ek_round}")
        if DATE_RE.match(str(date)) and str(date).replace("-", "") != d8:
            errs.append(f"date {date!r} != event_key date {d8}")
        if ek_rider not in [str(r) for r in riders]:
            errs.append(f"event_key rider {ek_rider} not in riders {riders!r}")

    raw_root = str(manifest["raw_2d_root"])
    if not raw_root or raw_root.startswith("/") or ".." in raw_root:
        errs.append(f"raw_2d_root must be a data-root-relative path without '..': {raw_root!r}")
    elif m_ek and Path(raw_root).name != str(ek):
        errs.append(f"raw_2d_root basename {Path(raw_root).name!r} != event_key {ek!r}")

    # content_hash（改竄検出）
    ch = manifest.get("content_hash")
    if ch is not None:
        if not SHA256_RE.match(str(ch)):
            errs.append(f"content_hash must be 64-hex sha256: {ch!r}")
        elif verify_hash:
            expect = compute_content_hash(manifest)
            if ch != expect:
                errs.append(f"content_hash MISMATCH (tampered or stale): "
                            f"declared={ch} computed={expect}")
    elif require_hash:
        errs.append("content_hash is required (seal the manifest first)")
    return errs


def load_manifest(path: Path | str, *, verify_hash: bool = True,
                  require_hash: bool = True) -> dict:
    """JSON ファイルを読み、検証合格した manifest dict を返す。不合格は ManifestError。"""
    p = Path(path)
    if not p.exists():
        raise ManifestError(f"manifest file not found: {p}")
    try:
        manifest = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ManifestError(f"manifest JSON parse error: {p}: {e}") from e
    errs = validate_manifest(manifest, verify_hash=verify_hash, require_hash=require_hash)
    if errs:
        raise ManifestError(f"manifest validation failed: {p}:\n  - " + "\n  - ".join(errs))
    manifest["_source_path"] = str(p)
    return manifest


def seal_manifest_file(path: Path | str) -> str:
    """content_hash を計算して JSON に書き戻す（作成/改版時の運用補助）。返り値=hash。"""
    p = Path(path)
    manifest = json.loads(p.read_text(encoding="utf-8"))
    errs = validate_manifest(manifest, verify_hash=False, require_hash=False)
    if errs:
        raise ManifestError(f"cannot seal invalid manifest: {p}:\n  - " + "\n  - ".join(errs))
    manifest["content_hash"] = compute_content_hash(manifest)
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest["content_hash"]


# ───────────────────────── DB mirror（enforcement） ──────────────────────────
def tables_exist(conn: sqlite3.Connection) -> bool:
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('event_manifest','event_state_ledger')")}
    return have == {"event_manifest", "event_state_ledger"}


def register_manifest(conn: sqlite3.Connection, manifest: dict,
                      actor: str = "claude_code") -> int:
    """manifest を DB ミラーへ登録。immutable version:
    同一 (event_key, manifest_version) 既存 → 同 hash なら no-op（既存 id 返却）、
    異 hash なら ManifestError（書換えは新 version のみ）。status='active' 直接登録は拒否。"""
    errs = validate_manifest(manifest, verify_hash=True, require_hash=True)
    if errs:
        raise ManifestError("register refused (invalid manifest):\n  - " + "\n  - ".join(errs))
    if not tables_exist(conn):
        raise ManifestError("event_manifest/event_state_ledger tables missing "
                            "(run create_event_control_tables.py first)")
    status = manifest["status"]
    if status == "active":
        raise ManifestError("register refused: status='active' cannot be registered directly; "
                            "register as 'approved' then call activate_manifest()")
    ek, mv = manifest["event_key"], manifest["manifest_version"]
    row = conn.execute(
        "SELECT manifest_id, content_hash FROM event_manifest "
        "WHERE event_key=? AND manifest_version=?", (ek, mv)).fetchone()
    if row is not None:
        if row[1] == manifest["content_hash"]:
            return int(row[0])  # 冪等 no-op
        raise ManifestError(
            f"register refused: (event_key={ek}, manifest_version={mv}) already registered "
            f"with different content_hash (existing={row[1]}, new={manifest['content_hash']}). "
            f"Content changes require a NEW manifest_version.")
    cur = conn.execute(
        """INSERT INTO event_manifest
           (event_key, weekend_key, manifest_version, schema_version, date, round, circuit,
            riders_json, raw_2d_root, allowed_sessions_json, status, fingerprint_policy,
            expected_outings_json, content_hash, approved_by, approved_at, activated_at,
            source_json_path, raw_json, imported_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ek, manifest["weekend_key"], mv, manifest["schema_version"], manifest["date"],
         manifest["round"], manifest["circuit"], json.dumps(manifest["riders"]),
         manifest["raw_2d_root"], json.dumps(manifest["allowed_sessions"]), status,
         manifest.get("fingerprint_policy", "content"),
         json.dumps(manifest["expected_outings"]) if manifest.get("expected_outings") else None,
         manifest["content_hash"], manifest.get("approved_by"), manifest.get("approved_at"),
         None, manifest.get("_source_path"),
         canonical_payload(manifest), now_iso()))
    mid = int(cur.lastrowid)
    append_ledger(conn, ek, scope="manifest", scope_id=f"v{mv}", state="registered",
                  reason=f"manifest registered (status={status})", actor=actor,
                  manifest_version=mv, manifest_content_hash=manifest["content_hash"])
    conn.commit()
    return mid


def activate_manifest(conn: sqlite3.Connection, event_key: str,
                      manifest_version: int | None = None,
                      actor: str = "tatsuki") -> dict:
    """指定 manifest を active 化。exactly-one-active を事前チェック + partial unique index の
    二重で強制。対象は status in (approved, locked) のみ（draft/closed は拒否）。"""
    if not tables_exist(conn):
        raise ManifestError("event control tables missing")
    if manifest_version is None:
        row = conn.execute(
            "SELECT MAX(manifest_version) FROM event_manifest WHERE event_key=?",
            (event_key,)).fetchone()
        if row is None or row[0] is None:
            raise ManifestError(f"no registered manifest for event_key={event_key}")
        manifest_version = int(row[0])
    target = conn.execute(
        "SELECT manifest_id, status, content_hash FROM event_manifest "
        "WHERE event_key=? AND manifest_version=?", (event_key, manifest_version)).fetchone()
    if target is None:
        raise ManifestError(f"manifest not registered: {event_key} v{manifest_version}")
    mid, status, chash = target
    if status == "active":
        return get_active_manifest(conn)          # 冪等
    if status not in ("approved", "locked"):
        raise ManifestError(f"activate refused: status={status!r} (need 'approved'/'locked')")
    actives = conn.execute(
        "SELECT event_key, manifest_version FROM event_manifest WHERE status='active'").fetchall()
    if actives:
        raise ManifestError(
            f"activate refused: another manifest is already active: "
            f"{[(r[0], r[1]) for r in actives]}. Close/lock it first (exactly-one-active).")
    try:
        conn.execute("UPDATE event_manifest SET status='active', activated_at=? "
                     "WHERE manifest_id=?", (now_iso(), mid))
    except sqlite3.IntegrityError as e:
        raise ManifestError(f"activate refused by DB constraint (exactly-one-active): {e}") from e
    append_ledger(conn, event_key, scope="manifest", scope_id=f"v{manifest_version}",
                  state="registered", prev_state=status,
                  reason="manifest activated (exactly-one-active enforced)", actor=actor,
                  manifest_version=manifest_version, manifest_content_hash=chash)
    conn.commit()
    return get_active_manifest(conn)


def set_manifest_status(conn: sqlite3.Connection, event_key: str, manifest_version: int,
                        new_status: str, actor: str = "tatsuki", reason: str = "") -> None:
    """前進のみの status 遷移（draft→approved→active→locked→closed）。active 化は
    activate_manifest() 経由のみ。後退（closed→active 等）は拒否。"""
    if new_status not in STATUS_ENUM:
        raise ManifestError(f"unknown status {new_status!r}")
    if new_status == "active":
        raise ManifestError("use activate_manifest() to activate")
    row = conn.execute("SELECT manifest_id, status, content_hash FROM event_manifest "
                       "WHERE event_key=? AND manifest_version=?",
                       (event_key, manifest_version)).fetchone()
    if row is None:
        raise ManifestError(f"manifest not registered: {event_key} v{manifest_version}")
    mid, cur_status, chash = row
    if STATUS_ENUM.index(new_status) <= STATUS_ENUM.index(cur_status):
        raise ManifestError(f"status transition refused: {cur_status} -> {new_status} "
                            f"(forward-only)")
    conn.execute("UPDATE event_manifest SET status=? WHERE manifest_id=?", (new_status, mid))
    append_ledger(conn, event_key, scope="manifest", scope_id=f"v{manifest_version}",
                  state="registered", prev_state=cur_status,
                  reason=reason or f"status -> {new_status}", actor=actor,
                  manifest_version=manifest_version, manifest_content_hash=chash)
    conn.commit()


def _row_to_manifest(row: sqlite3.Row | tuple, cols: list[str]) -> dict:
    d = dict(zip(cols, row))
    d["riders"] = json.loads(d.pop("riders_json"))
    d["allowed_sessions"] = json.loads(d.pop("allowed_sessions_json"))
    eo = d.pop("expected_outings_json")
    d["expected_outings"] = json.loads(eo) if eo else None
    return d


def get_active_manifest(conn: sqlite3.Connection) -> dict:
    """active manifest を厳格に1件返す。0件/複数件は ManifestError（fail-closed）。
    さらに raw_json から content_hash を再計算し、DB 行の改竄も検出する。"""
    if not tables_exist(conn):
        raise ManifestError("event control tables missing (no active manifest)")
    cols = ["manifest_id", "event_key", "weekend_key", "manifest_version", "schema_version",
            "date", "round", "circuit", "riders_json", "raw_2d_root", "allowed_sessions_json",
            "status", "fingerprint_policy", "expected_outings_json", "content_hash",
            "approved_by", "approved_at", "activated_at", "source_json_path", "raw_json",
            "imported_at"]
    rows = conn.execute(
        f"SELECT {','.join(cols)} FROM event_manifest WHERE status='active'").fetchall()
    if len(rows) == 0:
        raise ManifestError("no active event manifest (fail-closed: apply/live-scan refused)")
    if len(rows) > 1:
        keys = [r[1] for r in rows]
        raise ManifestError(f"multiple active manifests (DB invariant broken): {keys}")
    m = _row_to_manifest(rows[0], cols)
    recomputed = hashlib.sha256(m["raw_json"].encode("utf-8")).hexdigest()
    if recomputed != m["content_hash"]:
        raise ManifestError(
            f"active manifest content_hash mismatch in DB mirror "
            f"(stored={m['content_hash']}, recomputed={recomputed}) — tampered? fail-closed.")
    # 列レベル改竄検出: hash 対象の raw_json と DB ミラー列の主要フィールドを突合
    try:
        src = json.loads(m["raw_json"])
    except Exception as e:
        raise ManifestError(f"active manifest raw_json unparsable (tampered?): {e}") from e
    for field, col_val in (("event_key", m["event_key"]), ("weekend_key", m["weekend_key"]),
                           ("manifest_version", m["manifest_version"]), ("round", m["round"]),
                           ("circuit", m["circuit"]), ("raw_2d_root", m["raw_2d_root"]),
                           ("riders", m["riders"]), ("allowed_sessions", m["allowed_sessions"])):
        if src.get(field) != col_val:
            raise ManifestError(
                f"active manifest DB mirror column {field!r} != hashed raw_json "
                f"(column={col_val!r}, raw_json={src.get(field)!r}) — tampered? fail-closed.")
    return m


def get_active_manifest_or_none(conn: sqlite3.Connection):
    """テーブル未作成 or active 0件 → None（後方互換の分岐用）。複数 active は例外のまま
    （fail-closed: 呼び出し側は続行してはならない）。"""
    if not tables_exist(conn):
        return None
    n = conn.execute("SELECT COUNT(*) FROM event_manifest WHERE status='active'").fetchone()[0]
    if n == 0:
        return None
    return get_active_manifest(conn)


# ───────────────────────── ledger（append-only） ─────────────────────────────
def append_ledger(conn: sqlite3.Connection, event_key: str, *, scope: str, scope_id: str | None,
                  state: str, reason: str, actor: str, prev_state: str | None = None,
                  analysis_run_id: str | None = None, manifest_version: int | None = None,
                  manifest_content_hash: str | None = None, receipt: dict | None = None) -> int:
    if scope not in LEDGER_SCOPES:
        raise ManifestError(f"ledger scope invalid: {scope!r}")
    if state not in LEDGER_STATES:
        raise ManifestError(f"ledger state invalid: {state!r}")
    if not reason:
        raise ManifestError("ledger reason is required")
    cur = conn.execute(
        """INSERT INTO event_state_ledger
           (event_key, scope, scope_id, state, prev_state, reason, actor, analysis_run_id,
            manifest_version, manifest_content_hash, receipt_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_key, scope, scope_id, state, prev_state, reason, actor, analysis_run_id,
         manifest_version, manifest_content_hash,
         json.dumps(receipt, ensure_ascii=False, sort_keys=True) if receipt else None,
         now_iso()))
    return int(cur.lastrowid)


def ledger_append_durable(db_path: Path | str, event_key: str, **kw) -> int | None:
    """短命コネクションで即 commit する ledger 追記（apply の耐久 receipt 用）。
    テーブル未作成なら None（後方互換・書かない）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        if not tables_exist(conn):
            return None
        eid = append_ledger(conn, event_key, **kw)
        conn.commit()
        return eid
    finally:
        conn.close()


# ───────────────────────── CLI ────────────────────────────────────────────────
def _cli() -> int:
    ap = argparse.ArgumentParser(description="TS24 Event Manifest 管理（validate/seal/register/activate）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate");     p.add_argument("file", type=Path)
    p = sub.add_parser("seal");         p.add_argument("file", type=Path)
    p = sub.add_parser("register");     p.add_argument("file", type=Path)
    p.add_argument("--db", type=Path, required=True); p.add_argument("--actor", default="claude_code")
    p = sub.add_parser("activate");     p.add_argument("event_key")
    p.add_argument("--db", type=Path, required=True); p.add_argument("--version", type=int, default=None)
    p.add_argument("--actor", default="tatsuki")
    p = sub.add_parser("show-active");  p.add_argument("--db", type=Path, required=True)
    args = ap.parse_args()

    try:
        if args.cmd == "validate":
            m = load_manifest(args.file, verify_hash=True, require_hash=False)
            print(f"[OK] valid manifest: {m['event_key']} v{m['manifest_version']} "
                  f"status={m['status']} content_hash={m.get('content_hash')}")
        elif args.cmd == "seal":
            h = seal_manifest_file(args.file)
            print(f"[OK] sealed: content_hash={h}")
        elif args.cmd == "register":
            m = load_manifest(args.file)
            conn = sqlite3.connect(str(args.db))
            mid = register_manifest(conn, m, actor=args.actor)
            conn.close()
            print(f"[OK] registered: manifest_id={mid} {m['event_key']} v{m['manifest_version']}")
        elif args.cmd == "activate":
            conn = sqlite3.connect(str(args.db))
            m = activate_manifest(conn, args.event_key, args.version, actor=args.actor)
            conn.close()
            print(f"[OK] active: {m['event_key']} v{m['manifest_version']} "
                  f"content_hash={m['content_hash']}")
        elif args.cmd == "show-active":
            conn = sqlite3.connect(str(args.db))
            m = get_active_manifest(conn)
            conn.close()
            print(json.dumps({k: v for k, v in m.items() if k != "raw_json"},
                             ensure_ascii=False, indent=2))
        return 0
    except ManifestError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(_cli())
