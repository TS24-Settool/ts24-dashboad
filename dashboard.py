#!/usr/bin/env python3
"""
dashboard.py — TS24 SET-UP TOOL
====================================================
Streamlit dashboard — Power BI style, minimal design.

Run:
  /Users/ts24/Library/Python/3.9/bin/streamlit run dashboard.py
====================================================
"""

import sqlite3
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import streamlit as st
import urllib.request
import urllib.error
import json
import hashlib

# ── Layered architecture imports ──────────────────────────────────
# domain/   — pure analysis logic (no Streamlit)
# services/ — data loading, external APIs (no Streamlit)
# components/ — chart helpers (no Streamlit)
from domain.lap_analysis import (
    normalize_circuit     as _dyn_norm_circuit,   # backward-compat alias
    normalize_session     as _dyn_norm_session,   # backward-compat alias
    classify_fast_slow_tiers,
    build_lap_sus_map,
    build_lap_time_map,
    join_sus_and_laptimes,
)
from services.data_loader import (
    sql_to_df               as _sql_to_df,          # backward-compat alias
    coerce_dynamics_numerics as _coerce_dyn_numerics, # backward-compat alias
    load_dynamics_from_excel,
    load_dynamics_from_json,
    load_lap_suspension_from_excel,
    load_lap_suspension_from_sqlite,
    load_lap_suspension_from_json,
)
from services.claude_client import call_claude        # replaces local def
from services.memory_service import (
    load_race_memory    as _ms_load_race_memory,
    save_race_memory    as _ms_save_race_memory,
    build_memory_context,                             # replaces local def
)
from services.supabase_client import (
    supa_request        as _supa_req_base,
    fetch_table_paginated,
    supa_upsert         as _supa_upsert_base,
    supa_delete_row     as _supa_delete_row_base,
)
from components.charts import (
    apply_chart_layout  as chart_layout,             # backward-compat alias
    DA77_COLOR, JA52_COLOR, PHASE_COLORS, PHASE_LABELS, CHART_FONT,
)

# ── Path ─────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "ts24_config.json"
# /tmp fallback: writable on Streamlit Cloud (where repo dir is read-only)
_TMP_CONFIG    = Path("/tmp/ts24_dashboard_config.json")
MEMORY_FILE    = SCRIPT_DIR / "race_memory.json"
_TMP_MEMORY    = Path("/tmp/ts24_race_memory.json")

def find_db():
    for base in [SCRIPT_DIR, SCRIPT_DIR.parent]:
        db = base / "02_DATABASE" / "ts24_setup.db"
        if db.exists():
            return db
    return None  # Returns None in Streamlit Cloud / no-SQLite environments

def load_config() -> dict:
    cfg = {}
    # Step 1: st.secrets — API keys, Supabase URL (Streamlit Cloud)
    try:
        if hasattr(st, 'secrets') and len(st.secrets) > 0:
            cfg = dict(st.secrets)
            if 'users' in cfg and hasattr(cfg['users'], 'items'):
                cfg['users'] = {k: dict(v) for k, v in cfg['users'].items()}
    except Exception:
        pass
    # Step 2: Merge from JSON files — repo file first, then /tmp overlay
    # /tmp has the most recent UI changes on Streamlit Cloud
    for path in [CONFIG_FILE, _TMP_CONFIG]:
        if path.exists():
            try:
                file_cfg = json.loads(path.read_text())
                if 'users' in file_cfg:
                    merged = dict(cfg.get('users', {}))
                    merged.update(file_cfg['users'])
                    cfg['users'] = merged
                for k, v in file_cfg.items():
                    if k != 'users':
                        cfg[k] = v
            except Exception:
                pass
    return cfg

def save_config(data: dict):
    """Write config; try repo path first, fall back to /tmp (Streamlit Cloud)."""
    for path in [CONFIG_FILE, _TMP_CONFIG]:
        try:
            path.write_text(json.dumps(data, indent=2))
            return  # success — stop after first writable path
        except Exception:
            continue

# ── Auth helpers ──────────────────────────────────
def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.strip().encode()).hexdigest()

def _get_user_field(username: str, field: str, default=None):
    """Get a specific field from user data (supports old and new format)."""
    users = get_users()
    user_data = users.get(username)
    if user_data is None:
        return default
    if isinstance(user_data, dict):
        return user_data.get(field, default)
    # Legacy format (hash string only)
    if field == "password":
        return user_data
    if field == "role":
        return "admin" if username == "ts24" else "engineer"
    return default

def get_user_role(username: str) -> str:
    """admin / viewer / engineer"""
    return _get_user_field(username, "role", "engineer")

def get_user_rider(username: str):
    """Rider assigned to this user (DA77/JA52/None)."""
    return _get_user_field(username, "rider", None)

# ── Supabase user helpers (persistent storage) ────
def _supa_creds() -> tuple:
    cfg = load_config()
    return cfg.get("supabase_url", ""), cfg.get("supabase_service_key", "")

def _supa_users_available() -> bool:
    url, key = _supa_creds()
    return bool(url and key and key != "PASTE_SERVICE_ROLE_KEY_HERE")

def _supa_get_users():
    """Fetch users from Supabase dashboard_users table. Returns dict or None on failure."""
    url, key = _supa_creds()
    if not url or not key:
        return None
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    req = urllib.request.Request(f"{url}/rest/v1/dashboard_users?select=*",
                                 headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
            if isinstance(rows, list):
                return {
                    row["username"]: {
                        "password": row["password_hash"],
                        "role":     row.get("role", "engineer"),
                        "rider":    row.get("rider"),
                    }
                    for row in rows
                }
    except Exception:
        pass
    return None

def _supa_upsert_user(username, password_hash, role, rider):
    url, key = _supa_creds()
    if not url or not key:
        return False
    return _supa_upsert_base(
        "dashboard_users",
        {"username": username, "password_hash": password_hash, "role": role, "rider": rider},
        key, url,
    )

def _supa_delete_user(username):
    url, key = _supa_creds()
    if not url or not key:
        return False
    return _supa_delete_row_base("dashboard_users", f"username=eq.{username}", key, url)

def get_users() -> dict:
    """Return {username: user_data} dict — Supabase + JSON merged."""
    order_map = {"admin": 0, "engineer": 1, "viewer": 2}

    def _merge(base: dict, extra: dict) -> dict:
        """Merge extra into base; higher privilege wins on key collision."""
        result = dict(base)
        for uname, udata in extra.items():
            key = uname.lower()
            if key not in result:
                result[key] = udata
            else:
                # Keep more-privileged role
                existing_role = result[key].get("role", "engineer") if isinstance(result[key], dict) else "engineer"
                new_role      = udata.get("role", "engineer")       if isinstance(udata, dict)       else "engineer"
                if order_map.get(new_role, 9) < order_map.get(existing_role, 9):
                    result[key] = udata
        return result

    supa_users = {}
    if _supa_users_available():
        fetched = _supa_get_users()
        if fetched is not None:
            supa_users = {k.lower(): v for k, v in fetched.items()}

    # JSON config (local or /tmp on Streamlit Cloud)
    cfg = load_config()
    json_users_raw = cfg.get("users", {})
    json_users = {}
    for uname, udata in json_users_raw.items():
        json_users[uname.lower()] = udata

    # Merge: Supabase takes priority, JSON fills gaps
    merged = _merge(supa_users, json_users)

    if not merged:
        # Bootstrap default admin
        default = {"ts24": {"password": _hash("Tatsuki1344"),
                            "role": "admin", "rider": None}}
        cfg["users"] = default
        save_config(cfg)
        # Push to Supabase too
        if _supa_users_available():
            _supa_upsert_user("ts24", _hash("Tatsuki1344"), "admin", None)
        return default

    # If Supabase was empty, migrate JSON users up to Supabase
    if not supa_users and json_users and _supa_users_available():
        for uname, udata in json_users.items():
            if isinstance(udata, dict):
                _supa_upsert_user(uname, udata.get("password", ""),
                                  udata.get("role", "engineer"), udata.get("rider"))

    return merged

def check_login(username: str, password: str) -> bool:
    users = get_users()
    udata = users.get(username.strip().lower())
    if udata is None:
        return False
    stored = udata.get("password") if isinstance(udata, dict) else udata
    return stored == _hash(password)

def add_user(username: str, password: str, role: str = "engineer", rider: str = None):
    uname = username.strip().lower()
    phash = _hash(password)
    # 1) Supabase (preferred — persistent)
    supa_ok = False
    if _supa_users_available():
        supa_ok = _supa_upsert_user(uname, phash, role, rider)
    # 2) Always write to JSON as well (ensures data survives even if Supabase sync fails)
    cfg   = load_config()
    users = cfg.get("users", {})
    users[uname] = {"password": phash, "role": role, "rider": rider}
    cfg["users"] = users
    save_config(cfg)

def delete_user(username: str):
    uname = username.strip().lower()
    # 1) Supabase
    if _supa_users_available():
        _supa_delete_user(uname)
    # 2) JSON fallback (also clean up local copy)
    cfg = load_config()
    users = cfg.get("users", {})
    users.pop(uname, None)
    cfg["users"] = users
    save_config(cfg)

# ── Supabase helpers ──────────────────────────────
# Low-level supa_request imported from services.supabase_client (as _supa_req_base).
# Thin wrappers below keep the original names used throughout dashboard.py.

def _supa_req(method: str, url: str, key: str, data: dict = None):
    return _supa_req_base(method, url, key, data)

def supa_insert(table: str, data: dict, anon_key: str, supabase_url: str) -> bool:
    url    = f"{supabase_url}/rest/v1/{table}"
    result = _supa_req_base("POST", url, anon_key, data)
    return isinstance(result, list) and len(result) > 0 or isinstance(result, dict)

def supa_fetch(table: str, service_key: str, supabase_url: str,
               filters: str = "status=eq.pending") -> list:
    url    = f"{supabase_url}/rest/v1/{table}?{filters}&select=*&order=submitted_at.asc"
    result = _supa_req_base("GET", url, service_key)
    return result if isinstance(result, list) else []

def supa_update_status(table: str, record_id: int, status: str,
                       service_key: str, supabase_url: str):
    url = f"{supabase_url}/rest/v1/{table}?id=eq.{record_id}"
    _supa_req_base("PATCH", url, service_key, {"status": status})

# ── Login gate — must pass before any content ─────
def login_page():
    st.set_page_config(
        page_title="TS24 Dashboard — Login",
        page_icon="🏍",
        layout="centered",
    )
    st.markdown("""
    <style>
    html,body,[class*="css"],.stApp{background:#0F1923!important;color:#FFFFFF!important;}
    div[data-testid="stForm"]{background:#1A2533;border-radius:12px;padding:32px 40px;
        border:1px solid #2C3E50;max-width:420px;margin:60px auto;}
    input{background:#0F1923!important;color:#FFFFFF!important;border:1px solid #2C3E50!important;}
    #MainMenu,footer,header{visibility:hidden;}
    @media (max-width:480px){
        div[data-testid="stForm"]{padding:24px 16px!important;margin:20px 12px!important;}
    }
    </style>""", unsafe_allow_html=True)

    st.markdown("<h2 style='text-align:center;color:#0078D4;margin-bottom:4px'>🏍 TS24 Dashboard</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#7F8C8D;margin-bottom:32px'>MotoGP Performance Analysis</p>", unsafe_allow_html=True)

    with st.form("login_form"):
        username = st.text_input("Username", placeholder="Enter username")
        password = st.text_input("Password", type="password", placeholder="Enter password")
        submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

    if submitted:
        if check_login(username, password):
            st.session_state["authenticated"] = True
            st.session_state["current_user"]  = username.strip()
            st.rerun()
        else:
            st.error("Invalid username or password.")

# ── Auth gate ─────────────────────────────────────
if not st.session_state.get("authenticated"):
    login_page()
    st.stop()

DB_PATH = find_db()  # None in Supabase-only environments — OK

# ── Data loading ──────────────────────────────────
# _sql_to_df imported from services.data_loader (alias set above)

def _load_sqlite():
    """Load data from local SQLite (fallback)."""
    try:
        db = find_db()
        conn = sqlite3.connect(str(db))
        sessions = _sql_to_df(conn, "SELECT * FROM sessions ORDER BY session_date")
        tags     = _sql_to_df(conn, "SELECT * FROM session_tags")
        try:
            results = _sql_to_df(conn, "SELECT * FROM race_results ORDER BY round_no, session_type, rider_id")
            sectors = _sql_to_df(conn, "SELECT * FROM sector_results ORDER BY round_id, session_type, rider_id, sector")
        except Exception:
            results = pd.DataFrame()
            sectors = pd.DataFrame()
        try:
            laps = _sql_to_df(conn, "SELECT * FROM lap_times ORDER BY round_id, session_type, rider_num, lap_no")
        except Exception:
            laps = pd.DataFrame()
        conn.close()
        return sessions, tags, results, sectors, laps
    except Exception:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty

def _supa_to_df(table: str, svc_key: str, supa_url: str,
                order: str = "", where: str = "") -> pd.DataFrame:
    """Thin wrapper — delegates to services.supabase_client.fetch_table_paginated."""
    return fetch_table_paginated(table, svc_key, supa_url, order=order, where=where)

@st.cache_data(ttl=60)
def load_data():
    cfg      = load_config()
    supa_url = cfg.get("supabase_url", "")
    svc_key  = cfg.get("supabase_service_key", "")

    # If Supabase is configured, fetch from cloud
    if supa_url and svc_key and svc_key != "PASTE_SERVICE_ROLE_KEY_HERE":
        try:
            sessions = _supa_to_df("sessions",       svc_key, supa_url, order="session_date")
            tags     = _supa_to_df("session_tags",   svc_key, supa_url)
            results  = _supa_to_df("race_results",   svc_key, supa_url, order="round_no,session_type,rider_id")
            sectors  = _supa_to_df("sector_results", svc_key, supa_url)
            # lap_times: 全ライダー取得（Race Paceページのコンペティター比較に必要）
            laps     = _supa_to_df("lap_times", svc_key, supa_url,
                                   order="round_id,session_type,rider_num,lap_no")
            return sessions, tags, results, sectors, laps
        except Exception:
            pass  # Fallback to SQLite

    # Fallback: local SQLite
    return _load_sqlite()

def _scope_label(scope: str) -> str:
    return {
        "COMPANY": "Company",
        "TS24_PRIVATE": "TS24 Private",
        "ALL": "All",
    }.get(scope, scope)

def _scope_count(df: pd.DataFrame, scope: str) -> int:
    if df.empty or "data_scope" not in df.columns:
        return 0
    return int(df["data_scope"].fillna("TS24_PRIVATE").eq(scope).sum())

def _apply_data_scope(df: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "ALL" or df.empty or "data_scope" not in df.columns:
        return df.copy()
    return df[df["data_scope"].fillna("TS24_PRIVATE").eq(scope)].copy()

def _collect_filter_riders(sessions_df: pd.DataFrame) -> list:
    """Sidebar rider filter is based only on report/session riders.

    Official PDF race results and lap-time sheets contain the whole field; those
    competitors must not leak into the report rider filter.
    """
    riders = set()
    if not sessions_df.empty and "rider" in sessions_df.columns:
        riders.update(str(v) for v in sessions_df["rider"].dropna().unique() if str(v).strip())
    return ["All"] + sorted(riders)

def _rider_num_from_code(rider) -> int:
    digits = "".join(ch for ch in str(rider) if ch.isdigit())
    return int(digits) if digits else None

def _rider_num_to_code_map(rider_codes: list) -> dict:
    out = {}
    for rider in rider_codes:
        num = _rider_num_from_code(rider)
        if num is not None:
            out[num] = str(rider)
    return out

def _filter_race_results_to_report_riders(df: pd.DataFrame, rider_codes: list) -> pd.DataFrame:
    """Keep official result rows only for riders present in the selected report scope."""
    if df is None or df.empty or not rider_codes:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    codes = {str(r) for r in rider_codes}
    nums = set(_rider_num_to_code_map(rider_codes).keys())
    mask = pd.Series(False, index=out.index)
    if "rider_id" in out.columns:
        mask = mask | out["rider_id"].astype(str).isin(codes)
    if "rider" in out.columns:
        mask = mask | out["rider"].astype(str).isin(codes)
    rider_no_col = "rider_num" if "rider_num" in out.columns else ("rider_no" if "rider_no" in out.columns else None)
    if rider_no_col and nums:
        rider_num = pd.to_numeric(out[rider_no_col], errors="coerce")
        mask = mask | rider_num.isin(nums)
    out = out[mask].copy()
    if not out.empty and rider_no_col:
        num_to_code = _rider_num_to_code_map(rider_codes)
        mapped = pd.to_numeric(out[rider_no_col], errors="coerce").map(num_to_code)
        if "rider_id" in out.columns:
            out["rider_id"] = mapped.fillna(out["rider_id"].astype(str))
        else:
            out["rider_id"] = mapped.fillna(out[rider_no_col].astype(str))
    return out

def _rider_color(rider) -> str:
    if rider == "DA77":
        return DA77_COLOR
    if rider == "JA52":
        return JA52_COLOR
    palette = ["#8E44AD", "#16A085", "#D35400", "#2C3E50", "#F39C12", "#1ABC9C"]
    idx = sum(ord(ch) for ch in str(rider)) % len(palette)
    return palette[idx]

def _rider_color_map(riders) -> dict:
    return {str(r): _rider_color(str(r)) for r in riders}

# ── Run Log (setup data per run) ─────────────────
# Maps round_id in lap_times/DB → CIRCUIT name in Data_Bace_TS24_ORIGINAL
ROUND_CIRCUIT_MAP = {
    "ROUND1":  "PI",
    "ROUND2":  "PORTIMAO",
    "ROUND3":  "ASSEN",
    "ROUND4":  "BALATON",
    "ROUND5":  "MOST",
    "ROUND11": "ESTORIL",
    "ROUND12": "JEREZ",
}
# lap_times uses "SP" for Superpole; ORIGINAL uses "QP"
SESSION_LAP_TO_ORIG = {"SP": "QP"}

@st.cache_data(ttl=300)
def load_run_log():
    """Load run-by-run setup data from Data_Bace_TS24_ORIGINAL.xlsx.
    Returns empty DataFrame if file not available (e.g. Streamlit Cloud)."""
    candidates = [
        SCRIPT_DIR.parent / "04_REFERENCE" / "Data_Bace_TS24_ORIGINAL.xlsx",
        SCRIPT_DIR / "Data_Bace_TS24_ORIGINAL.xlsx",
    ]
    for path in candidates:
        if path.exists():
            try:
                import openpyxl  # noqa: F401 — just to check availability
                df_raw = pd.read_excel(str(path), sheet_name="DATA", header=None)
                headers_raw = df_raw.iloc[1].tolist()
                seen_h = {}; clean_h = []
                for h in headers_raw:
                    key = f"_blank_{len(seen_h)}" if pd.isna(h) else str(h).strip()
                    if key in seen_h:
                        seen_h[key] += 1; clean_h.append(f"{key}_{seen_h[key]}")
                    else:
                        seen_h[key] = 1; clean_h.append(key)
                df = df_raw.iloc[2:].copy()
                df.columns = clean_h
                df = df.reset_index(drop=True)
                df["CIRCUIT"] = df["CIRCUIT"].str.strip()
                df["SESSION"] = df["SESSION"].str.strip()
                df["RUN"]     = pd.to_numeric(df["RUN"], errors="coerce").fillna(0).astype(int)
                return df
            except Exception:
                pass
    return pd.DataFrame()

# ── Dynamics & Correlation data loader ───────────
_DYNAMICS_EXCEL = SCRIPT_DIR.parent / "02_DATABASE" / "TS24 DB Master.xlsx"

_JSON_DYN = SCRIPT_DIR / "dynamics_data.json"
_JSON_LT  = SCRIPT_DIR / "lap_times_data.json"

# _coerce_dyn_numerics imported from services.data_loader (alias set above)

@st.cache_data(ttl=120)
def _load_dynamics_data():
    """Load DYNAMICS_ANALYSIS and LAP_TIMES.
    Priority: TS24 DB Master.xlsx (local Mac) → JSON fallback (Streamlit Cloud)."""
    if _DYNAMICS_EXCEL.exists():
        return load_dynamics_from_excel(_DYNAMICS_EXCEL)
    return load_dynamics_from_json(_JSON_DYN, _JSON_LT)


_JSON_LAP_SUS = SCRIPT_DIR / "lap_suspension_data.json"
_JSON_RUNS = SCRIPT_DIR / "runs_data.json"

@st.cache_data(ttl=120)
def _load_lap_suspension() -> pd.DataFrame:
    """Load LAP_SUSPENSION data for the Lap Sus Stats page.

    Streamlit Cloud normally uses the JSON cache. Local execution can use
    SQLite when DB_PATH is available.
    """
    try:
        if DB_PATH is not None and DB_PATH.exists():
            df = load_lap_suspension_from_sqlite(DB_PATH)
            if not df.empty:
                return df
    except Exception:
        pass
    return load_lap_suspension_from_json(_JSON_LAP_SUS)

@st.cache_data(ttl=120)
def _load_runs_data() -> pd.DataFrame:
    """Load run-level setup data exported from ts24_unified.db."""
    try:
        if DB_PATH is not None and DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH))
            tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)["name"].tolist()
            if "runs" in tables:
                df = pd.read_sql("SELECT * FROM runs", conn)
                conn.close()
                if not df.empty:
                    df = df.rename(columns={
                        "session": "session_type",
                        "date": "session_date",
                        "r_spr": "r_spring",
                        "ride_hgt": "ride_height",
                        "tyre_front": "f_tyre",
                        "tyre_rear": "r_tyre",
                    })
                    if "f_spring" not in df.columns and {"f_spr_l", "f_spr_r"}.issubset(df.columns):
                        df["f_spring"] = df.apply(
                            lambda r: f"{r['f_spr_l']}/{r['f_spr_r']}"
                            if pd.notna(r["f_spr_l"]) or pd.notna(r["f_spr_r"]) else None,
                            axis=1,
                        )
                    return df
            conn.close()
    except Exception:
        pass
    try:
        if _JSON_RUNS.exists():
            return pd.read_json(str(_JSON_RUNS), convert_dates=False)
    except Exception:
        pass
    return pd.DataFrame()

_JSON_CORNER_PHASE = SCRIPT_DIR / "corner_phase_data.json"

@st.cache_data(ttl=120)
def _load_corner_phase() -> pd.DataFrame:
    """corner_phase_data.json を読み込んで DataFrame を返す。"""
    _NUM_COLS = [
        "lap_time_s","corner_no","lap_no","run_no",
        "ph12_duration_ms","ph12_brake_peak_bar","ph12_susf_avg",
        "ph3_duration_ms","ph3_speed_min","ph3_susf_avg","ph3_susr_avg",
        "ph45_duration_ms","ph45_gas_avg","ph45_susf_avg","total_corner_ms",
        "brake_peak_progress","cluster_lap_count",
    ]
    try:
        if _JSON_CORNER_PHASE.exists():
            df = pd.read_json(str(_JSON_CORNER_PHASE), convert_dates=False)
            df.columns = [c.lower() for c in df.columns]
            for c in _NUM_COLS:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna(how="all").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame()


_JSON_CORNER_PHASE = SCRIPT_DIR / "corner_phase_data.json"

@st.cache_data(ttl=120)
def _load_corner_phase() -> pd.DataFrame:
    """corner_phase_data.json を読み込んで DataFrame を返す。"""
    _NUM_COLS = [
        "lap_time_s","corner_no","lap_no","run_no",
        "ph12_duration_ms","ph12_brake_peak_bar","ph12_susf_avg",
        "ph3_duration_ms","ph3_speed_min","ph3_susf_avg","ph3_susr_avg",
        "ph45_duration_ms","ph45_gas_avg","ph45_susf_avg","total_corner_ms",
    ]
    try:
        if _JSON_CORNER_PHASE.exists():
            df = pd.read_json(str(_JSON_CORNER_PHASE), convert_dates=False)
            df.columns = [c.lower() for c in df.columns]
            for c in _NUM_COLS:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            return df.dropna(how="all").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame()


_JSON_LAP_OVERLAY    = SCRIPT_DIR / "lap_overlay_data.json"
_JSON_TURN_TEMPLATES = SCRIPT_DIR / "turn_templates.json"

@st.cache_data(ttl=300)
def _load_turn_templates() -> dict:
    """turn_templates.json を読み込んで dict を返す。存在しなければ空dict。"""
    try:
        if _JSON_TURN_TEMPLATES.exists():
            return json.loads(_JSON_TURN_TEMPLATES.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


@st.cache_data(ttl=120)
def _load_lap_overlay() -> list[dict]:
    """lap_overlay_data.json を読み込んでリストを返す。"""
    try:
        if _JSON_LAP_OVERLAY.exists():
            return json.loads(_JSON_LAP_OVERLAY.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _dyn_norm_circuit(c):
    c = str(c or "").upper().strip()
    if c in ("PHILLIPISLAND","PHILLIP ISLAND","PHI","AUSTRALIA","WORKSHOP","PHILLIP_ISLAND"):
        return "PHILLIP ISLAND"
    return c

_ROUND_ORDER_P = [
    "ROUND11", "ROUND12",
    "TEST1", "TEST2", "TEST3", "TEST4", "TEST5",
    "ROUND1", "ROUND2", "ROUND3", "ROUND4", "ROUND5",
]

def _rnd_sort(r):
    """Stable chronological-ish order used across dashboard pages."""
    r = str(r or "")
    try:
        return _ROUND_ORDER_P.index(r)
    except ValueError:
        import re
        m = re.search(r"ROUND(\d+)", r)
        if m:
            return 100 + int(m.group(1))
        return 999


def _fmt_seconds(value) -> str:
    try:
        sec = float(value)
    except Exception:
        return "—"
    if not np.isfinite(sec):
        return "—"
    m = int(sec // 60)
    s = sec - 60 * m
    return f"{m}'{s:06.3f}" if m else f"{s:.3f}"


def _normalize_race_results_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize race_results from local DB and Supabase variants."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df

    out = df.copy()
    if "rider_id" not in out.columns:
        if "rider_num" in out.columns:
            rider_num = pd.to_numeric(out["rider_num"], errors="coerce")
            out["rider_id"] = rider_num.map({77: "DA77", 52: "JA52"}).fillna(out["rider_num"].astype(str))
        elif "rider_no" in out.columns:
            rider_num = pd.to_numeric(out["rider_no"], errors="coerce")
            out["rider_id"] = rider_num.map({77: "DA77", 52: "JA52"}).fillna(out["rider_no"].astype(str))
        elif "rider" in out.columns:
            out["rider_id"] = out["rider"].astype(str)
        elif "rider_name" in out.columns:
            out["rider_id"] = out["rider_name"].astype(str)
        else:
            out["rider_id"] = ""

    if "round_no" not in out.columns and "round" in out.columns:
        out["round_no"] = out["round"]
    if "round_id" not in out.columns and "round" in out.columns:
        out["round_id"] = out["round"]
    if "session_type" not in out.columns and "session" in out.columns:
        out["session_type"] = out["session"]
    if "circuit" in out.columns:
        out["circuit"] = out["circuit"].astype(str)
    if "event_date" not in out.columns and "date" in out.columns:
        out["event_date"] = out["date"]
    if "position" in out.columns:
        out["position"] = pd.to_numeric(out["position"], errors="coerce")
    if "best_lap_s" in out.columns:
        out["best_lap_s"] = pd.to_numeric(out["best_lap_s"], errors="coerce")
    if "gap_to_top" not in out.columns and {"round_no", "session_type", "best_lap_s"}.issubset(out.columns):
        top = out.groupby(["round_no", "session_type"])["best_lap_s"].transform("min")
        out["gap_to_top"] = out["best_lap_s"] - top
    if "top_time" not in out.columns and {"round_no", "session_type", "best_lap_s"}.issubset(out.columns):
        top = out.groupby(["round_no", "session_type"])["best_lap_s"].transform("min")
        out["top_time"] = top.apply(lambda v: _fmt_seconds(v) if pd.notna(v) else "—")
    return out


def _ts24_race_results_view(df: pd.DataFrame) -> pd.DataFrame:
    """Return one clean result row per round/session/rider."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = _normalize_race_results_columns(df)
    if "rider_id" not in out.columns:
        return pd.DataFrame()
    if out.empty:
        return out
    if "position" in out.columns:
        out = out[out["position"].notna()]
    sort_cols = [c for c in ["round_no", "session_type", "rider_id", "position", "best_lap_s"] if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols)
    key_cols = [c for c in ["round_no", "session_type", "rider_id"] if c in out.columns]
    if key_cols:
        out = out.drop_duplicates(key_cols, keep="first")
    return out.reset_index(drop=True)


# _dyn_norm_circuit / _dyn_norm_session imported from domain.lap_analysis (aliases set above)

# ── Color palette (Power BI style) ────────────────
# DA77_COLOR, JA52_COLOR, PHASE_COLORS, PHASE_LABELS, CHART_FONT
# are all imported from components.charts at the top of this file.

# ── Claude API helper ─────────────────────────────
# call_claude imported from services.claude_client at the top of this file.
# Model constants exposed for any local reference:
from services.claude_client import CLAUDE_API_URL, CLAUDE_API_MODEL

# ══════════════════════════════════════════════════════════════
# RACE MEMORY SYSTEM — persistent knowledge across sessions
# ══════════════════════════════════════════════════════════════

def load_race_memory() -> dict:
    """Load persistent race memory. /tmp first (writable on Cloud), then repo."""
    return _ms_load_race_memory(MEMORY_FILE, _TMP_MEMORY)

def save_race_memory(memory: dict):
    """Save memory to both /tmp (Cloud) and repo (local)."""
    _ms_save_race_memory(memory, _TMP_MEMORY, MEMORY_FILE)

def extract_and_save_insights(api_key: str, conversation: list, context: dict):
    """Call Claude to extract key insights from conversation, save to memory."""
    if len(conversation) < 2:
        return
    conv_text = "\n".join([
        f"{m['role'].upper()}: {m['content'][:400]}"
        for m in conversation[-12:]
    ])
    prompt = (
        "You are reviewing a motorcycle racing engineering conversation.\n"
        "Extract up to 3 specific, actionable setup insights (numbers preferred).\n"
        f"Context — Page: {context.get('page','?')}, "
        f"Rider: {context.get('rider','All')}, "
        f"Circuit: {context.get('circuit','All')}\n\n"
        f"Conversation:\n{conv_text}\n\n"
        "Return ONLY a JSON array of concise English insight strings, e.g.:\n"
        '[\"DA77 needs +3mm THR_ON SusF at PORTIMAO\"]'
    )
    result = call_claude(api_key, prompt, max_tokens=400)
    try:
        insights = json.loads(result)
        if not isinstance(insights, list):
            return
    except Exception:
        return

    import datetime
    memory = load_race_memory()
    today  = datetime.date.today().isoformat()
    circ   = context.get("circuit", "ALL")
    rider  = context.get("rider", "ALL")

    # Store per-circuit per-rider
    if circ and circ != "All":
        memory["circuit_insights"].setdefault(circ, {})
        memory["circuit_insights"][circ].setdefault(rider, [])
        for ins in insights:
            entry = f"[{today}] {ins}"
            if entry not in memory["circuit_insights"][circ][rider]:
                memory["circuit_insights"][circ][rider].append(entry)
        # Keep last 20 per rider per circuit
        memory["circuit_insights"][circ][rider] = \
            memory["circuit_insights"][circ][rider][-20:]
    else:
        for ins in insights:
            entry = f"[{today}] {ins}"
            if entry not in memory["global_insights"]:
                memory["global_insights"].append(entry)
        memory["global_insights"] = memory["global_insights"][-30:]

    # Conversation summary
    if len(conversation) >= 4:
        summary_prompt = (
            "Summarize this racing engineering conversation in 1-2 sentences (English):\n"
            + conv_text
        )
        summary = call_claude(api_key, summary_prompt, max_tokens=150)
        memory["conversation_summaries"].append({
            "date": today, "page": context.get("page","?"),
            "rider": rider, "circuit": circ,
            "summary": summary[:300],
        })
        memory["conversation_summaries"] = memory["conversation_summaries"][-50:]

    save_race_memory(memory)

# build_memory_context imported from services.memory_service at the top of this file.


# ══════════════════════════════════════════════════════════════
# FLOATING CHAT — parent-DOM injection via st.components.v1.html
# No sidebar, no URL params, no page reload.
# ══════════════════════════════════════════════════════════════

def render_float_chat_component(api_key: str, memory: dict, page_ctx: dict):
    """
    Inject a floating chat panel directly into the parent page DOM using a
    zero-height st.components.v1.html iframe.  The panel makes fetch() calls
    to the Claude API from JavaScript — no Streamlit rerun on send.
    """
    import streamlit.components.v1 as components

    circ  = page_ctx.get("circuit", "All")
    rider = page_ctx.get("rider",   "All")
    page  = page_ctx.get("page",    "Dashboard")
    snap  = page_ctx.get("data_snapshot", "")

    memory_ctx = build_memory_context(memory, circ, rider)
    system_prompt = (
        "あなたはWorldSSPモーターサイクルレーシングチームのシニアエンジニアです。"
        f"現在のダッシュボード: ページ={page}, サーキット={circ}, ライダー={rider}。"
        "ライダーはDA77とJA52の2名。"
        "サスペンションデータはAPEX定義(BRAKE_FRONT+GAS+dTPS_A+SUSP_F+SUSP_R 5条件同時成立区間)を使用。"
        "具体的な数値と範囲を示して答えてください。日本語で回答してください。"
        + (f"\n\n[現在の表示データ]\n{snap}" if snap else "")
        + memory_ctx
    )

    mem_count = sum(
        len(v) for c in memory.get("circuit_insights", {}).values()
        for v in c.values()
    ) + len(memory.get("global_insights", []))

    # Escape for JS string embedding
    api_key_js     = json.dumps(api_key)
    sys_prompt_js  = json.dumps(system_prompt)
    mem_count_js   = json.dumps(mem_count)
    page_label_js  = json.dumps(f"{page}" + (f" · {circ}" if circ != "All" else "") +
                                (f" · {rider}" if rider != "All" else ""))

    html = f"""
<script>
(function() {{
  var doc = window.parent.document;

  /* ── Update context on every Streamlit rerun without re-building the UI ── */
  var meta = doc.getElementById('ts24-chat-meta');
  if (meta) {{
    meta.dataset.sys   = {sys_prompt_js};
    meta.dataset.label = {page_label_js};
    meta.dataset.mem   = {mem_count_js};
    var lbl = doc.getElementById('ts24-ctx-label');
    if (lbl) lbl.textContent = {page_label_js};
    var mcnt = doc.getElementById('ts24-mem-count');
    if (mcnt) mcnt.textContent = {mem_count_js} + ' memories';
    return;   /* panel already exists */
  }}

  /* ── First render: inject styles + panel ── */
  var s = doc.createElement('style');
  s.textContent = `
    #ts24-fab {{
      position:fixed; bottom:26px; right:26px; z-index:99999;
      width:56px; height:56px; border-radius:50%;
      background:linear-gradient(135deg,#0078D4,#005fa3);
      color:#fff; border:3px solid #fff; cursor:pointer;
      font-size:22px; box-shadow:0 4px 18px rgba(0,120,212,.5);
      transition:transform .15s,box-shadow .15s;
      display:flex; align-items:center; justify-content:center;
    }}
    #ts24-fab:hover {{ transform:scale(1.10); box-shadow:0 6px 22px rgba(0,120,212,.65); }}
    #ts24-fab-tip {{
      position:fixed; bottom:88px; right:16px; z-index:99999;
      background:rgba(0,0,0,.72); color:#fff; font-size:11px;
      padding:3px 9px; border-radius:4px; pointer-events:none;
      white-space:nowrap; font-family:Arial,sans-serif;
    }}
    #ts24-panel {{
      position:fixed; bottom:96px; right:26px; z-index:99998;
      width:360px; height:520px;
      background:#fff; border-radius:14px;
      box-shadow:0 8px 32px rgba(0,0,0,.18);
      display:none; flex-direction:column;
      font-family:Arial,sans-serif; overflow:hidden;
      border:1px solid #DDE1E7;
    }}
    #ts24-panel.open {{ display:flex; }}
    #ts24-ph {{
      background:linear-gradient(135deg,#0078D4,#005fa3);
      color:#fff; padding:12px 14px 8px;
      display:flex; flex-direction:column; gap:2px; flex-shrink:0;
    }}
    #ts24-ph-top {{ display:flex; align-items:center; justify-content:space-between; }}
    #ts24-ph-title {{ font-weight:700; font-size:14px; }}
    #ts24-ph-close {{
      background:rgba(255,255,255,.2); border:none; color:#fff;
      width:24px; height:24px; border-radius:50%; cursor:pointer;
      font-size:14px; display:flex; align-items:center; justify-content:center;
    }}
    #ts24-ctx-label {{ font-size:10px; opacity:.8; }}
    #ts24-mem-count {{ font-size:10px; opacity:.7; }}
    #ts24-msgs {{
      flex:1; overflow-y:auto; padding:12px 10px; display:flex;
      flex-direction:column; gap:8px;
    }}
    .ts24-msg {{ max-width:88%; padding:8px 11px; border-radius:10px; font-size:13px; line-height:1.45; word-break:break-word; }}
    .ts24-user {{ align-self:flex-end; background:#0078D4; color:#fff; border-bottom-right-radius:3px; }}
    .ts24-bot  {{ align-self:flex-start; background:#F0F4F8; color:#111; border-bottom-left-radius:3px; }}
    .ts24-typing {{ opacity:.6; font-style:italic; }}
    #ts24-input-row {{
      display:flex; gap:6px; padding:8px 10px 12px;
      border-top:1px solid #EEE; flex-shrink:0;
    }}
    #ts24-input {{
      flex:1; border:1px solid #DDE1E7; border-radius:8px;
      padding:7px 10px; font-size:13px; resize:none;
      outline:none; font-family:Arial,sans-serif;
    }}
    #ts24-send {{
      background:#0078D4; color:#fff; border:none; border-radius:8px;
      padding:0 14px; cursor:pointer; font-size:18px; flex-shrink:0;
    }}
    #ts24-send:disabled {{ background:#AAC8E8; cursor:default; }}
    #ts24-empty {{
      flex:1; display:flex; align-items:center; justify-content:center;
      color:#AAA; font-size:12px; text-align:center; line-height:1.6;
    }}
    @media (max-width: 768px) {{
      #ts24-panel {{
        width: calc(100vw - 20px) !important;
        right: 10px !important;
        left: 10px !important;
        height: 70vh !important;
        bottom: 90px !important;
      }}
      #ts24-fab {{
        bottom: 16px !important;
        right: 16px !important;
        width: 48px !important;
        height: 48px !important;
      }}
      #ts24-fab-tip {{
        bottom: 74px !important;
        right: 10px !important;
      }}
    }}
  `;
  doc.head.appendChild(s);

  /* ── Hidden meta element: updated on every Streamlit rerun ── */
  var meta = doc.createElement('div');
  meta.id = 'ts24-chat-meta';
  meta.style.display = 'none';
  meta.dataset.sys   = {sys_prompt_js};
  meta.dataset.label = {page_label_js};
  meta.dataset.key   = {api_key_js};
  meta.dataset.mem   = {mem_count_js};
  doc.body.appendChild(meta);

  /* ── Panel HTML ── */
  var wrap = doc.createElement('div');
  wrap.innerHTML = `
    <span id="ts24-fab-tip">AI Chat</span>
    <button id="ts24-fab" onclick="ts24Toggle()" title="AI Analysis Partner">🤖</button>
    <div id="ts24-panel">
      <div id="ts24-ph">
        <div id="ts24-ph-top">
          <span id="ts24-ph-title">🤖 AI Analysis Partner</span>
          <button id="ts24-ph-close" onclick="ts24Toggle()">✕</button>
        </div>
        <div id="ts24-ctx-label">{page_label_js.strip('"')}</div>
        <div id="ts24-mem-count">{mem_count_js} memories</div>
      </div>
      <div id="ts24-msgs">
        <div id="ts24-empty">データを見ながら<br>何でも聞いてください。<br><small>過去の知見も踏まえて答えます。</small></div>
      </div>
      <div id="ts24-input-row">
        <textarea id="ts24-input" rows="2" placeholder="気づいたことを聞いてください…"></textarea>
        <button id="ts24-send" onclick="ts24Send()">➤</button>
      </div>
    </div>
  `;
  doc.body.appendChild(wrap);

  /* ── State ── */
  var history = [];
  var open    = false;

  /* ── Toggle — defined on parent window so onclick attrs in parent DOM can find it ── */
  window.parent.ts24Toggle = function() {{
    open = !open;
    doc.getElementById('ts24-panel').classList.toggle('open', open);
    doc.getElementById('ts24-fab').textContent = open ? '✕' : '🤖';
    doc.getElementById('ts24-fab-tip').textContent = open ? 'チャットを閉じる' : 'AI Chat';
    if (open) doc.getElementById('ts24-input').focus();
  }};

  /* ── Add message bubble ── */
  function addMsg(role, text) {{
    var empty = doc.getElementById('ts24-empty');
    if (empty) empty.remove();
    var msgs = doc.getElementById('ts24-msgs');
    var d = doc.createElement('div');
    d.className = 'ts24-msg ' + (role === 'user' ? 'ts24-user' : 'ts24-bot');
    if (text === '…') d.classList.add('ts24-typing');
    d.id = (text === '…') ? 'ts24-typing-bubble' : '';
    // Simple markdown: **bold**
    d.innerHTML = text.replace(/\\n/g,'<br>')
                      .replace(/\\*\\*(.*?)\\*\\*/g,'<b>$1</b>');
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }}

  /* ── Send — defined on parent window so onclick attrs in parent DOM can find it ── */
  window.parent.ts24Send = async function() {{
    var meta   = doc.getElementById('ts24-chat-meta');
    var apiKey = meta ? meta.dataset.key : '';
    var sys    = meta ? meta.dataset.sys : '';
    var input  = doc.getElementById('ts24-input');
    var sendBtn= doc.getElementById('ts24-send');
    var text   = input.value.trim();
    if (!text) return;
    if (!apiKey) {{ addMsg('bot','⚠️ APIキーが設定されていません。左ナビで設定してください。'); return; }}

    input.value = '';
    addMsg('user', text);
    history.push({{role:'user', content:text}});
    sendBtn.disabled = true;
    var typing = addMsg('bot', '…');

    try {{
      var resp = await fetch('https://api.anthropic.com/v1/messages', {{
        method:'POST',
        headers:{{
          'x-api-key': apiKey,
          'anthropic-version':'2023-06-01',
          'anthropic-dangerous-allow-any-cors-origin': 'true',
          'content-type':'application/json'
        }},
        body: JSON.stringify({{
          model: 'claude-sonnet-4-6',
          max_tokens: 1200,
          system: sys,
          messages: history
        }})
      }});
      var data = await resp.json();
      if (data.error) throw new Error(data.error.message);
      var reply = data.content[0].text;
      typing.remove();
      addMsg('bot', reply);
      history.push({{role:'assistant', content:reply}});
    }} catch(e) {{
      typing.remove();
      addMsg('bot', '⚠️ エラー: ' + e.message);
    }}
    sendBtn.disabled = false;
    input.focus();
  }};

  /* ── Enter key (Shift+Enter = newline) ── */
  doc.getElementById('ts24-input').addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); window.parent.ts24Send(); }}
  }});

}})();
</script>

<script>
/* ── Mobile hamburger nav menu (v4 — MutationObserver + multi-selector) ── */
(function() {{
  var doc      = window.parent.document;
  var win      = window.parent;
  var isMobile = win.innerWidth <= 768;
  var NAV_LABEL = {page_label_js};

  /* ── Find nav column: try multiple selectors + content check ── */
  function getNavCol() {{
    var candidates = [
      doc.querySelector('[data-testid="stHorizontalBlock"] > [data-testid="column"]:first-child'),
      doc.querySelector('[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child'),
      doc.querySelector('[data-testid="stHorizontalBlock"] > div:first-child')
    ];
    for (var i = 0; i < candidates.length; i++) {{
      if (candidates[i] && candidates[i].textContent.indexOf('Set-UP Tool') > -1) return candidates[i];
    }}
    /* Fallback: search all stHorizontalBlock first children for known text */
    var blocks = doc.querySelectorAll('[data-testid="stHorizontalBlock"]');
    for (var j = 0; j < blocks.length; j++) {{
      var fc = blocks[j].firstElementChild;
      if (fc && fc.textContent.indexOf('Set-UP Tool') > -1) return fc;
    }}
    return null;
  }}

  /* ── Hide nav: inline style + MutationObserver to fight React re-renders ── */
  function applyHide(nc) {{
    if (nc) nc.style.setProperty('display', 'none', 'important');
  }}

  function startObserver(nc) {{
    if (win._ts24Obs) win._ts24Obs.disconnect();
    win._ts24Obs = new MutationObserver(function() {{
      if (!win._ts24Open && nc.style.display !== 'none') {{
        nc.style.setProperty('display', 'none', 'important');
      }}
    }});
    win._ts24Obs.observe(nc, {{ attributes: true, attributeFilter: ['style', 'class'] }});
  }}

  function initHide() {{
    var nc = getNavCol();
    if (nc) {{ applyHide(nc); startObserver(nc); }}
    else {{ setTimeout(initHide, 250); }}
  }}

  /* ── Every Streamlit rerun: refresh label + re-close nav ── */
  var existing = doc.getElementById('ts24-mobile-header');
  if (existing) {{
    var nameEl = doc.getElementById('ts24-mobile-page-name');
    if (nameEl) nameEl.textContent = NAV_LABEL;
    if (isMobile) {{
      win._ts24Open = false;
      doc.body.classList.remove('ts24-nav-open');
      var btn = doc.getElementById('ts24-hamburger-btn');
      if (btn) btn.textContent = '☰';
      initHide();  /* re-hide after React re-render */
    }}
    return;
  }}

  if (!isMobile) return;  /* desktop: do nothing */

  /* ── Inject CSS into <head> for overlay styles ── */
  var s = doc.createElement('style');
  s.id = 'ts24-mobile-nav-styles';
  s.textContent = `
    #ts24-mobile-header {{
      position:fixed; top:0; left:0; right:0; z-index:99995; height:52px;
      background:#FFFFFF; border-bottom:1px solid #DDE1E7;
      display:flex; align-items:center; justify-content:space-between;
      padding:0 14px; box-shadow:0 2px 8px rgba(0,0,0,.08); font-family:Arial,sans-serif;
    }}
    #ts24-mobile-logo {{ font-weight:800; font-size:15px; color:#0078D4; white-space:nowrap; }}
    #ts24-mobile-page-name {{
      flex:1; text-align:center; font-size:13px; font-weight:600; color:#333;
      overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin:0 10px;
    }}
    #ts24-hamburger-btn {{
      background:none; border:1px solid #DDE1E7; font-size:20px;
      cursor:pointer; padding:4px 10px; color:#333; border-radius:8px; line-height:1.3;
    }}
    #ts24-nav-backdrop {{ position:fixed; inset:0; background:rgba(0,0,0,.42); z-index:99989; display:none; }}
    body.ts24-nav-open #ts24-nav-backdrop {{ display:block; }}
  `;
  doc.head.appendChild(s);

  win._ts24Open = false;

  /* ── Header bar ── */
  var header = doc.createElement('div');
  header.id = 'ts24-mobile-header';
  header.innerHTML =
    '<span id="ts24-mobile-logo">🏍 TS24</span>' +
    '<span id="ts24-mobile-page-name">' + NAV_LABEL + '</span>' +
    '<button id="ts24-hamburger-btn" onclick="ts24NavToggle()" title="メニュー">☰</button>';
  doc.body.appendChild(header);

  /* ── Backdrop ── */
  var bd = doc.createElement('div');
  bd.id = 'ts24-nav-backdrop';
  bd.onclick = function() {{ win.ts24NavClose(); }};
  doc.body.appendChild(bd);

  /* ── Start hiding nav column ── */
  initHide();

  /* ── Open overlay ── */
  win.ts24NavToggle = function() {{
    if (win._ts24Open) {{ win.ts24NavClose(); return; }}
    var nc  = getNavCol();
    var btn = doc.getElementById('ts24-hamburger-btn');
    if (!nc) return;
    win._ts24Open = true;
    if (win._ts24Obs) win._ts24Obs.disconnect();  /* stop fighting React while open */
    doc.body.classList.add('ts24-nav-open');
    nc.style.setProperty('display',          'block',                      'important');
    nc.style.setProperty('position',         'fixed',                      'important');
    nc.style.setProperty('top',              '0',                          'important');
    nc.style.setProperty('left',             '0',                          'important');
    nc.style.setProperty('width',            '280px',                      'important');
    nc.style.setProperty('height',           '100vh',                      'important');
    nc.style.setProperty('z-index',          '99990',                      'important');
    nc.style.setProperty('background-color', '#FFFFFF',                    'important');
    nc.style.setProperty('overflow-y',       'auto',                       'important');
    nc.style.setProperty('overflow-x',       'hidden',                     'important');
    nc.style.setProperty('padding',          '60px 12px 24px',             'important');
    nc.style.setProperty('box-shadow',       '4px 0 24px rgba(0,0,0,.22)','important');
    if (btn) btn.textContent = '✕';
  }};

  /* ── Close overlay ── */
  win.ts24NavClose = function() {{
    var btn = doc.getElementById('ts24-hamburger-btn');
    win._ts24Open = false;
    doc.body.classList.remove('ts24-nav-open');
    if (btn) btn.textContent = '☰';
    initHide();  /* re-hide with observer */
  }};

}})();
</script>
"""
    components.html(html, height=0, scrolling=False)


# chart_layout imported from components.charts as alias at the top of this file.

# ── Page config ───────────────────────────────────
st.set_page_config(
    page_title="TS24 Dashboard",
    page_icon="🏍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Global CSS ────────────────────────────────────
st.markdown("""
<style>
    /* ── Force light mode across the entire app ── */
    html, body, [class*="css"], .stApp, .stApp > div,
    section[data-testid="stSidebar"],
    div[data-testid="stAppViewContainer"],
    div[data-testid="stMain"],
    div[data-testid="block-container"] {
        background-color: #F4F6F8 !important;
        color: #111111 !important;
    }

    /* Sidebar — hidden (not used; chat uses DOM-inject overlay) */
    section[data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"]  { display: none !important; }

    /* KPI metric cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF !important;
        border: 1px solid #DDE1E7 !important;
        border-left: 4px solid #0078D4 !important;
        border-radius: 6px !important;
        padding: 14px 18px !important;
    }
    div[data-testid="metric-container"] * { color: #111111 !important; }
    div[data-testid="metric-container"] label {
        font-size: 11px !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
        color: #555555 !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 26px !important;
        font-weight: 700 !important;
        color: #111111 !important;
    }

    /* Tabs */
    div[data-testid="stTabs"] { background: transparent !important; }
    button[data-baseweb="tab"] {
        font-size: 13px !important;
        font-weight: 600 !important;
        color: #444444 !important;
        background: transparent !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #0078D4 !important;
        border-bottom: 3px solid #0078D4 !important;
    }

    /* Selectbox / radio */
    div[data-testid="stSelectbox"] *, div[data-testid="stRadio"] * {
        color: #111111 !important;
    }

    /* Text areas */
    textarea { background-color: #FAFAFA !important; color: #111111 !important; }

    /* Divider */
    hr { border-color: #DDE1E7 !important; }

    /* Caption / small text */
    .stCaption, small { color: #666666 !important; }

    /* Section title */
    .section-title {
        font-size: 12px !important;
        font-weight: 700 !important;
        color: #333333 !important;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin: 0 0 8px 0;
        padding-bottom: 5px;
        border-bottom: 2px solid #0078D4;
        display: block;
    }

    /* Detail rows in Session Detail */
    .detail-row {
        display: flex;
        justify-content: space-between;
        padding: 5px 0;
        border-bottom: 1px solid #EEEEEE;
        font-size: 13px;
        color: #111111 !important;
    }
    .detail-label { color: #666666 !important; font-weight: 600; min-width: 90px; }
    .detail-val   { color: #111111 !important; font-weight: 400; }

    /* Phase badge */
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 11px;
        font-weight: 700;
        margin: 2px;
        color: #FFFFFF !important;
    }

    /* Hide Streamlit branding */
    #MainMenu, footer, header { visibility: hidden; }

    /* ── Left nav column styling ── */
    /* Nav radio: hide widget label */
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] > div:first-child {
        display: none !important;
    }
    /* Nav radio: each item row */
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] label {
        border-radius: 8px !important;
        padding: 9px 10px !important;
        margin: 2px 0 !important;
        transition: background 0.12s ease;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] label:hover {
        background: #EBF5FB !important;
    }
    /* Active nav item */
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] label:has(input:checked) {
        background: #DBEAFE !important;
        border-left: 3px solid #0078D4 !important;
        padding-left: 7px !important;
    }
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] label:has(input:checked) p {
        color: #0078D4 !important;
        font-weight: 700 !important;
    }
    /* Hide the radio dot */
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] input[type="radio"] {
        display: none !important;
    }
    div[data-testid="stVerticalBlock"] div[data-testid="stRadio"] [data-baseweb="radio"] > div:first-child {
        width: 0 !important; min-width: 0 !important;
        margin: 0 !important; padding: 0 !important; overflow: hidden !important;
    }
    /* Hide Streamlit sidebar toggle (not needed with column nav) */
    button[data-testid="collapsedControl"],
    div[data-testid="stSidebarCollapsedControl"] {
        display: none !important;
    }

    /* ── Sticky left nav column ── */
    /* The columns flex container: align items to top so sticky works */
    div[data-testid="stHorizontalBlock"] {
        align-items: flex-start !important;
    }
    /* First column (nav): sticky, scrolls independently */
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child {
        position: sticky !important;
        top: 0.5rem !important;
        max-height: calc(100vh - 1rem) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        scrollbar-width: thin !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child::-webkit-scrollbar {
        width: 4px;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child::-webkit-scrollbar-thumb {
        background: #DDE1E7;
        border-radius: 4px;
    }

    /* ── Mobile / iPhone responsive (max-width: 768px) ── */
    /* Nav show/hide is handled by JavaScript inline styles */
    @media (max-width: 768px) {

        /* Top padding to clear the fixed header bar injected by JS */
        div[data-testid="block-container"] {
            padding: 4.5rem 0.75rem 1rem !important;
            max-width: 100% !important;
        }

        /* Metric cards: compact */
        div[data-testid="stMetricValue"] {
            font-size: 20px !important;
        }
        div[data-testid="metric-container"] {
            padding: 10px 12px !important;
        }

        /* Tabs: compact text */
        button[data-baseweb="tab"] {
            font-size: 11px !important;
            padding: 8px 6px !important;
        }

        /* Charts: full width */
        div[data-testid="stPlotlyChart"] {
            width: 100% !important;
        }

        /* Section title: slightly smaller */
        .section-title {
            font-size: 11px !important;
        }

        /* Detail rows: allow wrapping */
        .detail-row {
            flex-wrap: wrap !important;
            font-size: 12px !important;
        }
    }
</style>
""", unsafe_allow_html=True)


# ── MotoGP Performance Analysis — app shell ───────────────────────
from motogp_tool.app_page import render_motogp_page

# Race memory kept so the floating AI chat keeps working
if "race_memory" not in st.session_state:
    st.session_state["race_memory"] = load_race_memory()

_cur_user = st.session_state.get("current_user", "")
_cur_role = get_user_role(_cur_user)

_nav_col, _content_col = st.columns([1, 5], gap="small")

with _nav_col:
    st.markdown(
        "<div style='text-align:center;padding:10px 0 4px'>"
        "<span style='font-size:26px'>🏍</span><br>"
        "<span style='font-weight:800;font-size:15px;color:#0078D4;letter-spacing:.5px'>MotoGP</span>"
        "<span style='font-size:12px;color:#666'> Performance</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;font-size:11px;color:#999;margin:0 0 8px'>Timing Analysis</p>",
        unsafe_allow_html=True,
    )

    NAV_ITEMS = ["🏍  MotoGP Performance Analysis", "👤  Accounts"]
    if st.session_state.get("nav_menu") not in (None, *NAV_ITEMS):
        st.session_state["nav_menu"] = NAV_ITEMS[0]
    nav_sel = st.radio("nav", NAV_ITEMS, label_visibility="collapsed", key="nav_menu")

    st.divider()
    st.caption(f"👤 {_cur_user or '—'} · {_cur_role}")
    if st.button("Logout", use_container_width=True, key="logout_btn"):
        for _k in ("authenticated", "current_user"):
            st.session_state.pop(_k, None)
        st.rerun()

    if _cur_role == "admin":
        with st.expander("⚙️ Settings", expanded=False):
            _cfg = load_config()
            _ck = st.text_input(
                "Claude API Key (optional — enables AI Chat)",
                value=st.session_state.get("claude_api_key", _cfg.get("claude_api_key", "")),
                type="password", key="set_claude")
            _sk = st.text_input(
                "Supabase Service Key (optional — user storage)",
                value=_cfg.get("supabase_service_key", ""),
                type="password", key="set_supa")
            if st.button("💾 Save", key="save_settings", use_container_width=True):
                _cfg["claude_api_key"] = _ck
                _cfg["supabase_service_key"] = _sk
                save_config(_cfg)
                st.session_state["claude_api_key"] = _ck
                st.success("Saved.")

_NAV = nav_sel

with _content_col:
    # Floating AI chat (optional — active when a Claude API key is configured)
    _page_ctx = {
        "page": _NAV.strip().lstrip("🏍👤 ").strip(),
        "circuit": "-", "rider": "-", "data_snapshot": "",
    }
    if "race_memory" not in st.session_state:
        st.session_state["race_memory"] = load_race_memory()
    try:
        render_float_chat_component(
            api_key=st.session_state.get("claude_api_key", ""),
            memory=st.session_state["race_memory"],
            page_ctx=_page_ctx,
        )
    except Exception:
        pass

    # ═══════════════════════════════════════════════════
    # PAGE — MotoGP Performance Analysis
    # ═══════════════════════════════════════════════════
    if _NAV == "🏍  MotoGP Performance Analysis":
        render_motogp_page(
            is_admin=(_cur_role == "admin"),
            api_key=st.session_state.get("claude_api_key", ""),
        )

    # ═══════════════════════════════════════════════════
    # PAGE 12 — Accounts (admin-only)
    # ═══════════════════════════════════════════════════
    elif _NAV == "👤  Accounts":
        st.markdown('<p class="section-title">👤 Account Management — Admin Only</p>', unsafe_allow_html=True)

        _ac_user = st.session_state.get("current_user", "")
        _ac_role = get_user_role(_ac_user)

        if _ac_role != "admin":
            st.warning("🔒 This tab is for administrators only.")
            st.stop()

        all_users = get_users()

        # ── User List ─────────────────────────────────
        st.markdown("### Current Users")

        ROLE_BADGE = {
            "admin":    ("🔑", "#C0392B"),
            "engineer": ("🔧", "#2980B9"),
            "viewer":   ("👁",  "#7F8C8D"),
        }
        cols_header = st.columns([2, 2, 2, 2])
        cols_header[0].markdown("**Username**")
        cols_header[1].markdown("**Role**")
        cols_header[2].markdown("**Assigned Rider**")
        cols_header[3].markdown("**Action**")
        st.markdown("<hr style='margin:4px 0 8px 0;border-color:#DDE1E7'>", unsafe_allow_html=True)

        for uname, udata in sorted(all_users.items()):
            role  = udata.get("role", "engineer") if isinstance(udata, dict) else "engineer"
            rider = udata.get("rider") if isinstance(udata, dict) else None
            icon, color = ROLE_BADGE.get(role, ("?", "#999"))

            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            c1.markdown(f"**{uname}**")
            c2.markdown(
                f'<span style="background:{color};color:#fff;padding:2px 10px;'
                f'border-radius:10px;font-size:12px;font-weight:700">{icon} {role}</span>',
                unsafe_allow_html=True
            )
            c3.markdown(rider or "—")
            if uname != "ts24":
                if c4.button("🗑 Delete", key=f"del_{uname}", type="secondary"):
                    delete_user(uname)
                    st.success(f"User '{uname}' deleted.")
                    st.rerun()
            else:
                c4.caption("(protected)")

        st.divider()

        # ── Add User ──────────────────────────────────
        ac1, ac2 = st.columns(2, gap="large")

        with ac1:
            st.markdown("### ➕ Add New User")
            with st.form("add_user_form", clear_on_submit=True):
                nu_name  = st.text_input("Username", placeholder="e.g. mechanic01")
                nu_pass  = st.text_input("Password", type="password", placeholder="At least 6 characters")
                nu_role  = st.selectbox("Role", ["engineer", "viewer", "admin"],
                                        help="engineer: submit data & upload | viewer: read + upload | admin: full access")
                nu_rider = st.selectbox("Assigned Rider", ["None", "DA77", "JA52"],
                                        help="Engineers will only see data for their assigned rider")
                add_btn  = st.form_submit_button("➕ Add User", type="primary", use_container_width=True)

            if add_btn:
                if not nu_name.strip():
                    st.error("Username is required.")
                elif len(nu_pass) < 4:
                    st.error("Password must be at least 4 characters.")
                elif nu_name.strip() in all_users:
                    st.error(f"Username '{nu_name.strip()}' already exists.")
                else:
                    add_user(nu_name.strip(), nu_pass, nu_role, None if nu_rider == "None" else nu_rider)
                    st.success(f"✅ User '{nu_name.strip()}' added as {nu_role}.")
                    st.rerun()

        # ── Change Password ───────────────────────────
        with ac2:
            st.markdown("### 🔑 Change Password")
            with st.form("change_pw_form", clear_on_submit=True):
                pw_target = st.selectbox("User", list(all_users.keys()), key="pw_target")
                pw_new    = st.text_input("New Password", type="password", placeholder="Enter new password")
                pw_new2   = st.text_input("Confirm Password", type="password", placeholder="Repeat new password")
                pw_btn    = st.form_submit_button("🔑 Change Password", type="primary", use_container_width=True)

            if pw_btn:
                if not pw_new:
                    st.error("Password cannot be empty.")
                elif pw_new != pw_new2:
                    st.error("Passwords do not match.")
                elif len(pw_new) < 4:
                    st.error("Password must be at least 4 characters.")
                else:
                    cfg_pw = load_config()
                    users_pw = cfg_pw.get("users", {})
                    if pw_target in users_pw and isinstance(users_pw[pw_target], dict):
                        users_pw[pw_target]["password"] = _hash(pw_new)
                    else:
                        users_pw[pw_target] = {"password": _hash(pw_new),
                                               "role": _get_user_field(pw_target, "role", "engineer"),
                                               "rider": _get_user_field(pw_target, "rider")}
                    cfg_pw["users"] = users_pw
                    save_config(cfg_pw)
                    st.success(f"✅ Password for '{pw_target}' updated.")
