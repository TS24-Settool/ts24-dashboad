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
    payload = json.dumps({
        "username": username, "password_hash": password_hash,
        "role": role, "rider": rider
    }).encode()
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    req = urllib.request.Request(f"{url}/rest/v1/dashboard_users",
                                 data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False

def _supa_delete_user(username):
    url, key = _supa_creds()
    if not url or not key:
        return False
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    req = urllib.request.Request(
        f"{url}/rest/v1/dashboard_users?username=eq.{username}",
        headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False

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
def _supa_req(method: str, url: str, key: str, data: dict = None):
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "return=representation",
    }
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else []
    except Exception:
        return []

def supa_insert(table: str, data: dict, anon_key: str, supabase_url: str) -> bool:
    url = f"{supabase_url}/rest/v1/{table}"
    result = _supa_req("POST", url, anon_key, data)
    return isinstance(result, list) and len(result) > 0 or isinstance(result, dict)

def supa_fetch(table: str, service_key: str, supabase_url: str,
               filters: str = "status=eq.pending") -> list:
    url = f"{supabase_url}/rest/v1/{table}?{filters}&select=*&order=submitted_at.asc"
    result = _supa_req("GET", url, service_key)
    return result if isinstance(result, list) else []

def supa_update_status(table: str, record_id: int, status: str,
                       service_key: str, supabase_url: str):
    url = f"{supabase_url}/rest/v1/{table}?id=eq.{record_id}"
    _supa_req("PATCH", url, service_key, {"status": status})

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
    st.markdown("<p style='text-align:center;color:#7F8C8D;margin-bottom:32px'>WorldSSP</p>", unsafe_allow_html=True)

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
def _sql_to_df(conn, query):
    cur = conn.execute(query)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)

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
    """Fetch a Supabase table with pagination (1000 rows/page) until all rows retrieved."""
    CHUNK = 1000
    all_rows = []
    offset   = 0
    base_q   = f"select=*"
    if where: base_q += f"&{where}"
    if order: base_q += f"&order={order}"
    headers = {
        "apikey":        svc_key,
        "Authorization": f"Bearer {svc_key}",
        "Prefer":        "count=none",
    }
    while True:
        url = (f"{supa_url}/rest/v1/{table}"
               f"?{base_q}&limit={CHUNK}&offset={offset}")
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                chunk = json.loads(resp.read())
        except Exception:
            break
        if not chunk:
            break
        all_rows.extend(chunk)
        if len(chunk) < CHUNK:
            break          # 最終ページ
        offset += CHUNK
        if offset > 50000: # 安全上限
            break
    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()

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

# ── Run Log (setup data per run) ─────────────────
# Maps round_id in lap_times/DB → CIRCUIT name in Data_Bace_TS24_ORIGINAL
ROUND_CIRCUIT_MAP = {
    "ROUND1":  "PI",
    "ROUND2":  "PORTIMAO",
    "ROUND3":  "ASSEN",
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

def _coerce_dyn_numerics(df_dyn):
    num_cols = ["APEX Count","APEX Spd (km/h)","APEX SusF (mm)","APEX SusR (mm)",
                "APEX WhlF (N)","APEX WhlR (N)","APEX ax (m/s²)",
                "Pit Count","Pit Spd (km/h)","Pit SusF (mm)","Pit SusR (mm)",
                "Brk Count","Brk Spd (km/h)","Brk SusF (mm)","Brk SusR (mm)"]
    for c in num_cols:
        if c in df_dyn.columns:
            df_dyn[c] = pd.to_numeric(df_dyn[c], errors="coerce")
    if "Date" in df_dyn.columns:
        df_dyn["Date"] = df_dyn["Date"].astype(str)
    return df_dyn

@st.cache_data(ttl=120)
def _load_dynamics_data():
    """Load DYNAMICS_ANALYSIS and LAP_TIMES.
    Priority: TS24 DB Master.xlsx (local Mac) → JSON fallback (Streamlit Cloud)."""

    # ── 1. ローカル Excel（Mac実行時）───────────────────────
    if _DYNAMICS_EXCEL.exists():
        try:
            df_dyn = pd.read_excel(str(_DYNAMICS_EXCEL),
                                   sheet_name="DYNAMICS_ANALYSIS", header=1)
            df_dyn = _coerce_dyn_numerics(
                df_dyn.dropna(subset=["Rider"]).reset_index(drop=True))
        except Exception:
            df_dyn = pd.DataFrame()
        try:
            df_lt = pd.read_excel(str(_DYNAMICS_EXCEL),
                                  sheet_name="LAP_TIMES", header=1)
            df_lt = df_lt.dropna(how="all").reset_index(drop=True)
        except Exception:
            df_lt = pd.DataFrame()
        return df_dyn, df_lt

    # ── 2. JSON フォールバック（Streamlit Cloud）────────────
    # convert_dates=False: 日付文字列を datetime に自動変換しない（文字列のまま保持）
    # これにより LT の str(date) と DYN の Date_s が同じ '2025-01-01' 形式で一致する
    try:
        df_dyn = pd.read_json(str(_JSON_DYN), convert_dates=False) if _JSON_DYN.exists() else pd.DataFrame()
        if not df_dyn.empty:
            df_dyn = _coerce_dyn_numerics(df_dyn)
    except Exception:
        df_dyn = pd.DataFrame()
    try:
        df_lt = pd.read_json(str(_JSON_LT), convert_dates=False) if _JSON_LT.exists() else pd.DataFrame()
    except Exception:
        df_lt = pd.DataFrame()

    return df_dyn, df_lt


_JSON_LAP_SUS = SCRIPT_DIR / "lap_suspension_data.json"

@st.cache_data(ttl=120)
def _load_lap_suspension():
    """LAP_SUSPENSION データを読み込む。
    優先: TS24 DB Master.xlsx (ローカル) → ts24_unified.db → JSON フォールバック"""
    _NUM_COLS = ["LAP_TIME_S","APEX_CNT","APEX_SPD_AVG","APEX_SUSF_AVG","APEX_SUSR_AVG",
                 "BRK_CNT","BRK_SPD_AVG","BRK_SUSF_AVG","BRK_SUSR_AVG",
                 "FULLBRK_CNT","FULLBRK_SUSF","FULLBRK_SUSR",
                 "LAP_SUSF_MEAN","LAP_SUSF_MIN","LAP_SUSF_MAX","LAP_SUSR_MEAN","RUN_NO","LAP_NO"]

    def _coerce(df):
        df.columns = [c.upper() for c in df.columns]
        for c in _NUM_COLS:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(how="all").reset_index(drop=True)

    # 1. ローカル Excel
    if _DYNAMICS_EXCEL.exists():
        try:
            df = pd.read_excel(str(_DYNAMICS_EXCEL), sheet_name="LAP_SUSPENSION", header=1)
            return _coerce(df)
        except Exception:
            pass
    # 2. ローカル SQLite
    try:
        _udb = _DYNAMICS_EXCEL.parent / "ts24_unified.db"
        if _udb.exists():
            conn = sqlite3.connect(str(_udb))
            df = pd.read_sql("SELECT * FROM lap_suspension ORDER BY round,circuit,session,rider,run_no,lap_no", conn)
            conn.close()
            return _coerce(df)
    except Exception:
        pass
    # 3. JSON フォールバック（Streamlit Cloud）
    try:
        if _JSON_LAP_SUS.exists():
            df = pd.read_json(str(_JSON_LAP_SUS), convert_dates=False)
            return _coerce(df)
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


def _dyn_norm_circuit(c):
    c = str(c or "").upper().strip()
    if c in ("PHILLIPISLAND","PHILLIP ISLAND","PHI","AUSTRALIA","WORKSHOP","PHILLIP_ISLAND"):
        return "PHILLIP ISLAND"
    return c

def _dyn_norm_session(s):
    s = str(s or "").upper().strip()
    m = {"WUP":"WUP","WUP1":"WUP","WUP2":"WUP",
         "FP":"FP","FP1":"FP","FP2":"FP","L1":"FP","L2":"FP",
         "QP":"QP","QP1":"QP","QP2":"QP",
         "SP":"SP","RACE1":"RACE1","RACE2":"RACE2",
         "TEST_D1":"TEST_D1","TEST_D2":"TEST_D2"}
    return m.get(s, s)

# ── Color palette (Power BI style) ────────────────
DA77_COLOR = "#0078D4"   # Microsoft blue
JA52_COLOR = "#E74C3C"   # Red
PHASE_COLORS = {
    "PH1": "#C0392B",
    "PH2": "#E67E22",
    "PH3": "#F1C40F",
    "PH4": "#27AE60",
    "PH5": "#2980B9",
}
PHASE_LABELS = {
    "PH1": "PH1 Braking",
    "PH2": "PH2 Entry",
    "PH3": "PH3 Apex",
    "PH4": "PH4 Exit",
    "PH5": "PH5 Hi-Speed",
}

CHART_FONT = dict(family="Arial, sans-serif", size=12, color="#111111")

# ── Claude API helper ─────────────────────────────
CLAUDE_API_URL   = "https://api.anthropic.com/v1/messages"
CLAUDE_API_MODEL = "claude-sonnet-4-6"

def call_claude(api_key: str, user_msg: str, system_msg: str = "", max_tokens: int = 2000) -> str:
    payload = {
        "model": CLAUDE_API_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_msg}],
    }
    if system_msg:
        payload["system"] = system_msg
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        CLAUDE_API_URL, data=data,
        headers={
            "x-api-key":           api_key,
            "anthropic-version":   "2023-06-01",
            "content-type":        "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            return f"API Error {e.code}: {err.get('error', {}).get('message', body)}"
        except Exception:
            return f"API Error {e.code}: {body}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

# ══════════════════════════════════════════════════════════════
# RACE MEMORY SYSTEM — persistent knowledge across sessions
# ══════════════════════════════════════════════════════════════

def load_race_memory() -> dict:
    """Load persistent race memory. /tmp first (writable on Cloud), then repo."""
    default = {
        "version": 2,
        "circuit_insights": {},          # {CIRCUIT: {RIDER: [insight, ...]}}
        "global_insights": [],           # cross-circuit learnings
        "setup_learnings": [],           # {date, circuit, rider, insight, page}
        "conversation_summaries": [],    # {date, page, riders, summary}
    }
    for path in [_TMP_MEMORY, MEMORY_FILE]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Merge: fill missing keys from default
                for k, v in default.items():
                    if k not in data:
                        data[k] = v
                return data
            except Exception:
                pass
    return default

def save_race_memory(memory: dict):
    """Save memory to both /tmp (Cloud) and repo (local)."""
    blob = json.dumps(memory, ensure_ascii=False, indent=2)
    for path in [_TMP_MEMORY, MEMORY_FILE]:
        try:
            path.write_text(blob, encoding="utf-8")
        except Exception:
            pass

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

def build_memory_context(memory: dict, circuit: str, rider: str) -> str:
    """Build a memory context string to inject into system prompt."""
    lines = []

    # Circuit-specific insights for this rider
    if circuit and circuit != "All":
        c_insights = memory.get("circuit_insights", {}).get(circuit, {})
        for r in ([rider] if rider != "All" else list(c_insights.keys())):
            r_ins = c_insights.get(r, [])
            if r_ins:
                lines.append(f"[{circuit} / {r} — past insights]")
                lines.extend(f"  • {i}" for i in r_ins[-5:])

    # Recent global insights
    g_ins = memory.get("global_insights", [])
    if g_ins:
        lines.append("[Cross-circuit learnings]")
        lines.extend(f"  • {i}" for i in g_ins[-4:])

    # Recent conversation summaries
    summaries = memory.get("conversation_summaries", [])
    recent = [s for s in summaries[-6:] if
              (circuit == "All" or s.get("circuit") in ("All", circuit))]
    if recent:
        lines.append("[Recent analysis sessions]")
        for s in recent[-3:]:
            lines.append(f"  • [{s['date']}] {s['summary']}")

    if not lines:
        return ""
    return "\n\nPAST KNOWLEDGE BASE (use this to give more contextual answers):\n" + "\n".join(lines)


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


def chart_layout(fig, height=300, title=""):
    fig.update_layout(
        height=height,
        title=dict(
            text=title,
            font=dict(size=13, color="#222222", family="Arial, sans-serif"),
            x=0
        ),
        font=CHART_FONT,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F8F9FA",
        margin=dict(l=10, r=10, t=44, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            font=dict(color="#111111", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
        coloraxis_colorbar=dict(
            tickfont=dict(color="#111111"),
        ),
    )
    fig.update_xaxes(
        gridcolor="#E5E5E5",
        linecolor="#CCCCCC",
        tickfont=dict(color="#333333", size=11),
        title_font=dict(color="#333333"),
        zerolinecolor="#CCCCCC",
    )
    fig.update_yaxes(
        gridcolor="#E5E5E5",
        linecolor="#CCCCCC",
        tickfont=dict(color="#333333", size=11),
        title_font=dict(color="#333333"),
        zerolinecolor="#CCCCCC",
    )
    return fig

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

# ── Load data ─────────────────────────────────────
sessions, tags, results, sectors, laps = load_data()

# ── Race Memory — load once per session ───────────
if "race_memory" not in st.session_state:
    st.session_state["race_memory"] = load_race_memory()

# ── Floating Chat — injected after layout is known ────────────
# (called later, after _NAV and filters are resolved)

# ── Main layout: left nav column + right content column ──────
# Using columns instead of st.sidebar so the nav is always visible
_nav_col, _content_col = st.columns([1, 5], gap="small")

with _nav_col:
    st.markdown(
        "<div style='text-align:center;padding:10px 0 4px'>"
        "<span style='font-size:26px'>🏍</span><br>"
        "<span style='font-weight:800;font-size:16px;color:#0078D4;letter-spacing:1px'>TS24</span>"
        "<span style='font-size:12px;color:#666'> Set-UP Tool</span></div>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='text-align:center;font-size:11px;color:#999;margin:0 0 8px'>WorldSSP</p>",
        unsafe_allow_html=True
    )

    # ── Navigation Menu ──────────────────────────────
    NAV_ITEMS = [
        "📊  Problem Analysis",
        "🗺  Heatmap",
        "📈  Season Trend",
        "🏁  Race Results",
        "⏱  Race Pace",
        "📐  Lap Analysis",
        "🏎  2D Lap Data",
        "🔬  Suspension Dynamics",
        "📊  Lap Sus Stats",
        "🎯  Setup Target",
        "🔄  Corner Phase",
        "📋  Session Detail",
        "📉  Trend Analysis",
        "🔍  Problem→Solution",
        "🏆  Performance",
        "🤖  AI Advice",
        "💬  Setup Chat",
        "📤  Submit Data",
        "✅  Approvals",
        "👤  Accounts",
    ]
    nav_sel = st.radio("nav", NAV_ITEMS, label_visibility="collapsed", key="nav_menu")

    st.divider()

    st.markdown("**Rider**")
    all_riders = ["All", "DA77", "JA52"]
    sel_rider  = st.radio("", all_riders, horizontal=True, label_visibility="collapsed")

    st.markdown("**Circuit**")
    # Circuit options: collect from both race_results (track) + sessions (reports)
    circ_from_sessions = set(sessions["circuit"].dropna().unique().tolist())
    circ_from_results  = set(results["circuit"].dropna().str.upper().unique().tolist()) if not results.empty else set()
    all_circuits = sorted(circ_from_sessions | circ_from_results)
    circuits_list = ["All"] + all_circuits
    sel_circuit   = st.selectbox("", circuits_list, label_visibility="collapsed")

    st.divider()

    # ── Setup session filter (for Session Detail tab) — rider + circuit ──
    df_s = sessions.copy()
    df_t = tags.copy()
    if sel_rider != "All":
        df_s = df_s[df_s["rider"] == sel_rider]
        df_t = df_t[df_t["session_id"].isin(df_s["session_id"])]
    if sel_circuit != "All":
        df_s = df_s[df_s["circuit"].str.upper() == sel_circuit.upper()]
        df_t = df_t[df_t["session_id"].isin(df_s["session_id"])]

    # ── Whole-event filter (for Problem Analysis / Heatmap / Season Trend tabs) ──
    # Filter by circuit only — show all event tags regardless of rider selection
    df_s_event = sessions.copy()
    df_t_event = tags.copy()
    if sel_circuit != "All":
        df_s_event = df_s_event[df_s_event["circuit"].str.upper() == sel_circuit.upper()]
        df_t_event = df_t_event[df_t_event["session_id"].isin(df_s_event["session_id"])]

    # ── Track session filter (for KPI / Race Results tabs) ──
    # Each row in race_results = one session (FP/SP/WUP/RACE)
    df_rr = results.copy() if not results.empty else pd.DataFrame()
    if not df_rr.empty:
        if sel_rider != "All":
            df_rr = df_rr[df_rr["rider_id"] == sel_rider]
        if sel_circuit != "All":
            df_rr = df_rr[df_rr["circuit"].str.upper() == sel_circuit.upper()]

    n_track   = len(df_rr)
    n_da77    = len(df_rr[df_rr["rider_id"] == "DA77"]) if not df_rr.empty else 0
    n_ja52    = len(df_rr[df_rr["rider_id"] == "JA52"]) if not df_rr.empty else 0
    n_circuits = df_rr["circuit"].nunique() if not df_rr.empty else df_s["circuit"].nunique()

    st.caption(f"{n_track} track sessions / {len(df_s)} reports")

    st.divider()
    st.markdown("**Claude AI**")

    # Auto-load API key from config file on startup
    if "claude_api_key" not in st.session_state:
        cfg = load_config()
        st.session_state["claude_api_key"] = cfg.get("claude_api_key", "")

    api_key_input = st.text_input(
        "API Key (sk-ant-...)",
        value=st.session_state.get("claude_api_key", ""),
        type="password",
        label_visibility="visible",
        key="api_key_field",
        help="Anthropic API key — required for AI Advice and Setup Chat tabs",
    )
    if api_key_input != st.session_state.get("claude_api_key", ""):
        st.session_state["claude_api_key"] = api_key_input

    if st.button("💾 Save API Key", key="save_api_key", use_container_width=True):
        cfg = load_config()
        cfg["claude_api_key"] = st.session_state.get("claude_api_key", "")
        save_config(cfg)
        st.success("Saved!")

    claude_ready = bool(st.session_state.get("claude_api_key", ""))

    # ── User management (admin: ts24 only) ──
    current_user = st.session_state.get("current_user", "")
    current_role = get_user_role(current_user)
    current_rider = get_user_rider(current_user)

    st.divider()
    role_badge = {"admin": "🔑 Admin", "viewer": "👁 Viewer", "engineer": "🔧 Engineer"}.get(current_role, current_role)
    st.markdown(f"**{current_user}** · {role_badge}")
    if current_rider:
        st.caption(f"Assigned rider: {current_rider}")
    if st.button("🚪 Logout", key="logout_btn", use_container_width=True):
        st.session_state["authenticated"] = False
        st.session_state["current_user"]  = ""
        st.rerun()

    if current_role == "admin":
        with st.expander("☁️ Supabase Settings", expanded=False):
            cfg_s = load_config()
            svc_key_input = st.text_input(
                "Service Role Key",
                value=cfg_s.get("supabase_service_key", ""),
                type="password", key="svc_key"
            )
            gmail_u = st.text_input("Gmail address", value=cfg_s.get("gmail_user", ""), key="gmail_u")
            gmail_pw = st.text_input("Gmail App Password", value=cfg_s.get("gmail_app_password", ""),
                                     type="password", key="gmail_pw")
            if st.button("💾 Save Supabase Config", key="save_supa", use_container_width=True):
                cfg_s["supabase_service_key"] = svc_key_input
                cfg_s["gmail_user"] = gmail_u
                cfg_s["gmail_app_password"] = gmail_pw
                save_config(cfg_s)
                st.success("Saved!")

with _content_col:
    # ── KPI row ─────────────────────────────────────────────────
    # Track Sessions = race_results based (FP/SP/WUP/RACE track session units)
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Track Sessions", n_track)
    k2.metric("DA77 Sessions",  n_da77)
    k3.metric("JA52 Sessions",  n_ja52)
    k4.metric("Problem Tags",   len(df_t_event))
    k5.metric("Circuits",       n_circuits)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # ── Claude API Key — inline setup bar (shown when key not yet saved) ──
    if not claude_ready:
        with st.expander("🔑  Claude AI Setup — API Key Required for AI Advice & Setup Chat", expanded=True):
            col_k1, col_k2 = st.columns([4, 1])
            with col_k1:
                inline_key = st.text_input(
                    "Anthropic API Key (sk-ant-...)",
                    value="",
                    type="password",
                    key="inline_api_key",
                    label_visibility="visible",
                )
            with col_k2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                if st.button("Save & Apply", key="inline_save", type="primary"):
                    if inline_key.strip():
                        st.session_state["claude_api_key"] = inline_key.strip()
                        cfg = load_config()
                        cfg["claude_api_key"] = inline_key.strip()
                        save_config(cfg)
                        st.success("API key saved! Reloading...")
                        st.rerun()

    # ── Tabs ──────────────────────────────────────────
    # ── Role-based data filtering ──────────────────────────────────
    # Engineer role: show only their assigned rider's data
    _cur_user  = st.session_state.get("current_user", "")
    _cur_role  = get_user_role(_cur_user)
    _cur_rider = get_user_rider(_cur_user)

    if _cur_role == "engineer" and _cur_rider:
        df_s       = df_s[df_s["rider"] == _cur_rider]
        df_t       = df_t[df_t["session_id"].isin(df_s["session_id"])]
        df_s_event = df_s_event[df_s_event["rider"] == _cur_rider]
        df_t_event = df_t_event[df_t_event["session_id"].isin(df_s_event["session_id"])]
        if not df_rr.empty:
            df_rr = df_rr[df_rr["rider_id"] == _cur_rider]

    # ── Navigation routing (sidebar radio → content area) ──────────
    _NAV = nav_sel  # shorthand

    # ── Floating Chat — DOM-inject (no sidebar, no page reload) ──
    _snap_lines = []
    if sel_circuit != "All":
        _snap_lines.append(f"Circuit filter: {sel_circuit}")
    if sel_rider != "All":
        _snap_lines.append(f"Rider filter: {sel_rider}")
    _snap_lines.append(f"Sessions in view: {len(df_s)}")
    _snap_lines.append(f"Problem tags in view: {len(df_t_event)}")
    _page_ctx = {
        "page":          _NAV.strip().lstrip("📊🗺📈🏁⏱📐🏎🔬📊🎯📋📉🔍🏆🤖💬 ").strip(),
        "circuit":       sel_circuit,
        "rider":         sel_rider,
        "data_snapshot": "\n".join(_snap_lines),
    }
    render_float_chat_component(
        api_key  = st.session_state.get("claude_api_key", ""),
        memory   = st.session_state["race_memory"],
        page_ctx = _page_ctx,
    )

    # ═══════════════════════════════════════════════════
    # PAGE 1 — Problem Analysis
    # ═══════════════════════════════════════════════════
    if _NAV == "📊  Problem Analysis":
        col_l, col_r = st.columns(2, gap="medium")

        # ── Left: Tag frequency bar ──
        with col_l:
            st.markdown('<p class="section-title">Problem Tag Frequency</p>', unsafe_allow_html=True)
            tag_counts = (
                df_t_event.groupby("tag").size().reset_index(name="count")
                  .sort_values("count", ascending=True)
            )
            if not tag_counts.empty:
                # Color by phase
                phase_map = dict(zip(
                    tags["tag"].values, tags["phase"].values
                ))
                tag_counts["phase"] = tag_counts["tag"].map(phase_map)
                tag_counts["color"] = tag_counts["phase"].map(PHASE_COLORS).fillna("#AAAAAA")

                fig = go.Figure(go.Bar(
                    x=tag_counts["count"],
                    y=tag_counts["tag"],
                    orientation="h",
                    marker_color=tag_counts["color"],
                    text=tag_counts["count"],
                    textposition="outside",
                    textfont=dict(color="#111111", size=12),
                ))
                chart_layout(fig, height=320)
                fig.update_layout(xaxis_title="Sessions", yaxis_title="")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No tag data.")

        # ── Right: DA77 vs JA52 ──
        with col_r:
            st.markdown('<p class="section-title">DA77 vs JA52 Comparison</p>', unsafe_allow_html=True)
            # Merge tags for whole event (both riders) — show all regardless of rider selection
            merged = df_t_event.merge(df_s_event[["session_id", "rider"]], on="session_id", how="left")
            by_rider = merged.groupby(["tag", "rider"]).size().reset_index(name="count")
            if not by_rider.empty:
                # Sort tags by total
                tag_order = (
                    by_rider.groupby("tag")["count"].sum()
                      .sort_values(ascending=False).index.tolist()
                )
                fig2 = px.bar(
                    by_rider, x="count", y="tag", color="rider",
                    orientation="h", barmode="group",
                    color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                    category_orders={"tag": tag_order[::-1]},
                )
                chart_layout(fig2, height=320)
                fig2.update_layout(xaxis_title="Sessions", yaxis_title="")
                st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No data.")

        # ── Bottom: Phase distribution donut ──
        st.markdown('<p class="section-title">Phase Distribution</p>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 1, 2])

        phase_cnt = df_t_event.groupby("phase").size().reset_index(name="count")
        phase_cnt["label"] = phase_cnt["phase"].map(PHASE_LABELS).fillna(phase_cnt["phase"])

        with c1:
            # All riders donut
            if not phase_cnt.empty:
                fig_d = go.Figure(go.Pie(
                    labels=phase_cnt["label"],
                    values=phase_cnt["count"],
                    hole=0.55,
                    marker_colors=[PHASE_COLORS.get(p, "#AAA") for p in phase_cnt["phase"]],
                    textinfo="label+percent",
                    textfont=dict(size=11, color="#111111"),
                ))
                chart_layout(fig_d, height=240, title="All Riders")
                fig_d.update_layout(showlegend=False, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})

        with c2:
            # DA77 donut
            t_da = merged[merged["rider"] == "DA77"].groupby("phase").size().reset_index(name="count") if not merged.empty else pd.DataFrame()
            if not t_da.empty:
                t_da["label"] = t_da["phase"].map(PHASE_LABELS).fillna(t_da["phase"])
                fig_da = go.Figure(go.Pie(
                    labels=t_da["label"], values=t_da["count"], hole=0.55,
                    marker_colors=[PHASE_COLORS.get(p, "#AAA") for p in t_da["phase"]],
                    textinfo="label+percent",
                    textfont=dict(size=11, color="#111111"),
                ))
                chart_layout(fig_da, height=240, title="DA77")
                fig_da.update_layout(showlegend=False, margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig_da, use_container_width=True, config={"displayModeBar": False})

        with c3:
            # Grouped bar by phase per rider
            if not merged.empty:
                ph_rider = merged.groupby(["phase", "rider"]).size().reset_index(name="count")
                ph_rider["label"] = ph_rider["phase"].map(PHASE_LABELS).fillna(ph_rider["phase"])
                fig_ph = px.bar(
                    ph_rider, x="label", y="count", color="rider",
                    barmode="group",
                    color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                )
                chart_layout(fig_ph, height=240, title="Phase × Rider")
                fig_ph.update_layout(xaxis_title="", yaxis_title="Sessions")
                st.plotly_chart(fig_ph, use_container_width=True, config={"displayModeBar": False})

    # ═══════════════════════════════════════════════════
    # PAGE 2 — Heatmap
    # ═══════════════════════════════════════════════════
    elif _NAV == "🗺  Heatmap":
        st.markdown('<p class="section-title">Problem Frequency by Circuit & Phase</p>', unsafe_allow_html=True)

        merged_hm = df_t_event.merge(df_s_event[["session_id", "circuit", "rider"]], on="session_id", how="left")
        merged_hm = merged_hm[merged_hm["circuit"].notna() & merged_hm["phase"].notna()]

        col_h1, col_h2 = st.columns(2, gap="medium")

        def draw_heatmap(data, title, col):
            if data.empty:
                col.info("Not enough data.")
                return
            hm = data.groupby(["circuit", "phase"]).size().reset_index(name="n")
            pivot = hm.pivot(index="circuit", columns="phase", values="n").fillna(0)
            ordered = [c for c in ["PH1","PH2","PH3","PH4","PH5"] if c in pivot.columns]
            pivot = pivot[ordered]
            pivot.columns = [PHASE_LABELS.get(c, c) for c in pivot.columns]
            fig = px.imshow(
                pivot, text_auto=True,
                color_continuous_scale=["#EBF5FB","#1A5276"],
                aspect="auto",
            )
            chart_layout(fig, height=300, title=title)
            fig.update_layout(coloraxis_showscale=False, xaxis_title="", yaxis_title="")
            fig.update_traces(textfont=dict(size=13, color="#111111"))
            col.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        with col_h1:
            draw_heatmap(merged_hm, "All Riders", col_h1)
        with col_h2:
            if sel_rider != "All":
                draw_heatmap(merged_hm[merged_hm["rider"] == sel_rider], f"Rider: {sel_rider}", col_h2)
            else:
                draw_heatmap(merged_hm[merged_hm["rider"] == "DA77"], "DA77", col_h2)

        # Tag × Circuit detail
        st.markdown('<p class="section-title">Tag × Circuit Detail</p>', unsafe_allow_html=True)
        if not merged_hm.empty:
            tc = merged_hm.groupby(["tag", "circuit"]).size().reset_index(name="n")
            pivot2 = tc.pivot(index="tag", columns="circuit", values="n").fillna(0)
            fig2 = px.imshow(
                pivot2, text_auto=True,
                color_continuous_scale=["#EBF5FB","#154360"],
                aspect="auto",
            )
            chart_layout(fig2, height=350)
            fig2.update_layout(coloraxis_showscale=False, xaxis_title="Circuit", yaxis_title="")
            fig2.update_traces(textfont=dict(size=13, color="#111111"))
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    # ═══════════════════════════════════════════════════
    # PAGE 3 — Season Trend
    # ═══════════════════════════════════════════════════
    elif _NAV == "📈  Season Trend":
        st.markdown('<p class="section-title">Problem Count per Session (Season Progress)</p>', unsafe_allow_html=True)

        tps = df_t_event.groupby("session_id").size().reset_index(name="tag_count")
        trend = df_s_event[["session_id","session_date","rider","circuit","session_type","best_lap"]].merge(
            tps, on="session_id", how="left"
        ).fillna({"tag_count": 0}).sort_values("session_date")
        trend["label"] = trend["circuit"].fillna("?") + "\n" + trend["session_type"].fillna("")

        fig_t = px.line(
            trend, x="session_date", y="tag_count",
            color="rider", markers=True,
            color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
            hover_data={"circuit": True, "best_lap": True, "session_type": True, "tag_count": True},
            labels={"session_date": "", "tag_count": "Problem Tags", "rider": "Rider"},
        )
        fig_t.update_traces(marker=dict(size=9), line=dict(width=2.5))
        chart_layout(fig_t, height=300)
        fig_t.add_annotation(
            text="↓ Lower is better", xref="paper", yref="paper",
            x=0.01, y=0.97, showarrow=False,
            font=dict(size=10, color="#999")
        )
        st.plotly_chart(fig_t, use_container_width=True, config={"displayModeBar": False})

        # Stacked bar: phase over time
        st.markdown('<p class="section-title">Phase Breakdown Over Season</p>', unsafe_allow_html=True)
        merged_trend = df_t_event.merge(df_s_event[["session_id","session_date","circuit"]], on="session_id", how="left")
        merged_trend = merged_trend.sort_values("session_date")
        if not merged_trend.empty:
            ph_time = merged_trend.groupby(["session_date", "phase"]).size().reset_index(name="count")
            ph_time["phase_label"] = ph_time["phase"].map(PHASE_LABELS).fillna(ph_time["phase"])
            # Sort phases consistently
            ph_order = list(PHASE_LABELS.values())
            fig_st = px.bar(
                ph_time, x="session_date", y="count", color="phase_label",
                barmode="stack",
                color_discrete_map={v: PHASE_COLORS[k] for k, v in PHASE_LABELS.items()},
                category_orders={"phase_label": ph_order},
                labels={"session_date": "", "count": "Tags", "phase_label": "Phase"},
            )
            chart_layout(fig_st, height=260)
            fig_st.update_layout(xaxis_tickangle=-30)
            st.plotly_chart(fig_st, use_container_width=True, config={"displayModeBar": False})

    # ═══════════════════════════════════════════════════
    # PAGE 4 — Race Results (Official PDFs)
    # ═══════════════════════════════════════════════════
    elif _NAV == "🏁  Race Results":
        if results.empty:
            st.info("No official results data yet. Add PDFs to 07_RESULTS/ and run result_sync.py.")
        else:
            # Race Results tab uses df_rr (already filtered by sidebar)
            df_r = df_rr.copy() if not df_rr.empty else results.copy()

            # ── KPI row ──
            st.markdown('<p class="section-title">Round Performance Overview</p>', unsafe_allow_html=True)
            rounds = sorted(results["round_no"].dropna().unique())

            # Round display: "ROUND1 · 2026 | Phillip Island"
            CIRCUIT_DISP = {
                "PHILLIPISLAND": "Phillip Island",
                "PHILLIP":       "Phillip Island",
                "ESTORIL":       "Estoril",
                "JEREZ":         "Jerez",
                "PORTIMAO":      "Portimão",
                "ASSEN":         "Assen",
            }
            def format_round(r):
                if r == "All":
                    return "All"
                sub = results[results["round_no"] == r]
                year, circ = "", ""
                if not sub.empty:
                    row0 = sub.iloc[0]
                    edate = row0.get("event_date") or ""
                    if edate:
                        year = str(edate)[:4]
                    raw_circ = str(row0.get("circuit") or "").upper()
                    circ = CIRCUIT_DISP.get(raw_circ, raw_circ.capitalize())
                label = r
                if year:
                    label += f"  ·  {year}"
                if circ:
                    label += f"  |  {circ}"
                return label

            sel_round = st.selectbox("Round", ["All"] + list(rounds),
                                     format_func=format_round,
                                     index=len(rounds), label_visibility="visible")
            if sel_round != "All":
                df_r = df_r[df_r["round_no"] == sel_round]
                df_sec = sectors[sectors["round_id"].str.startswith(sel_round)] if not sectors.empty else pd.DataFrame()
            else:
                df_sec = sectors.copy()

            # Session result cards
            session_order = ["FP", "SP", "WUP", "RACE1", "RACE2"]
            sessions_avail = [s for s in session_order if s in df_r["session_type"].values]
            if sessions_avail:
                cols = st.columns(len(sessions_avail))
                for col, ses in zip(cols, sessions_avail):
                    sub = df_r[df_r["session_type"] == ses]
                    with col:
                        st.markdown(f'<p class="section-title">{ses}</p>', unsafe_allow_html=True)
                        for _, row in sub.iterrows():
                            rid   = row.get("rider_id", "?")
                            pos   = row.get("position")
                            bl    = row.get("best_lap", "—")
                            gap   = row.get("gap_to_top")
                            top   = row.get("top_time", "—")
                            gpos  = row.get("grid_position")
                            r2g   = row.get("race2_grid")
                            color = DA77_COLOR if rid == "DA77" else JA52_COLOR
                            st.markdown(
                                f'<div style="background:#fff;border-left:4px solid {color};'
                                f'padding:10px 14px;border-radius:4px;margin-bottom:8px;">'
                                f'<b style="color:{color}">{rid}</b>'
                                f'<span style="float:right;font-size:22px;font-weight:700;color:#111">P{pos or "?"}</span><br>'
                                f'<span style="font-size:13px;color:#333">Best: <b>{bl}</b></span><br>'
                                f'<span style="font-size:12px;color:#666">Gap: +{gap or "—"}s &nbsp;|&nbsp; Top: {top}</span>'
                                + (f'<br><span style="font-size:11px;color:#888">Grid: P{gpos}</span>' if gpos else '')
                                + (f'&nbsp;<span style="font-size:11px;color:#0078D4">→ Race2 Grid: P{r2g}</span>' if r2g else '')
                                + '</div>',
                                unsafe_allow_html=True
                            )

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # ── Gap to top trend ──
            st.markdown('<p class="section-title">Gap to P1 by Session</p>', unsafe_allow_html=True)
            gap_df = df_r[df_r["gap_to_top"].notna()].copy()
            if not gap_df.empty:
                gap_df["session_label"] = gap_df["round_no"] + " " + gap_df["session_type"]
                fig_gap = px.bar(
                    gap_df, x="session_label", y="gap_to_top", color="rider_id",
                    barmode="group",
                    color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                    labels={"session_label": "", "gap_to_top": "Gap to P1 (sec)", "rider_id": "Rider"},
                    text="gap_to_top",
                )
                fig_gap.update_traces(texttemplate="+%{text:.3f}s", textposition="outside",
                                      textfont=dict(color="#111111", size=11))
                chart_layout(fig_gap, height=280)
                fig_gap.update_layout(yaxis_title="Gap to P1 (sec)")
                st.plotly_chart(fig_gap, use_container_width=True, config={"displayModeBar": False})

            # ── Sector analysis ──
            if not df_sec.empty:
                st.markdown('<p class="section-title">Race Sector Analysis — Gap to Sector Best</p>', unsafe_allow_html=True)
                sec_pivot = df_sec[["rider_id","sector","gap_to_sector_top","sector_rank"]].copy()
                if not sec_pivot.empty:
                    c1, c2 = st.columns(2, gap="medium")
                    with c1:
                        fig_sec = px.bar(
                            sec_pivot, x="sector", y="gap_to_sector_top", color="rider_id",
                            barmode="group",
                            color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                            labels={"sector":"Sector","gap_to_sector_top":"Gap (sec)","rider_id":"Rider"},
                            text="gap_to_sector_top",
                        )
                        fig_sec.update_traces(texttemplate="+%{text:.3f}s", textposition="outside",
                                              textfont=dict(color="#111111", size=11))
                        chart_layout(fig_sec, height=280, title="Gap to Sector Best")
                        st.plotly_chart(fig_sec, use_container_width=True, config={"displayModeBar": False})
                    with c2:
                        fig_rnk = px.bar(
                            sec_pivot, x="sector", y="sector_rank", color="rider_id",
                            barmode="group",
                            color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                            labels={"sector":"Sector","sector_rank":"Rank","rider_id":"Rider"},
                            text="sector_rank",
                        )
                        fig_rnk.update_traces(texttemplate="P%{text}", textposition="outside",
                                              textfont=dict(color="#111111", size=11))
                        chart_layout(fig_rnk, height=280, title="Sector Rank")
                        fig_rnk.update_yaxes(autorange="reversed")
                        st.plotly_chart(fig_rnk, use_container_width=True, config={"displayModeBar": False})

            # ── Cancelled laps note ──
            cancelled = df_r[df_r["cancelled_laps"] > 0][["round_no","session_type","rider_id","cancelled_laps","notes"]]
            if not cancelled.empty:
                st.markdown('<p class="section-title">Cancelled Laps</p>', unsafe_allow_html=True)
                for _, r in cancelled.iterrows():
                    st.markdown(
                        f'<div style="background:#FFF3CD;border-left:4px solid #F0AD00;'
                        f'padding:8px 14px;border-radius:4px;margin-bottom:6px;font-size:13px;">'
                        f'⚠️ <b>{r["rider_id"]}</b> {r["round_no"]} {r["session_type"]} — '
                        f'{int(r["cancelled_laps"])}x cancelled &nbsp;|&nbsp; {r["notes"] or ""}'
                        f'</div>',
                        unsafe_allow_html=True
                    )


    # ═══════════════════════════════════════════════════
    # PAGE 5 — Race Pace
    # ═══════════════════════════════════════════════════
    elif _NAV == "⏱  Race Pace":

        def fmt_laptime(sec):
            """97.901 → '1:37.90'"""
            if sec is None or pd.isna(sec):
                return "—"
            m = int(sec // 60)
            s = sec - m * 60
            return f"{m}:{s:05.2f}"

        if laps.empty:
            st.info("No lap time data. Run lap_sync.py first.")
        else:
            # ── Filter row 1: Round / Session / pit display ──
            fc1, fc2, fc3 = st.columns([2, 2, 1])

            available_rounds = sorted(laps["round_id"].unique())
            sel_rp_round = fc1.selectbox(
                "Round", available_rounds,
                index=len(available_rounds) - 1,
                key="rp_round"
            )

            avail_sessions = sorted(
                laps[laps["round_id"] == sel_rp_round]["session_type"].unique()
            )
            sel_rp_session = fc2.selectbox(
                "Session", avail_sessions,
                key="rp_session"
            )

            show_invalid = fc3.checkbox("Show pit/cancelled", value=False, key="rp_invalid")

            # Data for selected session (base filter)
            df_lp_base = laps[
                (laps["round_id"] == sel_rp_round) &
                (laps["session_type"] == sel_rp_session)
            ].copy()

            # Rider labels (number + name) — all riders regardless of is_valid
            rider_labels = {
                r: f"#{r} {df_lp_base[df_lp_base['rider_num']==r]['rider_name'].iloc[0]}"
                for r in df_lp_base["rider_num"].unique()
            }
            df_lp_base["rider_label"] = df_lp_base["rider_num"].map(rider_labels)

            # ── Filter row 2: Compare rider selection ──
            COMPARE_PALETTE = [
                "#8E44AD", "#16A085", "#D35400", "#2C3E50",
                "#F39C12", "#1ABC9C", "#884EA0", "#CA6F1E",
            ]
            field_nums_all = sorted([n for n in df_lp_base["rider_num"].unique() if n not in (77, 52)])
            field_label_list = [rider_labels.get(n, f"#{n}") for n in field_nums_all]
            field_label_to_num = {rider_labels.get(n, f"#{n}"): n for n in field_nums_all}

            sel_compare_labels = st.multiselect(
                "Compare Riders (Highlighted)",
                options=field_label_list,
                default=[],
                key="rp_compare",
                help="Highlight up to 8 riders other than DA77/JA52 in color for comparison",
            )
            compare_nums = [field_label_to_num[l] for l in sel_compare_labels]
            compare_colors = {n: COMPARE_PALETTE[i % len(COMPARE_PALETTE)]
                              for i, n in enumerate(compare_nums)}

            # Apply is_valid filter
            df_lp = df_lp_base.copy()
            if not show_invalid:
                df_lp = df_lp[df_lp["is_valid"] == 1]

            # Check if DA77 / JA52 exist in data
            has_da77 = 77 in df_lp["rider_num"].values
            has_ja52 = 52 in df_lp["rider_num"].values

            # ── KPI ──
            kp1, kp2, kp3, kp4 = st.columns(4)
            best_all  = df_lp[df_lp["is_valid"] == 1]["lap_time"].min()
            best_da77 = df_lp[(df_lp["rider_num"] == 77) & (df_lp["is_valid"] == 1)]["lap_time"].min() if has_da77 else None
            best_ja52 = df_lp[(df_lp["rider_num"] == 52) & (df_lp["is_valid"] == 1)]["lap_time"].min() if has_ja52 else None
            total_riders = df_lp["rider_num"].nunique()

            kp1.metric("Session Best",  fmt_laptime(best_all))
            kp2.metric("DA77 Best",     fmt_laptime(best_da77) if best_da77 else "—")
            kp3.metric("JA52 Best",     fmt_laptime(best_ja52) if best_ja52 else "—")
            kp4.metric("Riders in Data", total_riders)

            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

            # ── CHART 1: Lap Time Evolution ────────────────────────────
            st.markdown('<p class="section-title">Lap Time Evolution</p>', unsafe_allow_html=True)

            fig_pace = go.Figure()

            # Draw field riders: gray background + highlighted color for selected compare riders
            field_nums = [n for n in df_lp["rider_num"].unique() if n not in (77, 52)]
            for rnum in field_nums:
                df_r = df_lp[df_lp["rider_num"] == rnum].sort_values("lap_no")
                lbl  = rider_labels.get(rnum, f"#{rnum}")
                _cd  = df_r["lap_time"].apply(fmt_laptime).values

                if rnum in compare_nums:
                    col = compare_colors[rnum]
                    fig_pace.add_trace(go.Scatter(
                        x=df_r["lap_no"], y=df_r["lap_time"],
                        mode="lines+markers", name=lbl,
                        line=dict(color=col, width=2),
                        marker=dict(size=6, color=col),
                        customdata=_cd,
                        hovertemplate=f"<b>{lbl}</b><br>Lap %{{x}}: %{{customdata}}<extra></extra>",
                    ))
                else:
                    fig_pace.add_trace(go.Scatter(
                        x=df_r["lap_no"], y=df_r["lap_time"],
                        mode="lines+markers", name=lbl,
                        line=dict(color="#CCCCCC", width=1),
                        marker=dict(size=4, color="#CCCCCC"),
                        customdata=_cd,
                        hovertemplate=f"<b>{lbl}</b><br>Lap %{{x}}: %{{customdata}}<extra></extra>",
                        legendgroup="field", showlegend=False,
                    ))

            # Highlight DA77 in blue
            if has_da77:
                df_da = df_lp[df_lp["rider_num"] == 77].sort_values("lap_no")
                df_da_v = df_da[df_da["is_valid"] == 1]
                df_da_i = df_da[df_da["is_valid"] == 0]
                fig_pace.add_trace(go.Scatter(
                    x=df_da_v["lap_no"], y=df_da_v["lap_time"],
                    mode="lines+markers", name="DA77 D.Aegerter",
                    line=dict(color=DA77_COLOR, width=2.5),
                    marker=dict(size=7, color=DA77_COLOR),
                    customdata=df_da_v["lap_time"].apply(fmt_laptime).values,
                    hovertemplate="<b>DA77</b> Lap %{x}: %{customdata}<extra></extra>",
                ))
                if not df_da_i.empty:
                    _da_i_cd = list(zip(df_da_i["flag"], df_da_i["lap_time"].apply(fmt_laptime)))
                    fig_pace.add_trace(go.Scatter(
                        x=df_da_i["lap_no"], y=df_da_i["lap_time"],
                        mode="markers", name="DA77 pit/cancel",
                        marker=dict(size=8, color=DA77_COLOR, symbol="x", opacity=0.5),
                        customdata=_da_i_cd,
                        hovertemplate="<b>DA77 [%{customdata[0]}]</b> Lap %{x}: %{customdata[1]}<extra></extra>",
                        showlegend=False,
                    ))
            else:
                fig_pace.add_annotation(
                    text="DA77: no data in this PDF",
                    xref="paper", yref="paper", x=0.01, y=0.95,
                    showarrow=False, font=dict(size=11, color=DA77_COLOR),
                )

            # Highlight JA52 in red
            if has_ja52:
                df_ja = df_lp[df_lp["rider_num"] == 52].sort_values("lap_no")
                df_ja_v = df_ja[df_ja["is_valid"] == 1]
                df_ja_i = df_ja[df_ja["is_valid"] == 0]
                fig_pace.add_trace(go.Scatter(
                    x=df_ja_v["lap_no"], y=df_ja_v["lap_time"],
                    mode="lines+markers", name="JA52 J.Alcoba",
                    line=dict(color=JA52_COLOR, width=2.5),
                    marker=dict(size=7, color=JA52_COLOR),
                    customdata=df_ja_v["lap_time"].apply(fmt_laptime).values,
                    hovertemplate="<b>JA52</b> Lap %{x}: %{customdata}<extra></extra>",
                ))
                if not df_ja_i.empty:
                    _ja_i_cd = list(zip(df_ja_i["flag"], df_ja_i["lap_time"].apply(fmt_laptime)))
                    fig_pace.add_trace(go.Scatter(
                        x=df_ja_i["lap_no"], y=df_ja_i["lap_time"],
                        mode="markers", name="JA52 pit/cancel",
                        marker=dict(size=8, color=JA52_COLOR, symbol="x", opacity=0.5),
                        customdata=_ja_i_cd,
                        hovertemplate="<b>JA52 [%{customdata[0]}]</b> Lap %{x}: %{customdata[1]}<extra></extra>",
                        showlegend=False,
                    ))
            else:
                fig_pace.add_annotation(
                    text="JA52: no data in this PDF",
                    xref="paper", yref="paper", x=0.01, y=0.88,
                    showarrow=False, font=dict(size=11, color=JA52_COLOR),
                )

            # Draw horizontal session best line
            if best_all:
                fig_pace.add_hline(
                    y=best_all, line_dash="dot",
                    line_color="#27AE60", line_width=1,
                    annotation_text=f"Best {fmt_laptime(best_all)}",
                    annotation_font_color="#27AE60",
                    annotation_position="top right",
                )

            # Custom Y-axis ticks in mm:ss format
            if not df_lp.empty:
                y_min = df_lp[df_lp["is_valid"]==1]["lap_time"].quantile(0.02) if not df_lp[df_lp["is_valid"]==1].empty else 90
                y_max = df_lp[df_lp["is_valid"]==1]["lap_time"].quantile(0.98) if not df_lp[df_lp["is_valid"]==1].empty else 120
                margin = (y_max - y_min) * 0.3
                tick_vals = [y_min + i * (y_max - y_min) / 6 for i in range(7)]
                tick_text = [fmt_laptime(v) for v in tick_vals]
                fig_pace.update_yaxes(
                    tickvals=tick_vals, ticktext=tick_text,
                    range=[y_min - margin * 0.2, y_max + margin],
                )

            chart_layout(fig_pace, height=380)
            fig_pace.update_layout(
                xaxis_title="Lap",
                yaxis_title="Lap Time",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_pace, use_container_width=True, config={"displayModeBar": False})

            # ── CHART 2: Sector Time Comparison ──────────────────────
            _sector_targets = []
            if has_da77: _sector_targets.append((77, "DA77", DA77_COLOR))
            if has_ja52: _sector_targets.append((52, "JA52", JA52_COLOR))
            for rnum in compare_nums[:2]:
                _sector_targets.append((rnum, rider_labels.get(rnum, f"#{rnum}"), compare_colors[rnum]))

            if _sector_targets:
                st.markdown('<p class="section-title">Sector Time Evolution</p>', unsafe_allow_html=True)
                _n_sec_cols = min(len(_sector_targets), 2)
                _sec_cols = st.columns(_n_sec_cols, gap="medium")

                for col_idx, (rnum, rname, color) in enumerate(_sector_targets):
                    col = _sec_cols[col_idx % _n_sec_cols]
                    df_r = df_lp[(df_lp["rider_num"] == rnum) & (df_lp["is_valid"] == 1)].sort_values("lap_no")
                    if df_r.empty:
                        col.info(f"{rname}: no data")
                        continue
                    fig_sec = go.Figure()
                    seg_colors = {"seg1": "#C0392B", "seg2": "#E67E22", "seg3": "#27AE60", "seg4": "#2980B9"}
                    seg_labels = {"seg1": "S1", "seg2": "S2", "seg3": "S3", "seg4": "S4"}
                    _sec_all_vals = []
                    for seg, sc in seg_colors.items():
                        if df_r[seg].notna().any():
                            _seg_cd = df_r[seg].apply(lambda v: fmt_laptime(v) if pd.notna(v) else "—").values
                            fig_sec.add_trace(go.Scatter(
                                x=df_r["lap_no"], y=df_r[seg],
                                mode="lines+markers", name=seg_labels[seg],
                                line=dict(color=sc, width=2),
                                marker=dict(size=5),
                                customdata=_seg_cd,
                                hovertemplate=f"{seg_labels[seg]} Lap %{{x}}: %{{customdata}}<extra></extra>",
                            ))
                            _sec_all_vals.extend(df_r[seg].dropna().tolist())
                    # Y-axis: M:SS.mmm ticks
                    if _sec_all_vals:
                        _sv_min, _sv_max = min(_sec_all_vals), max(_sec_all_vals)
                        _sv_pad = max((_sv_max - _sv_min) * 0.2, 0.5)
                        _sv_tick = [_sv_min + i * (_sv_max - _sv_min) / 5 for i in range(6)]
                        fig_sec.update_yaxes(
                            tickvals=_sv_tick,
                            ticktext=[fmt_laptime(v) for v in _sv_tick],
                            range=[_sv_min - _sv_pad, _sv_max + _sv_pad],
                        )
                    chart_layout(fig_sec, height=240, title=f"{rname} — Sector Times per Lap")
                    fig_sec.update_layout(xaxis_title="Lap", yaxis_title="Sector Time")
                    col.plotly_chart(fig_sec, use_container_width=True, config={"displayModeBar": False})

            # ── CHART 3: Lap Gap (vs. session best) ──────────────────
            st.markdown('<p class="section-title">Gap to Session Best Lap (per lap)</p>', unsafe_allow_html=True)

            gap_traces = []
            _gap_targets = [(77, "DA77", DA77_COLOR), (52, "JA52", JA52_COLOR)]
            for rnum in compare_nums:
                _gap_targets.append((rnum, rider_labels.get(rnum, f"#{rnum}"), compare_colors[rnum]))
            for rnum, rname, color in _gap_targets:
                df_r = df_lp[(df_lp["rider_num"] == rnum) & (df_lp["is_valid"] == 1)].sort_values("lap_no")
                if df_r.empty:
                    continue
                df_r = df_r.copy()
                df_r["gap"] = df_r["lap_time"] - best_all
                gap_traces.append((df_r, rname, color))

            if gap_traces:
                fig_gap = go.Figure()
                for df_r, rname, color in gap_traces:
                    fig_gap.add_trace(go.Bar(
                        x=df_r["lap_no"], y=df_r["gap"],
                        name=rname,
                        marker_color=color,
                        text=[f"+{v:.3f}" for v in df_r["gap"]],
                        textposition="outside",
                        textfont=dict(size=10, color="#333"),
                    ))
                fig_gap.add_hline(y=0, line_color="#27AE60", line_width=1.5)
                chart_layout(fig_gap, height=260)
                fig_gap.update_layout(
                    xaxis_title="Lap", yaxis_title="Gap to Best (s)",
                    barmode="group",
                )
                st.plotly_chart(fig_gap, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("No gap data for DA77/JA52 — field data only session.")

            # ── CHART: Pace Comparison (Avg & Best) ──────────────────
            if compare_nums:
                st.markdown('<p class="section-title">Pace Comparison — vs Selected Competitors</p>',
                            unsafe_allow_html=True)

                pace_rows = []
                _pace_targets = []
                if has_da77: _pace_targets.append((77, "DA77", DA77_COLOR))
                if has_ja52: _pace_targets.append((52, "JA52", JA52_COLOR))
                for rnum in compare_nums:
                    _pace_targets.append((rnum, rider_labels.get(rnum, f"#{rnum}"), compare_colors[rnum]))

                for rnum, rname, color in _pace_targets:
                    df_r = df_lp[(df_lp["rider_num"] == rnum) & (df_lp["is_valid"] == 1)]
                    if df_r.empty:
                        continue
                    times = df_r["lap_time"].dropna().values
                    if len(times) == 0:
                        continue
                    top_n = max(1, len(times) // 3)
                    race_pace = float(np.sort(times)[:top_n].mean())
                    pace_rows.append({
                        "Rider":    rname,
                        "color":    color,
                        "Best":     float(df_r["lap_time"].min()),
                        "RacePace": race_pace,
                        "Avg":      float(df_r["lap_time"].mean()),
                        "Laps":     len(times),
                    })

                if pace_rows:
                    df_pace = pd.DataFrame(pace_rows)
                    pc1, pc2 = st.columns(2, gap="medium")

                    with pc1:
                        fig_rp = go.Figure()
                        for _, row in df_pace.iterrows():
                            fig_rp.add_trace(go.Bar(
                                x=[row["Rider"]], y=[row["RacePace"]],
                                name=row["Rider"],
                                marker_color=row["color"],
                                text=[fmt_laptime(row["RacePace"])],
                                textposition="outside",
                                textfont=dict(size=11),
                                showlegend=False,
                            ))
                        _rp_vals = df_pace["RacePace"].values
                        _rp_lo = float(np.min(_rp_vals)) - 0.5
                        _rp_hi = float(np.max(_rp_vals)) + 0.5
                        _rp_step = 0.5
                        _rp_ticks = list(np.arange(
                            np.floor(_rp_lo / _rp_step) * _rp_step,
                            np.ceil(_rp_hi / _rp_step) * _rp_step + _rp_step,
                            _rp_step,
                        ))
                        fig_rp.update_layout(
                            yaxis=dict(
                                tickvals=_rp_ticks,
                                ticktext=[fmt_laptime(v) for v in _rp_ticks],
                                range=[_rp_hi + 0.3, _rp_lo - 0.3],
                                title="Race Pace (Top 1/3 avg)",
                            ),
                            height=300,
                            margin=dict(l=60, r=20, t=30, b=40),
                            plot_bgcolor="#FAFAFA",
                            paper_bgcolor="white",
                            title_text="Race Pace (Top 1/3 Laps Avg)",
                        )
                        pc1.plotly_chart(fig_rp, use_container_width=True,
                                         config={"displayModeBar": False})

                    with pc2:
                        _da77_best = df_pace[df_pace["Rider"] == "DA77"]["Best"].values
                        ref_best = float(_da77_best[0]) if len(_da77_best) > 0 else float(df_pace["Best"].min())
                        fig_gap2 = go.Figure()
                        for _, row in df_pace.iterrows():
                            delta = row["RacePace"] - ref_best
                            fig_gap2.add_trace(go.Bar(
                                x=[row["Rider"]], y=[delta],
                                name=row["Rider"],
                                marker_color=row["color"],
                                text=[f"+{delta:.3f}s" if delta >= 0 else f"{delta:.3f}s"],
                                textposition="outside",
                                textfont=dict(size=11),
                                showlegend=False,
                            ))
                        fig_gap2.add_hline(y=0, line_color="#27AE60", line_width=1.5)
                        fig_gap2.update_layout(
                            yaxis_title="Race Pace Δ vs DA77 Best (s)",
                            height=300,
                            margin=dict(l=50, r=20, t=30, b=40),
                            plot_bgcolor="#FAFAFA",
                            paper_bgcolor="white",
                            title_text="Race Pace Gap vs DA77",
                        )
                        pc2.plotly_chart(fig_gap2, use_container_width=True,
                                         config={"displayModeBar": False})

                    df_pace_disp = df_pace[["Rider","Best","RacePace","Avg","Laps"]].copy()
                    df_pace_disp["Best"]     = df_pace_disp["Best"].apply(fmt_laptime)
                    df_pace_disp["RacePace"] = df_pace_disp["RacePace"].apply(fmt_laptime)
                    df_pace_disp["Avg"]      = df_pace_disp["Avg"].apply(fmt_laptime)
                    df_pace_disp.columns     = ["Rider","Best Lap","Race Pace (top 1/3)","Avg Lap","Laps"]
                    st.dataframe(df_pace_disp, use_container_width=True, hide_index=True)

            # ── Statistics Summary ───────────────────────────────────
            st.markdown('<p class="section-title">Lap Time Statistics</p>', unsafe_allow_html=True)

            stat_rows = []
            for rnum in sorted(df_lp["rider_num"].unique()):
                df_r = df_lp[(df_lp["rider_num"] == rnum) & (df_lp["is_valid"] == 1)]
                if df_r.empty:
                    continue
                lbl = rider_labels.get(rnum, f"#{rnum}")
                tag = "★ DA77" if rnum == 77 else ("★ JA52" if rnum == 52 else "")
                stat_rows.append({
                    "Rider": lbl,
                    "Tag": tag,
                    "Best":   fmt_laptime(df_r["lap_time"].min()),
                    "Avg":    fmt_laptime(df_r["lap_time"].mean()),
                    "Worst":  fmt_laptime(df_r["lap_time"].max()),
                    "Laps":   len(df_r),
                    "Δ Best (s)": round(df_r["lap_time"].min() - best_all, 3),
                })

            if stat_rows:
                df_stat = pd.DataFrame(stat_rows).sort_values("Δ Best (s)")
                # Show DA77/JA52 at the top
                df_star = df_stat[df_stat["Tag"] != ""]
                df_field = df_stat[df_stat["Tag"] == ""]
                df_show = pd.concat([df_star, df_field]).drop(columns=["Tag"]).reset_index(drop=True)
                st.dataframe(df_show, use_container_width=True, hide_index=True)


    # ═══════════════════════════════════════════════════
    # PAGE 5.5 — Lap Analysis (3-Metric + Performance Evolution)
    # ═══════════════════════════════════════════════════
    elif _NAV == "📐  Lap Analysis":
        st.markdown('<p class="section-title">📐 Lap Analysis — Performance Metrics & Evolution</p>',
                    unsafe_allow_html=True)

        if laps.empty:
            st.info("No lap time data available.")
        else:
            # ── Round & Rider selectors ──────────────────────
            la1, la2 = st.columns([2, 1])
            with la1:
                avail_rounds = sorted(laps["round_id"].unique())
                sel_la_round = st.selectbox("Round", avail_rounds,
                                            index=len(avail_rounds) - 1, key="la_round")
            with la2:
                sel_la_rider = st.radio("Rider", ["Both", "DA77", "JA52"],
                                        horizontal=True, key="la_rider")

            df_round = laps[laps["round_id"] == sel_la_round].copy()
            SESSION_ORDER = ["FP", "SP", "WUP1", "WUP2", "RACE1", "RACE2"]
            RIDER_NUM     = {"DA77": 77, "JA52": 52}
            RIDER_COLOR   = {"DA77": "#0078D4", "JA52": "#E74C3C"}
            riders_to_show = (["DA77", "JA52"] if sel_la_rider == "Both"
                               else [sel_la_rider])

            if df_round.empty:
                st.warning("No data for the selected round.")
            else:
                # ── Normalise column types (Supabase returns JSON; ensure numeric) ──
                for _c in ["lap_time", "rider_num", "lap_no", "is_valid"]:
                    if _c in df_round.columns:
                        df_round[_c] = pd.to_numeric(df_round[_c], errors="coerce")

                df_valid = (df_round[df_round["is_valid"] == 1]
                            if "is_valid" in df_round.columns else df_round)

                # ── 107% filter: remove out-laps / cool-down laps ──
                # Uses transform() so session_type column is preserved in result
                if not df_valid.empty and "lap_time" in df_valid.columns:
                    _mask = (df_valid
                             .groupby("session_type")["lap_time"]
                             .transform(lambda x: x <= 1.07 * x.min()))
                    df_valid = df_valid[_mask]

                sessions_avail = [s for s in SESSION_ORDER
                                  if s in df_valid["session_type"].unique()]

                # ── Build metrics table ──────────────────────
                def fmt_lap(s):
                    if s is None or (isinstance(s, float) and pd.isna(s)):
                        return "—"
                    m = int(s) // 60
                    return f"{m}:{s % 60:05.2f}"

                rows = []
                for ses in sessions_avail:
                    df_ses = df_valid[df_valid["session_type"] == ses]
                    p1_time = df_ses["lap_time"].min() if not df_ses.empty else None

                    for rider in riders_to_show:
                        rnum = RIDER_NUM[rider]
                        # Match both int and string rider_num from different data sources
                        df_r = df_ses[df_ses["rider_num"].astype(str) == str(rnum)]
                        if df_r.empty:
                            continue
                        times = pd.to_numeric(df_r["lap_time"], errors="coerce").dropna().values
                        if len(times) == 0:
                            continue
                        best      = float(times.min())
                        avg       = float(times.mean())
                        sigma     = float(times.std()) if len(times) > 1 else 0.0
                        p1_gap    = round(best - float(p1_time), 3) if p1_time is not None else 0.0
                        avg_vs_best = round(avg - best, 3)
                        rows.append({
                            "Session":         ses,
                            "Rider":           rider,
                            "Laps":            len(times),
                            "Best Lap":        fmt_lap(best),
                            "Best (s)":        best,        # hidden, for charts
                            "P1 Gap (s)":      p1_gap,
                            "Consistency σ":   round(sigma, 3),
                            "Avg vs Best (s)": avg_vs_best,
                        })

                if not rows:
                    st.warning(f"No valid lap data for the selected riders/round. "
                               f"({len(df_round)} laps loaded, {len(df_valid)} after filter, "
                               f"sessions: {sessions_avail})")
                else:
                    df_m = pd.DataFrame(rows)

                    # ── Colour-coded metrics table ───────────
                    st.markdown("#### Session Metrics")

                    def _colour_p1(v):
                        if v <= 0.0:   return "background-color:#d4edda;color:#155724"
                        if v <  0.5:   return "background-color:#fff3cd;color:#856404"
                        return "background-color:#f8d7da;color:#721c24"

                    def _colour_sigma(v):
                        if v < 0.3:   return "background-color:#d4edda;color:#155724"
                        if v < 0.8:   return "background-color:#fff3cd;color:#856404"
                        return "background-color:#f8d7da;color:#721c24"

                    def _colour_avg(v):
                        if v < 0.3:   return "background-color:#d4edda;color:#155724"
                        if v < 1.0:   return "background-color:#fff3cd;color:#856404"
                        return "background-color:#f8d7da;color:#721c24"

                    disp_cols = ["Session","Rider","Laps","Best Lap",
                                 "P1 Gap (s)","Consistency σ","Avg vs Best (s)"]
                    try:
                        # pandas >= 2.1 uses .map(); older pandas uses .applymap()
                        _s = df_m[disp_cols].style
                        _cell_fn = "map" if hasattr(_s, "map") else "applymap"
                        styled = (getattr(_s, _cell_fn)(_colour_p1,    subset=["P1 Gap (s)"])
                                  .pipe(lambda s: getattr(s, _cell_fn)(_colour_sigma, subset=["Consistency σ"]))
                                  .pipe(lambda s: getattr(s, _cell_fn)(_colour_avg,   subset=["Avg vs Best (s)"])))
                        st.dataframe(styled, use_container_width=True, hide_index=True)
                    except Exception:
                        # Fallback: plain dataframe without colour styling
                        st.dataframe(df_m[disp_cols], use_container_width=True, hide_index=True)

                    st.caption("🟢 Green = strong  🟡 Yellow = acceptable  🔴 Red = needs attention  "
                               "| P1 Gap: gap to session fastest  "
                               "| Consistency σ: std dev of valid laps  "
                               "| Avg vs Best: avg lap vs personal best")

                    st.divider()

                    # ── Performance Evolution Chart ──────────
                    st.markdown("#### Performance Evolution across Event")

                    import plotly.graph_objects as go

                    fig_evo = go.Figure()

                    # P1 rider average reference
                    # Uses the average lap time of the fastest rider per session
                    # (more stable reference than best single lap, especially for
                    #  FP/SP where a single hot lap can be misleading)
                    p1_ref = {}
                    for ses in sessions_avail:
                        ses_data = df_valid[df_valid["session_type"] == ses]
                        if ses_data.empty:
                            continue
                        rider_avgs = ses_data.groupby("rider_num")["lap_time"].mean()
                        if not rider_avgs.empty:
                            p1_ref[ses] = float(rider_avgs.min())
                    if p1_ref:
                        fig_evo.add_trace(go.Scatter(
                            x=list(p1_ref.keys()), y=list(p1_ref.values()),
                            name="P1 Rider Avg (all riders)",
                            line=dict(color="#2ECC71", width=2, dash="dot"),
                            mode="lines+markers",
                            marker=dict(size=7, symbol="diamond"),
                            customdata=[fmt_lap(v) for v in p1_ref.values()],
                            hovertemplate="%{x}  <b>%{customdata}</b><extra>P1 Rider Avg</extra>",
                        ))

                    for rider in riders_to_show:
                        rd = df_m[df_m["Rider"] == rider].copy()
                        if rd.empty:
                            continue
                        fig_evo.add_trace(go.Scatter(
                            x=rd["Session"], y=rd["Best (s)"],
                            name=f"{rider} Best Lap",
                            line=dict(color=RIDER_COLOR[rider], width=2),
                            mode="lines+markers",
                            marker=dict(size=9),
                            text=[f"P1+{g:.3f}s" for g in rd["P1 Gap (s)"]],
                            textposition="top center",
                            customdata=list(zip(
                                [fmt_lap(v) for v in rd["Best (s)"]],
                                [f"+{g:.3f}s" for g in rd["P1 Gap (s)"]],
                            )),
                            hovertemplate="%{x}  <b>%{customdata[0]}</b>  (%{customdata[1]})<extra>" + rider + "</extra>",
                        ))

                    # Y-axis tick range in mm:ss.00
                    _evo_y_all = list(p1_ref.values()) + [
                        float(v) for r in riders_to_show
                        for v in df_m[df_m["Rider"] == r]["Best (s)"].dropna()
                    ]
                    if _evo_y_all:
                        import numpy as _np
                        _evo_lo = min(_evo_y_all) - 0.4
                        _evo_hi = max(_evo_y_all) + 0.4
                        _step = 0.5
                        _evo_ticks = list(_np.arange(
                            _np.floor(_evo_lo / _step) * _step,
                            _np.ceil(_evo_hi / _step) * _step + _step,
                            _step,
                        ))
                        _evo_yaxis = dict(
                            tickvals=_evo_ticks,
                            ticktext=[fmt_lap(v) for v in _evo_ticks],
                            range=[_evo_hi, _evo_lo],   # reversed: faster = top
                        )
                    else:
                        _evo_yaxis = dict(autorange="reversed")

                    fig_evo.update_layout(
                        xaxis_title="Session",
                        yaxis_title="Lap Time",
                        yaxis=_evo_yaxis,
                        legend=dict(orientation="h", y=1.12),
                        height=420,
                        margin=dict(l=60, r=20, t=40, b=40),
                        plot_bgcolor="#FAFAFA",
                        paper_bgcolor="white",
                    )
                    st.plotly_chart(fig_evo, use_container_width=True)

                    st.divider()

                    # ── Consistency Evolution ────────────────
                    st.markdown("#### Consistency (σ) Evolution — lower is better")

                    fig_sig = go.Figure()
                    for rider in riders_to_show:
                        rd = df_m[df_m["Rider"] == rider]
                        if rd.empty:
                            continue
                        fig_sig.add_trace(go.Bar(
                            x=rd["Session"], y=rd["Consistency σ"],
                            name=rider,
                            marker_color=RIDER_COLOR[rider],
                            opacity=0.85,
                            text=[f"{v:.2f}s" for v in rd["Consistency σ"]],
                            textposition="outside",
                        ))
                    fig_sig.update_layout(
                        barmode="group",
                        xaxis_title="Session",
                        yaxis_title="Std Dev (s)",
                        height=300,
                        margin=dict(l=50, r=20, t=20, b=40),
                        plot_bgcolor="#FAFAFA",
                        paper_bgcolor="white",
                    )
                    st.plotly_chart(fig_sig, use_container_width=True)

                    st.divider()

                    # ── Setup Direction ── セッション間ペース変化 ──
                    st.markdown("#### Setup Direction — Session-over-Session Pace")

                    _pace_shown = False
                    for rider in riders_to_show:
                        rd = df_m[df_m["Rider"] == rider].reset_index(drop=True)
                        if len(rd) < 2:
                            continue
                        _pace_shown = True
                        st.markdown(f"**{rider}**")
                        dir_cols = st.columns(len(rd) - 1)
                        for i in range(len(rd) - 1):
                            prev = rd.iloc[i]
                            curr = rd.iloc[i + 1]
                            d_pace  = curr["Best (s)"]        - prev["Best (s)"]
                            d_sigma = curr["Consistency σ"]   - prev["Consistency σ"]
                            pi = "🟢" if d_pace  < -0.1 else ("🔴" if d_pace  > 0.1 else "🟡")
                            ci = "🟢" if d_sigma < -0.1 else ("🔴" if d_sigma > 0.1 else "🟡")
                            with dir_cols[i]:
                                st.markdown(
                                    f"<div style='text-align:center;padding:8px;background:#F8F9FA;"
                                    f"border-radius:8px;border:1px solid #DDE1E7'>"
                                    f"<b>{prev['Session']}→{curr['Session']}</b><br>"
                                    f"{pi} Pace: <b>{d_pace:+.3f}s</b><br>"
                                    f"{ci} σ: <b>{d_sigma:+.3f}s</b></div>",
                                    unsafe_allow_html=True,
                                )

                    if not _pace_shown:
                        st.caption("Session-over-Session comparison requires at least 2 sessions. "
                                   "Only 1 session available for the selected round/rider.")

                    st.divider()

                    # ── Setup Direction ── Run別セットアップ詳細 ──
                    st.markdown("#### Setup Direction — Run-by-Run Detail")
                    st.caption("🟡 Yellow = changed from previous run in same session")

                    _run_log = load_run_log()
                    _circuit = ROUND_CIRCUIT_MAP.get(sel_la_round, "")

                    if _run_log.empty or not _circuit:
                        st.info("Run log data not available in this environment. "
                                "Place Data_Bace_TS24_ORIGINAL.xlsx in 04_REFERENCE folder.")
                    else:
                        # セットアップ表示列の定義
                        _SETUP_COLS = {
                            "F:Set C/R": lambda r: f"{r['SETTING']}/{r['_blank_9']}",
                            "F:Spr L/R": lambda r: f"{r['SPRING L/R']}/{r['_blank_13']}",
                            "F:PreLoad": lambda r: r["PRELOAD"],
                            "F:Comp":    lambda r: r["COMP"],
                            "F:Reb":     lambda r: r["REB"],
                            "F:Offset":  lambda r: r["OFFSET"],
                            "F:Height":  lambda r: r["FRONT HEIGHT TOP/BOTT"],
                            "R:ShkType": lambda r: r["SHOCK TYP"],
                            "R:Set C/R": lambda r: r["SETTING COMP/REB"],
                            "R:Spring":  lambda r: r["SPRING"],
                            "R:PreLoad": lambda r: r["PRELOAD_2"],
                            "R:Comp":    lambda r: r["COMP_2"],
                            "R:Reb":     lambda r: r["REB_2"],
                            "ShkLen":    lambda r: r["SHOCK LENGHT"],
                            "Link":      lambda r: r["LINK"],
                            "RideHgt":   lambda r: r["RIDE HEIGHT"],
                            "SwingArm":  lambda r: r["SWING ARM LENGHT"],
                        }

                        def _highlight_run_changes(df_disp):
                            styles = pd.DataFrame(
                                "", index=df_disp.index, columns=df_disp.columns
                            )
                            for col in df_disp.columns:
                                if col == "RUN":
                                    continue
                                for i in range(1, len(df_disp)):
                                    if str(df_disp.iloc[i][col]) != str(df_disp.iloc[i - 1][col]):
                                        styles.iat[i, df_disp.columns.get_loc(col)] = (
                                            "background-color:#FFF3CD;"
                                            "font-weight:bold;color:#856404"
                                        )
                            return styles

                        for rider in riders_to_show:
                            st.markdown(f"**{rider}**")
                            RIDER_NUM_MAP = {"DA77": "DA77", "JA52": "JA52"}

                            # どのセッションにデータがあるか確認
                            _ses_with_data = []
                            for ses in sessions_avail:
                                orig_ses = SESSION_LAP_TO_ORIG.get(ses, ses)
                                _df_chk = _run_log[
                                    (_run_log["CIRCUIT"] == _circuit) &
                                    (_run_log["RIDER"]   == rider) &
                                    (_run_log["SESSION"] == orig_ses)
                                ]
                                if not _df_chk.empty:
                                    _ses_with_data.append(ses)

                            if not _ses_with_data:
                                st.caption(f"No run log data for {rider} at {_circuit}.")
                                continue

                            # セッションごとにタブ表示
                            _tabs = st.tabs(_ses_with_data)
                            for _t_idx, ses in enumerate(_ses_with_data):
                                orig_ses = SESSION_LAP_TO_ORIG.get(ses, ses)
                                _df_runs = _run_log[
                                    (_run_log["CIRCUIT"] == _circuit) &
                                    (_run_log["RIDER"]   == rider) &
                                    (_run_log["SESSION"] == orig_ses)
                                ].copy().reset_index(drop=True)

                                # 表示用テーブル構築
                                _rows = []
                                for _, _row in _df_runs.iterrows():
                                    _r = {"RUN": int(_row["RUN"])}
                                    for _col, _fn in _SETUP_COLS.items():
                                        try:
                                            _r[_col] = _fn(_row)
                                        except Exception:
                                            _r[_col] = "—"
                                    _rows.append(_r)

                                _df_disp = pd.DataFrame(_rows)

                                # 変化した列数をカウント
                                _n_changes = sum(
                                    1
                                    for col in _df_disp.columns
                                    if col != "RUN"
                                    for i in range(1, len(_df_disp))
                                    if str(_df_disp.iloc[i][col]) != str(_df_disp.iloc[i - 1][col])
                                )

                                with _tabs[_t_idx]:
                                    if len(_df_disp) == 1:
                                        # 1 RUNのみ：ハイライトなし
                                        st.dataframe(
                                            _df_disp,
                                            use_container_width=True,
                                            hide_index=True,
                                        )
                                        st.caption("Only 1 run in this session — no changes to highlight.")
                                    else:
                                        try:
                                            _styled = _df_disp.style.apply(
                                                _highlight_run_changes, axis=None
                                            )
                                        except Exception:
                                            _styled = _df_disp
                                        st.dataframe(
                                            _styled,
                                            use_container_width=True,
                                            hide_index=True,
                                        )
                                        st.caption(
                                            f"🟡 {_n_changes} parameter change(s) across "
                                            f"{len(_df_disp)} runs"
                                        )

    # ═══════════════════════════════════════════════════
    # PAGE 6 — Session Detail
    # ═══════════════════════════════════════════════════
    # PAGE — 2D Lap Data
    # ═══════════════════════════════════════════════════
    elif _NAV == "🏎  2D Lap Data":
        st.markdown('<p class="section-title">🏎 2D Lap Data — Official Session Laps (JA52 / DA77)</p>', unsafe_allow_html=True)

        # ── Fetch via existing _supa_to_df helper ────────────────
        _cfg2d   = load_config()
        _url2d   = _cfg2d.get("supabase_url", "").rstrip("/")
        _key2d   = _cfg2d.get("supabase_service_key", "")

        if not _url2d or not _key2d or "PASTE" in _key2d:
            st.warning("⚠️ Supabase not configured.")
        else:
            with st.spinner("Loading 2D session data..."):
                df_2ds = _supa_to_df("sessions_2d",  _key2d, _url2d,
                                     order="date.asc,round.asc,rider.asc,run_no.asc")
                df_2dl = _supa_to_df("lap_times_2d", _key2d, _url2d,
                                     order="date.asc,round.asc,rider.asc,run_no.asc,lap_no.asc")

            if df_2ds.empty:
                st.info("📭 No 2D session data in Supabase yet.\n\n"
                        "Run `sync_2d_to_supabase.command` on your Mac to populate.")
            else:
                # ── Filters ─────────────────────────────────────
                col_f1, col_f2, col_f3 = st.columns(3)
                _rounds_2d  = sorted(df_2ds["round"].dropna().unique())
                _riders_2d  = sorted(df_2ds["rider"].dropna().unique())
                _stypes_2d  = sorted(df_2ds["session_type"].dropna().unique())

                # 最新ラウンドをデフォルトに（日付ベースで判定）
                try:
                    _2d_latest_date = df_2ds["date"].dropna().max()
                    _2d_latest_rnd  = df_2ds.loc[df_2ds["date"] == _2d_latest_date, "round"].iloc[0]
                    _2d_default_rnd = [_2d_latest_rnd] if _2d_latest_rnd in _rounds_2d else _rounds_2d
                except Exception:
                    _2d_default_rnd = _rounds_2d

                with col_f1:
                    _sel_round = st.multiselect("Round",   _rounds_2d, default=_2d_default_rnd, key="2d_round")
                with col_f2:
                    _sel_rider = st.multiselect("Rider",   _riders_2d, default=_riders_2d, key="2d_rider")
                with col_f3:
                    _sel_stype = st.multiselect("Session", _stypes_2d, default=_stypes_2d, key="2d_stype")

                df_2ds_f = df_2ds[
                    df_2ds["round"].isin(_sel_round) &
                    df_2ds["rider"].isin(_sel_rider) &
                    df_2ds["session_type"].isin(_sel_stype)
                ].copy()

                df_2dl_f = df_2dl[
                    df_2dl["round"].isin(_sel_round) &
                    df_2dl["rider"].isin(_sel_rider) &
                    df_2dl["session_type"].isin(_sel_stype)
                ].copy() if not df_2dl.empty else pd.DataFrame()

                st.markdown(f"**{len(df_2ds_f)} sessions · {len(df_2dl_f)} laps** (filtered)")
                st.divider()

                tab_a, tab_b, tab_c = st.tabs(["📊 Lap Time Chart", "📋 Session Summary", "🔧 Setup Overview"])

                # TAB A — Lap Time Chart
                with tab_a:
                    if df_2dl_f.empty:
                        st.info("No lap data for current filter.")
                    else:
                        df_2dl_f["lap_time_s"] = pd.to_numeric(df_2dl_f["lap_time_s"], errors="coerce")
                        df_2dl_f = df_2dl_f[~df_2dl_f["is_outlap"].astype(bool)]
                        df_2dl_f = df_2dl_f.dropna(subset=["lap_time_s"])
                        df_2dl_f["label"] = (df_2dl_f["round"] + " " + df_2dl_f["session_type"]
                                             + " R" + df_2dl_f["run_no"].astype(str)
                                             + " " + df_2dl_f["rider"])

                        def _fmt2d(sec):
                            try:
                                m = int(sec // 60); s = sec - m * 60
                                return f"{m}:{s:06.3f}"
                            except Exception:
                                return "—"

                        RIDER_COL = {"JA52": "#2196F3", "DA77": "#FF5722"}
                        fig_2d = go.Figure()
                        for _lbl in df_2dl_f["label"].unique():
                            _d     = df_2dl_f[df_2dl_f["label"] == _lbl]
                            _rider = _d["rider"].iloc[0]
                            _cd2d  = _d["lap_time_s"].apply(_fmt2d).values
                            fig_2d.add_trace(go.Scatter(
                                x=_d["lap_no"], y=_d["lap_time_s"],
                                mode="lines+markers", name=_lbl,
                                line=dict(color=RIDER_COL.get(_rider, "#888"), width=1.5),
                                marker=dict(size=5),
                                customdata=_cd2d,
                                hovertemplate="%{text}<br>Lap %{x}: %{customdata}<extra></extra>",
                                text=[_lbl] * len(_d)
                            ))
                        # Y-axis: M:SS.mmm ticks
                        _2d_y_min = df_2dl_f["lap_time_s"].min()
                        _2d_y_max = df_2dl_f["lap_time_s"].max()
                        _2d_pad   = max((_2d_y_max - _2d_y_min) * 0.15, 0.5)
                        _2d_ticks = [_2d_y_min + i * (_2d_y_max - _2d_y_min) / 6 for i in range(7)]
                        fig_2d.update_layout(
                            height=420, template="plotly_white",
                            xaxis_title="Lap No", yaxis_title="Lap Time",
                            legend=dict(orientation="h", y=-0.25),
                            margin=dict(t=20, b=90),
                            yaxis=dict(
                                tickvals=_2d_ticks,
                                ticktext=[_fmt2d(v) for v in _2d_ticks],
                                range=[_2d_y_min - _2d_pad, _2d_y_max + _2d_pad],
                            )
                        )
                        st.plotly_chart(fig_2d, use_container_width=True)

                        # Best lap table
                        _best = (df_2dl_f.groupby(["round","session_type","rider","run_no"])
                                         ["lap_time_s"].min().reset_index()
                                         .sort_values(["round","session_type","rider","run_no"]))
                        _best["Best Lap"] = _best["lap_time_s"].apply(
                            lambda t: f"{int(t//60)}:{t%60:06.3f}" if pd.notna(t) and t > 0 else "")
                        _best.columns = ["Round","Session","Rider","Run","Best Lap (s)","Best Lap"]
                        st.dataframe(_best[["Round","Session","Rider","Run","Best Lap","Best Lap (s)"]],
                                     use_container_width=True, hide_index=True)

                # TAB B — Session Summary
                with tab_b:
                    _disp = [c for c in ["round","circuit","date","session_type","rider","run_no",
                                         "total_laps","best_lap","best_lap_s","condition",
                                         "air_temp","track_temp","tyre_f","tyre_r"]
                             if c in df_2ds_f.columns]
                    st.dataframe(df_2ds_f[_disp].sort_values(["date","round","rider","run_no"]),
                                 use_container_width=True, hide_index=True)

                # TAB C — Setup Overview
                with tab_c:
                    _setup = [c for c in ["round","date","session_type","rider","run_no",
                                          "fork","fork_comp","fork_reb","shock","fork_offset",
                                          "tyre_f","tyre_r","tyre_f_press","tyre_r_press"]
                              if c in df_2ds_f.columns]
                    st.dataframe(df_2ds_f[_setup].sort_values(["date","round","rider","run_no"]),
                                 use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════
    elif _NAV == "📋  Session Detail":
        session_list = df_s["session_id"].tolist()
        if not session_list:
            st.info("No sessions for current filter.")
        else:
            sel_session = st.selectbox(
                "Session", session_list,
                index=len(session_list) - 1,
                label_visibility="visible"
            )
            row = df_s[df_s["session_id"] == sel_session].iloc[0]
            session_tag_rows = tags[tags["session_id"] == sel_session]

            # ── Info row ──
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("Best Lap",    row.get("best_lap") or "—")
            i2.metric("Race Result", row.get("race_result") or "—")
            i3.metric("Track Temp",  f"{row.get('track_temp') or '—'}°C")
            i4.metric("Air Temp",    f"{row.get('air_temp') or '—'}°C")

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # ── Setup columns ──
            col_a, col_b, col_c = st.columns(3, gap="medium")

            with col_a:
                st.markdown('<p class="section-title">Session Info</p>', unsafe_allow_html=True)
                info_items = [
                    ("Date",    row.get("session_date") or "—"),
                    ("Circuit", row.get("circuit") or "—"),
                    ("Session", row.get("session_type") or "—"),
                    ("Rider",   row.get("rider") or "—"),
                    ("Bike",    row.get("bike_model") or "—"),
                    ("F Tyre",  row.get("f_tyre") or "—"),
                    ("R Tyre",  row.get("r_tyre") or "—"),
                ]
                for label, val in info_items:
                    st.markdown(
                        f'<div class="detail-row"><span class="detail-label">{label}</span>'
                        f'<span class="detail-val">{val}</span></div>',
                        unsafe_allow_html=True
                    )

            with col_b:
                st.markdown('<p class="section-title">Front Fork</p>', unsafe_allow_html=True)
                fork_items = [
                    ("Type",    row.get("fork_type") or "—"),
                    ("Spring",  f"{row.get('f_spring') or '—'} N/mm"),
                    ("Preload", f"{row.get('f_preload') or '—'} mm"),
                    ("COMP",    row.get("f_comp") or "—"),
                    ("REB",     row.get("f_reb") or "—"),
                ]
                for label, val in fork_items:
                    st.markdown(
                        f'<div class="detail-row"><span class="detail-label">{label}</span>'
                        f'<span class="detail-val">{val}</span></div>',
                        unsafe_allow_html=True
                    )

                st.markdown('<p class="section-title" style="margin-top:16px">Rear Shock</p>', unsafe_allow_html=True)
                shock_items = [
                    ("Type",      row.get("shock_type") or "—"),
                    ("Spring",    f"{row.get('r_spring') or '—'} N/mm"),
                    ("Preload",   f"{row.get('r_preload') or '—'} mm"),
                    ("COMP",      row.get("r_comp") or "—"),
                    ("REB",       row.get("r_reb") or "—"),
                    ("Swing Arm", f"{row.get('swing_arm') or '—'} mm"),
                    ("Ride Height", f"{row.get('ride_height') or '—'} mm"),
                ]
                for label, val in shock_items:
                    st.markdown(
                        f'<div class="detail-row"><span class="detail-label">{label}</span>'
                        f'<span class="detail-val">{val}</span></div>',
                        unsafe_allow_html=True
                    )

            with col_c:
                st.markdown('<p class="section-title">Problem Tags</p>', unsafe_allow_html=True)
                BADGE_COLORS = {
                    "PH1": "#C0392B", "PH2": "#E67E22",
                    "PH3": "#D4AC0D", "PH4": "#27AE60", "PH5": "#2980B9"
                }
                if session_tag_rows.empty:
                    st.caption("No tags recorded.")
                else:
                    for _, trow in session_tag_rows.iterrows():
                        ph = trow.get("phase") or "—"
                        bg = BADGE_COLORS.get(ph, "#999")
                        st.markdown(
                            f'<span class="badge" style="background:{bg};color:white">{ph}</span>'
                            f'&nbsp;<b style="font-size:13px">{trow["tag"]}</b><br>',
                            unsafe_allow_html=True
                        )

                # Phase problems summary
                st.markdown('<p class="section-title" style="margin-top:16px">Phase Comments</p>', unsafe_allow_html=True)
                for ph_col, ph_name in [
                    ("ph1_braking", "PH1"), ("ph2_entry", "PH2"),
                    ("ph3_mid", "PH3"), ("ph4_exit", "PH4"), ("ph5_speed", "PH5")
                ]:
                    val = row.get(ph_col) or row.get(ph_col.split("_")[0])
                    # Try generic column name
                    for try_col in [ph_col, ph_col.split("_")[0]]:
                        val = row.get(try_col)
                        if val:
                            break
                    if val:
                        color = BADGE_COLORS.get(ph_name, "#999")
                        st.markdown(
                            f'<span class="badge" style="background:{color};color:white">{ph_name}</span>'
                            f'<span style="font-size:12px;color:#444"> {val}</span><br>',
                            unsafe_allow_html=True
                        )

            # Engineer notes
            note = row.get("engineer_note")
            next_act = row.get("next_action")

            if note or next_act:
                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                n1, n2 = st.columns(2, gap="medium")
                if note:
                    with n1:
                        st.markdown('<p class="section-title">Engineer Notes</p>', unsafe_allow_html=True)
                        st.text_area("", value=note, height=150, disabled=True, label_visibility="collapsed")
                if next_act:
                    with n2:
                        st.markdown('<p class="section-title">Next Action</p>', unsafe_allow_html=True)
                        st.markdown(
                            f'<div style="background:#EBF5FB;border-left:4px solid #0078D4;'
                            f'padding:12px 16px;border-radius:4px;font-size:13px;color:#1A252F">'
                            f'{next_act}</div>',
                            unsafe_allow_html=True
                        )

    # ═══════════════════════════════════════════════════
    # PAGE — Suspension Dynamics
    # ═══════════════════════════════════════════════════
    elif _NAV == "🔬  Suspension Dynamics":
        st.markdown('<p class="section-title">🔬 Suspension Dynamics — APEX / Braking Entry / Pit Limiter</p>',
                    unsafe_allow_html=True)

        df_dyn, _ = _load_dynamics_data()

        if df_dyn.empty:
            st.warning("⚠️ データが見つかりません。\n\n"
                       "Mac で run_full_analysis.command を実行後、git push してください。")
        else:
            # ── Filters ──────────────────────────────────────
            fc1, fc2, fc3 = st.columns(3)
            _dyn_riders   = sorted(df_dyn["Rider"].dropna().unique())
            _dyn_circuits = sorted(df_dyn["Circuit"].apply(_dyn_norm_circuit).dropna().unique())
            _dyn_sessions = sorted(df_dyn["Session"].apply(_dyn_norm_session).dropna().unique())

            # 最新イベントのサーキットをデフォルトに
            try:
                _dyn_latest_date = df_dyn["Date"].dropna().max()
                _dyn_latest_circ = _dyn_norm_circuit(
                    df_dyn.loc[df_dyn["Date"] == _dyn_latest_date, "Circuit"].iloc[0]
                )
                _dyn_default_circ = [_dyn_latest_circ] if _dyn_latest_circ in _dyn_circuits else _dyn_circuits
            except Exception:
                _dyn_default_circ = _dyn_circuits

            with fc1:
                _f_rider = st.multiselect("Rider", _dyn_riders, default=_dyn_riders, key="dyn_rider")
            with fc2:
                _f_circuit = st.multiselect("Circuit", _dyn_circuits, default=_dyn_default_circ, key="dyn_circ")
            with fc3:
                _f_session = st.multiselect("Session", _dyn_sessions, default=_dyn_sessions, key="dyn_sess")

            df_dyn_w = df_dyn.copy()
            df_dyn_w["Circuit_n"] = df_dyn_w["Circuit"].apply(_dyn_norm_circuit)
            df_dyn_w["Session_n"] = df_dyn_w["Session"].apply(_dyn_norm_session)
            df_dyn_w = df_dyn_w[
                df_dyn_w["Rider"].isin(_f_rider) &
                df_dyn_w["Circuit_n"].isin(_f_circuit) &
                df_dyn_w["Session_n"].isin(_f_session)
            ].copy()

            if df_dyn_w.empty:
                st.info("No data for current filter.")
            else:
                # Build a session label column for x-axis
                df_dyn_w["Run"] = pd.to_numeric(df_dyn_w["Run"], errors="coerce").fillna(0).astype(int)
                df_dyn_w["label"] = (df_dyn_w["Circuit_n"].str[:6] + " "
                                     + df_dyn_w["Session_n"] + " R"
                                     + df_dyn_w["Run"].astype(str)
                                     + " " + df_dyn_w["Rider"])
                df_dyn_w = df_dyn_w.sort_values(["Date", "Rider", "Run"])

                RIDER_COLOR = {"DA77": DA77_COLOR, "JA52": JA52_COLOR}

                # ── Sub-tabs ────────────────────────────────────
                tab_apex, tab_brake, tab_pit = st.tabs(
                    ["🔺 APEX Posture", "🛑 Braking Entry", "🟡 Pit Limiter"]
                )

                def _sus_scatter(df, col_f, col_r, title, ylab="Suspension (mm)"):
                    """Dual-metric scatter/line: SusF and SusR plotted together."""
                    rows = []
                    for _, row in df.iterrows():
                        for metric, col in [("SusF (Front)", col_f), ("SusR (Rear)", col_r)]:
                            if pd.notna(row.get(col)):
                                rows.append({"label": row["label"], "Rider": row["Rider"],
                                             "Metric": metric, "Value": row[col]})
                    if not rows:
                        st.info("No data.")
                        return
                    dff = pd.DataFrame(rows)
                    fig = px.scatter(dff, x="label", y="Value", color="Rider",
                                     symbol="Metric",
                                     color_discrete_map=RIDER_COLOR,
                                     labels={"label": "", "Value": ylab},
                                     title=title)
                    fig.update_traces(marker=dict(size=10), opacity=0.85)
                    chart_layout(fig, height=360, title=title)
                    fig.update_layout(xaxis_tickangle=-40, xaxis_title="")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                def _avg_bar(df, col_f, col_r, title):
                    """Average SusF and SusR per circuit × rider bar chart."""
                    rows = []
                    for rider in df["Rider"].unique():
                        for circ in df["Circuit_n"].unique():
                            sub = df[(df["Rider"]==rider) & (df["Circuit_n"]==circ)]
                            f_avg = sub[col_f].mean() if col_f in sub else None
                            r_avg = sub[col_r].mean() if col_r in sub else None
                            if pd.notna(f_avg):
                                rows.append({"Circuit": circ, "Rider": rider, "Metric": "SusF (Front)", "Avg (mm)": round(f_avg,1)})
                            if pd.notna(r_avg):
                                rows.append({"Circuit": circ, "Rider": rider, "Metric": "SusR (Rear)", "Avg (mm)": round(r_avg,1)})
                    if not rows:
                        return
                    dff = pd.DataFrame(rows)
                    dff["Group"] = dff["Rider"] + " " + dff["Metric"]
                    fig = px.bar(dff, x="Circuit", y="Avg (mm)", color="Group", barmode="group",
                                 title=title,
                                 color_discrete_map={
                                     "DA77 SusF (Front)": "#0078D4", "DA77 SusR (Rear)": "#66B2E8",
                                     "JA52 SusF (Front)": "#E74C3C", "JA52 SusR (Rear)": "#F1948A"})
                    chart_layout(fig, height=300, title=title)
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                with tab_apex:
                    st.caption("APEX = all corners across full-length laps. Average suspension position at minimum speed (local minima of Speed F).")
                    _sus_scatter(df_dyn_w, "APEX SusF (mm)", "APEX SusR (mm)",
                                 "APEX Suspension Position — per Session")
                    st.divider()
                    _avg_bar(df_dyn_w, "APEX SusF (mm)", "APEX SusR (mm)",
                             "APEX Average Suspension — by Circuit × Rider")

                    # Summary stats table
                    st.markdown('<p class="section-title">Session Data</p>', unsafe_allow_html=True)
                    disp_cols = ["Date","Circuit_n","Session_n","Rider","Run",
                                 "APEX Count","APEX Spd (km/h)","APEX SusF (mm)","APEX SusR (mm)",
                                 "APEX WhlF (N)","APEX WhlR (N)","APEX ax (m/s²)"]
                    disp_cols = [c for c in disp_cols if c in df_dyn_w.columns]
                    rename = {"Circuit_n":"Circuit","Session_n":"Session"}
                    st.dataframe(df_dyn_w[disp_cols].rename(columns=rename).reset_index(drop=True),
                                 use_container_width=True, height=280)

                with tab_brake:
                    st.caption("Braking Entry = captured ~0.08 s before brake-on (decel ≤ −8 m/s², speed ≥ 80 km/h). Average front/rear suspension position.")
                    _sus_scatter(df_dyn_w, "Brk SusF (mm)", "Brk SusR (mm)",
                                 "Braking Entry Suspension Position — per Session")
                    st.divider()
                    _avg_bar(df_dyn_w, "Brk SusF (mm)", "Brk SusR (mm)",
                             "Braking Entry Average Suspension — by Circuit × Rider")
                    st.markdown('<p class="section-title">Session Data</p>', unsafe_allow_html=True)
                    disp_cols_b = ["Date","Circuit_n","Session_n","Rider","Run",
                                   "Brk Count","Brk Spd (km/h)","Brk SusF (mm)","Brk SusR (mm)"]
                    disp_cols_b = [c for c in disp_cols_b if c in df_dyn_w.columns]
                    st.dataframe(df_dyn_w[disp_cols_b].rename(columns={"Circuit_n":"Circuit","Session_n":"Session"}).reset_index(drop=True),
                                 use_container_width=True, height=280)

                with tab_pit:
                    st.caption("Pit Limiter = Speed F in [56–64 km/h] for ≥ 3 s continuously. Represents fully settled, low-load suspension baseline.")
                    _sus_scatter(df_dyn_w, "Pit SusF (mm)", "Pit SusR (mm)",
                                 "Pit Limiter Suspension Position — per Session")
                    st.divider()
                    _avg_bar(df_dyn_w, "Pit SusF (mm)", "Pit SusR (mm)",
                             "Pit Limiter Average Suspension — by Circuit × Rider")
                    st.markdown('<p class="section-title">Session Data</p>', unsafe_allow_html=True)
                    disp_cols_p = ["Date","Circuit_n","Session_n","Rider","Run",
                                   "Pit Count","Pit Spd (km/h)","Pit SusF (mm)","Pit SusR (mm)"]
                    disp_cols_p = [c for c in disp_cols_p if c in df_dyn_w.columns]
                    st.dataframe(df_dyn_w[disp_cols_p].rename(columns={"Circuit_n":"Circuit","Session_n":"Session"}).reset_index(drop=True),
                                 use_container_width=True, height=280)

    # ═══════════════════════════════════════════════════
    # PAGE — Lap Sus Stats (ラップ別サスペンション統計)
    # ═══════════════════════════════════════════════════
    elif _NAV == "📊  Lap Sus Stats":
        st.markdown('<p class="section-title">📊 Lap Sus Stats — ラップ別サスペンション統計</p>',
                    unsafe_allow_html=True)

        df_ls = _load_lap_suspension()

        if df_ls.empty:
            st.warning("⚠️ LAP_SUSPENSION データが見つかりません。\n\n"
                       "Mac で `python lap_suspension_stats.py` を実行後、再起動してください。")
        else:
            # ── フィルター ──────────────────────────────────
            fc1, fc2, fc3, fc4 = st.columns(4)
            _ls_riders   = sorted(df_ls["RIDER"].dropna().unique())   if "RIDER"   in df_ls.columns else []
            _ls_circuits = sorted(df_ls["CIRCUIT"].dropna().unique()) if "CIRCUIT" in df_ls.columns else []
            _ls_sessions = sorted(df_ls["SESSION"].dropna().unique()) if "SESSION" in df_ls.columns else []
            _ls_rounds   = sorted(df_ls["ROUND"].dropna().unique())   if "ROUND"   in df_ls.columns else []

            # 最新イベントをデフォルトに
            try:
                _ls_latest_date = df_ls["DATE"].dropna().max() if "DATE" in df_ls.columns else None
                _ls_latest_circ = df_ls.loc[df_ls["DATE"] == _ls_latest_date, "CIRCUIT"].iloc[0] if _ls_latest_date else None
                _ls_latest_rnd  = df_ls.loc[df_ls["DATE"] == _ls_latest_date, "ROUND"].iloc[0]  if _ls_latest_date else None
                _ls_default_circ = [_ls_latest_circ] if _ls_latest_circ in _ls_circuits else _ls_circuits
                _ls_default_rnd  = [_ls_latest_rnd]  if _ls_latest_rnd  in _ls_rounds  else _ls_rounds
            except Exception:
                _ls_default_circ = _ls_circuits
                _ls_default_rnd  = _ls_rounds

            with fc1:
                _f_ls_rider = st.multiselect("Rider", _ls_riders, default=_ls_riders, key="ls_rider")
            with fc2:
                _f_ls_circ  = st.multiselect("Circuit", _ls_circuits, default=_ls_default_circ, key="ls_circ")
            with fc3:
                _f_ls_sess  = st.multiselect("Session", _ls_sessions, default=_ls_sessions, key="ls_sess")
            with fc4:
                _f_ls_rnd  = st.multiselect("Round", _ls_rounds, default=_ls_default_rnd, key="ls_rnd")

            dfW = df_ls.copy()
            if _f_ls_rider   and "RIDER"   in dfW.columns: dfW = dfW[dfW["RIDER"].isin(_f_ls_rider)]
            if _f_ls_circ    and "CIRCUIT" in dfW.columns: dfW = dfW[dfW["CIRCUIT"].isin(_f_ls_circ)]
            if _f_ls_sess    and "SESSION" in dfW.columns: dfW = dfW[dfW["SESSION"].isin(_f_ls_sess)]
            if _f_ls_rnd     and "ROUND"   in dfW.columns: dfW = dfW[dfW["ROUND"].isin(_f_ls_rnd)]

            if dfW.empty:
                st.info("No data for current filter.")
            else:
                # x軸ラベル: Circuit + Session + RunNo + LapNo
                dfW = dfW.copy()
                dfW["run_label"] = (dfW.get("CIRCUIT","").astype(str).str[:5] + " "
                                    + dfW.get("SESSION","").astype(str) + " R"
                                    + dfW.get("RUN_NO", pd.Series(dtype=str)).astype(str))
                dfW["lap_label"] = dfW["run_label"] + " L" + dfW.get("LAP_NO", pd.Series(dtype=str)).astype(str)

                RIDER_COLOR = {"DA77": DA77_COLOR, "JA52": JA52_COLOR}

                tab_apex, tab_brake, tab_laptime, tab_table = st.tabs(
                    ["🔺 APEX per Lap", "🛑 Brake per Lap", "⏱ Lap Time Trend", "📋 Data Table"]
                )

                # ── APEX タブ ───────────────────────────────
                with tab_apex:
                    st.caption(
                        "**APEX SusF** — "
                        "新定義 (2026-04-30): BRAKE_FRONT -0.6~0.3Bar / GAS 0~6% / "
                        "dTPS_A 5~50 / SUSP_F 20~140mm / SUSP_R 5~50mm の5条件同時成立区間"
                    )

                    # ── APEX SusF ラップ別 ────────────────────────
                    apex_cols = [
                        ("APEX_SUSF_AVG", "APEX SusF (mm)"),
                    ]
                    rows_3 = []
                    for _, r in dfW.iterrows():
                        for col, label in apex_cols:
                            if col in dfW.columns and pd.notna(r.get(col)):
                                rows_3.append({
                                    "Lap": r["lap_label"], "Rider": r.get("RIDER","?"),
                                    "Definition": label, "SusF (mm)": r[col],
                                    "Run": r["run_label"], "LapNo": r.get("LAP_NO", 0)
                                })
                    if rows_3:
                        df3 = pd.DataFrame(rows_3)

                        # ── Power BI スタイル: 定義別カラー ─────────
                        DEF_COLORS = {
                            "APEX SusF (mm)": "#0078D4",   # Power BI blue
                        }
                        # ライダー別シンボル
                        riders_u = sorted(df3["Rider"].unique())
                        _syms = ["circle","square","diamond","cross","x","triangle-up"]
                        sym_map = {r: _syms[i % len(_syms)] for i, r in enumerate(riders_u)}

                        runs_u = sorted(df3["Run"].unique())
                        n_runs = len(runs_u)
                        cols_w = 2 if n_runs > 2 else n_runs   # 2列 → 各パネルを大きく
                        n_rows_f = max(1, (n_runs + cols_w - 1) // cols_w)
                        panel_h = 340
                        total_h = max(520, panel_h * n_rows_f + 140)

                        fig_3 = px.scatter(
                            df3, x="LapNo", y="SusF (mm)",
                            color="Definition", symbol="Rider",
                            facet_col="Run", facet_col_wrap=cols_w,
                            color_discrete_map=DEF_COLORS,
                            symbol_map=sym_map,
                            labels={"LapNo": "Lap No", "SusF (mm)": "SusF (mm)"},
                        )
                        fig_3.update_traces(
                            marker=dict(size=14, line=dict(width=1.5, color="white")),
                            opacity=0.92,
                        )
                        fig_3.update_layout(
                            height=total_h,
                            plot_bgcolor="white",
                            paper_bgcolor="white",
                            font=dict(family="Arial, sans-serif", size=12, color="#1F2937"),
                            legend=dict(
                                orientation="v", yanchor="top", y=1.0,
                                xanchor="left", x=1.01,
                                bgcolor="rgba(255,255,255,0.95)",
                                bordercolor="#D1D5DB", borderwidth=1,
                                font=dict(size=11), title_font=dict(size=11),
                            ),
                            margin=dict(l=60, r=220, t=40, b=60),
                        )
                        fig_3.update_xaxes(
                            showgrid=True, gridcolor="#E5E7EB", gridwidth=1,
                            zeroline=False, showline=True, linecolor="#9CA3AF", linewidth=1,
                            tickfont=dict(size=11), title_font=dict(size=11),
                            dtick=1,
                        )
                        fig_3.update_yaxes(
                            showgrid=True, gridcolor="#E5E7EB", gridwidth=1,
                            zeroline=False, showline=True, linecolor="#9CA3AF", linewidth=1,
                            tickfont=dict(size=11), title_font=dict(size=12, color="#374151"),
                            rangemode="tozero",
                        )
                        # ファセットタイトルを "Run=" プレフィックス除去
                        fig_3.for_each_annotation(
                            lambda a: a.update(
                                text=a.text.replace("Run=", ""),
                                font=dict(size=12, color="#374151"),
                            )
                        )
                        st.plotly_chart(fig_3, use_container_width=True, config={"displayModeBar": False})

                    # ── ラン別平均 棒グラフ（Power BI スタイル）──────
                    st.divider()
                    st.markdown("**ラン別 APEX SusF 平均**")
                    rows_bar = []
                    for col, label in apex_cols:
                        if col in dfW.columns:
                            grp = dfW.groupby(["run_label","RIDER"])[col].mean().reset_index()
                            grp["Definition"] = label
                            grp.rename(columns={col: "SusF avg (mm)"}, inplace=True)
                            rows_bar.append(grp)
                    if rows_bar:
                        df_bar = pd.concat(rows_bar, ignore_index=True)
                        riders_bar = sorted(df_bar["RIDER"].unique())
                        n_r = len(riders_bar)
                        bar_h = max(420, 240 * n_r + 80)
                        fig_bar = px.bar(
                            df_bar, x="run_label", y="SusF avg (mm)",
                            color="Definition", barmode="group",
                            facet_row="RIDER",
                            color_discrete_map=DEF_COLORS if rows_3 else None,
                            labels={"run_label": "Run", "SusF avg (mm)": "SusF avg (mm)"},
                        )
                        fig_bar.update_layout(
                            height=bar_h,
                            plot_bgcolor="white", paper_bgcolor="white",
                            font=dict(family="Arial, sans-serif", size=12, color="#1F2937"),
                            legend=dict(
                                orientation="v", yanchor="top", y=1.0,
                                xanchor="left", x=1.01,
                                bgcolor="rgba(255,255,255,0.95)",
                                bordercolor="#D1D5DB", borderwidth=1,
                                font=dict(size=11),
                            ),
                            margin=dict(l=60, r=220, t=40, b=70),
                            bargap=0.20, bargroupgap=0.08,
                        )
                        fig_bar.update_xaxes(
                            showgrid=False, showline=True, linecolor="#9CA3AF",
                            tickangle=-30, tickfont=dict(size=11),
                        )
                        fig_bar.update_yaxes(
                            showgrid=True, gridcolor="#E5E7EB", gridwidth=1,
                            zeroline=True, zerolinecolor="#9CA3AF",
                            showline=True, linecolor="#9CA3AF",
                            tickfont=dict(size=11),
                        )
                        fig_bar.for_each_annotation(
                            lambda a: a.update(
                                text=a.text.replace("RIDER=", ""),
                                font=dict(size=12, color="#374151"),
                            )
                        )
                        st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})

                # ── ブレーキ タブ ────────────────────────────
                with tab_brake:
                    st.caption("各ラップのブレーキ直前・フルブレーキング時の平均サスペンションポジション")
                    brk_ok = "BRK_SUSF_AVG" in dfW.columns and dfW["BRK_SUSF_AVG"].notna().any()
                    fb_ok  = "FULLBRK_SUSF"  in dfW.columns and dfW["FULLBRK_SUSF"].notna().any()

                    if brk_ok:
                        rows_br = []
                        for _, r in dfW.iterrows():
                            if pd.notna(r.get("BRK_SUSF_AVG")):
                                rows_br.append({"Lap": r["lap_label"], "Rider": r.get("RIDER","?"),
                                                "Type":"Brake Entry SusF", "Value": r["BRK_SUSF_AVG"],
                                                "LapNo": r.get("LAP_NO",0), "Run": r["run_label"]})
                            if fb_ok and pd.notna(r.get("FULLBRK_SUSF")):
                                rows_br.append({"Lap": r["lap_label"], "Rider": r.get("RIDER","?"),
                                                "Type":"Full Brake SusF", "Value": r["FULLBRK_SUSF"],
                                                "LapNo": r.get("LAP_NO",0), "Run": r["run_label"]})
                        if rows_br:
                            dfbr = pd.DataFrame(rows_br)
                            fig_br = px.scatter(dfbr, x="LapNo", y="Value", color="Rider",
                                                symbol="Type", facet_col="Run", facet_col_wrap=4,
                                                color_discrete_map=RIDER_COLOR,
                                                labels={"LapNo":"Lap No","Value":"Sus (mm)"},
                                                title="Braking Suspension per Lap")
                            fig_br.update_traces(marker=dict(size=8), opacity=0.8)
                            chart_layout(fig_br, height=420, title="Braking Suspension per Lap")
                            st.plotly_chart(fig_br, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.info("ブレーキデータがありません。")

                # ── ラップタイム タブ ─────────────────────────
                with tab_laptime:
                    st.caption("ラップタイム推移と APEX SusF の相関")
                    lt_ok = "LAP_TIME_S" in dfW.columns and dfW["LAP_TIME_S"].notna().any()

                    # ラップタイム フォーマット helper: 秒 → "m:ss.00"
                    def _fmt_lt(s):
                        try:
                            s = float(s)
                            m = int(s) // 60
                            return f"{m}:{s % 60:05.2f}"
                        except Exception:
                            return str(s)

                    def _lt_yaxis(fig, series):
                        """Y軸ティックを m:ss.00 形式に設定"""
                        valid = series.dropna()
                        if valid.empty:
                            return
                        lo = float(valid.min())
                        hi = float(valid.max())
                        step = 5.0  # 5秒刻み
                        import math
                        t_lo = math.floor(lo / step) * step
                        t_hi = math.ceil(hi / step) * step
                        ticks = []
                        v = t_lo
                        while v <= t_hi + 0.001:
                            ticks.append(round(v, 3))
                            v += step
                        labels = [_fmt_lt(t) for t in ticks]
                        fig.update_yaxes(
                            tickvals=ticks,
                            ticktext=labels,
                            title_text="Lap Time"
                        )

                    if lt_ok:
                        # ラップタイム推移 (ラン別)
                        dfW_lt = dfW.copy()
                        dfW_lt["LAP_TIME_FMT"] = dfW_lt["LAP_TIME_S"].apply(_fmt_lt)
                        fig_lt = px.line(dfW_lt, x="LAP_NO", y="LAP_TIME_S", color="RIDER",
                                         line_dash="run_label", markers=True,
                                         color_discrete_map=RIDER_COLOR,
                                         hover_data={"LAP_TIME_S": False, "LAP_TIME_FMT": True,
                                                     "run_label": True, "LAP_NO": True},
                                         labels={"LAP_NO":"Lap No","LAP_TIME_S":"Lap Time",
                                                 "LAP_TIME_FMT":"Lap Time","run_label":"Run"},
                                         title="Lap Time per Lap")
                        chart_layout(fig_lt, height=340, title="Lap Time per Lap")
                        _lt_yaxis(fig_lt, dfW_lt["LAP_TIME_S"])
                        st.plotly_chart(fig_lt, use_container_width=True, config={"displayModeBar": False})

                        # APEX SusF vs Lap Time 散布図
                        if "APEX_SUSF_AVG" in dfW.columns and dfW["APEX_SUSF_AVG"].notna().any():
                            st.divider()
                            st.markdown("**APEX SusF vs Lap Time — 相関散布図**")
                            dfXY = dfW_lt.dropna(subset=["APEX_SUSF_AVG","LAP_TIME_S"])
                            if not dfXY.empty:
                                fig_xy = px.scatter(dfXY, x="APEX_SUSF_AVG", y="LAP_TIME_S",
                                                    color="RIDER",
                                                    hover_data={"LAP_TIME_S": False,
                                                                "LAP_TIME_FMT": True,
                                                                "run_label": True, "LAP_NO": True},
                                                    color_discrete_map=RIDER_COLOR,
                                                    trendline="ols",
                                                    labels={"APEX_SUSF_AVG":"APEX SusF (mm)",
                                                            "LAP_TIME_S":"Lap Time",
                                                            "LAP_TIME_FMT":"Lap Time",
                                                            "run_label":"Run"},
                                                    title="APEX SusF vs Lap Time Correlation")
                                chart_layout(fig_xy, height=350, title="APEX SusF vs Lap Time")
                                _lt_yaxis(fig_xy, dfXY["LAP_TIME_S"])
                                st.plotly_chart(fig_xy, use_container_width=True, config={"displayModeBar": False})
                                st.caption("傾向線はOLS(最小二乗)回帰。傾きが負 = SusF 沈み増加 → タイム短縮の傾向")
                    else:
                        st.info("ラップタイムデータがありません。")

                # ── データテーブル タブ ──────────────────────
                with tab_table:
                    disp_cols_ls = ["RUN_ID","LAP_ID","ROUND","CIRCUIT","SESSION","RIDER",
                                    "RUN_NO","LAP_NO","LAP_TIME","LAP_TIME_S",
                                    # APEX
                                    "APEX_CNT","APEX_SUSF_AVG","APEX_SUSR_AVG","APEX_SPD_AVG",
                                    # ブレーキ / ラップ全体
                                    "BRK_CNT","BRK_SUSF_AVG","BRK_SUSR_AVG",
                                    "FULLBRK_SUSF","FULLBRK_SUSR",
                                    "LAP_SUSF_MEAN","LAP_SUSF_MIN","LAP_SUSF_MAX","LAP_SUSR_MEAN"]
                    disp_cols_ls = [c for c in disp_cols_ls if c in dfW.columns]
                    st.dataframe(dfW[disp_cols_ls].reset_index(drop=True),
                                 use_container_width=True, height=420)
                    st.caption(f"表示: {len(dfW)} ラップ / 全 {len(df_ls)} ラップ")

    # ═══════════════════════════════════════════════════
    # PAGE — Setup Target
    # ═══════════════════════════════════════════════════
    elif _NAV == "🎯  Setup Target":
        st.markdown('<p class="section-title">🎯 Setup Target — FAST vs SLOW Session Comparison</p>',
                    unsafe_allow_html=True)
        st.caption("Sessions ranked by best lap time within each rider × circuit group. "
                   "FAST = top 33%, SLOW = bottom 33%. "
                   "Δ = FAST avg − SLOW avg (positive = front compresses more when fast).")

        try:
            df_dyn, df_lt = _load_dynamics_data()
        except Exception as _ld_err:
            st.error(f"データ読み込みエラー: {_ld_err}")
            df_dyn = pd.DataFrame(); df_lt = pd.DataFrame()

        if df_dyn.empty:
            st.warning("⚠️ データが見つかりません（dynamics_data.json / TS24 DB Master.xlsx）。\n\n"
                       "Mac で run_full_analysis.command を実行後、git push してください。")
            st.caption(f"DYN JSON exists: {_JSON_DYN.exists()} | LT JSON exists: {_JSON_LT.exists()} | Excel exists: {_DYNAMICS_EXCEL.exists()}")
        else:
            # ── Apex定義: 新APEX定義 (2026-04-30) を使用 ─────────
            MIN_LAP_S_CORR = 80.0

            # ── LAP_SUSPENSION から APEX / BRK をラン別集計 ──────
            df_ls = _load_lap_suspension()
            ls_map = {}
            if not df_ls.empty:
                for nc in ["APEX_SUSF_AVG","APEX_SUSR_AVG","BRK_SUSF_AVG","BRK_SUSR_AVG",
                           "APEX_CNT","BRK_CNT","APEX_SPD_AVG"]:
                    if nc in df_ls.columns:
                        df_ls[nc] = pd.to_numeric(df_ls[nc], errors="coerce")
                _grp_cols = [c for c in ["RIDER","CIRCUIT","DATE","RUN_NO"] if c in df_ls.columns]
                if _grp_cols:
                    for _gkey, _gdf in df_ls.groupby(_grp_cols):
                        if len(_grp_cols) == 4:
                            rider_g, circ_g, date_g, run_g = _gkey
                        else:
                            continue
                        circ_n = _dyn_norm_circuit(circ_g)
                        date_s = str(date_g or "")
                        try: run_i = int(run_g or 0)
                        except: run_i = 0
                        g_apex = _gdf[_gdf["APEX_CNT"] > 0] if "APEX_CNT" in _gdf.columns else _gdf
                        g_brk  = _gdf[_gdf["BRK_CNT"] > 0]  if "BRK_CNT"  in _gdf.columns else _gdf
                        ls_map[(rider_g, circ_n, date_s, run_i)] = {
                            "thron_susF": g_apex["APEX_SUSF_AVG"].dropna().mean() if not g_apex.empty else None,
                            "thron_susR": g_apex["APEX_SUSR_AVG"].dropna().mean() if not g_apex.empty else None,
                            "brk_susF":   g_brk["BRK_SUSF_AVG"].dropna().mean()  if not g_brk.empty  else None,
                            "brk_susR":   g_brk["BRK_SUSR_AVG"].dropna().mean()  if not g_brk.empty  else None,
                            "apex_spd":   _gdf["APEX_SPD_AVG"].dropna().mean()    if "APEX_SPD_AVG" in _gdf.columns else None,
                        }

            # ── LAP_TIMES からラン最良タイム ────────────────────
            lt_map = {}
            if not df_lt.empty:
                lt_rider_col  = next((c for c in df_lt.columns if str(c).lower() in ("rider","rider_id")), None)
                lt_circ_col   = next((c for c in df_lt.columns if str(c).lower() in ("circuit","circ")), None)
                lt_date_col   = next((c for c in df_lt.columns if str(c).lower() in ("date","session_date")), None)
                lt_run_col    = next((c for c in df_lt.columns if str(c).lower() in ("run","run_no","run no")), None)
                lt_ts_col     = next((c for c in df_lt.columns if str(c).lower() in
                                      ("lap_time_s","laptime_s","lap time s","time (s)")), None)
                lt_outlap_col = next((c for c in df_lt.columns if str(c).lower() in
                                      ("outlap","is_outlap","out_lap","outlap?")), None)
                if all([lt_rider_col, lt_circ_col, lt_date_col, lt_run_col, lt_ts_col]):
                    for _, lr in df_lt.iterrows():
                        rider = str(lr[lt_rider_col] or "")
                        if not rider: continue
                        if lt_outlap_col and str(lr.get(lt_outlap_col,"")).upper() == "YES": continue
                        ts = lr[lt_ts_col]
                        if not isinstance(ts, (int, float)) or ts < MIN_LAP_S_CORR or ts > 400: continue
                        circ = _dyn_norm_circuit(lr[lt_circ_col])
                        date = str(lr[lt_date_col] or "")
                        try: run = int(lr[lt_run_col] or 0)
                        except: run = 0
                        lt_map.setdefault((rider, circ, date, run), []).append(float(ts))
            lt_best = {k: min(v) for k, v in lt_map.items()}

            # ── THR_ON データ × LAP_TIMES をジョイン ────────────
            matched_rows = []
            for key, best_s in lt_best.items():
                if key not in ls_map: continue
                ld = ls_map[key]
                rider, circ, date, run = key
                matched_rows.append({
                    "rider": rider, "circuit": circ, "date": date, "run": run,
                    "best_s": best_s,
                    "apex_susF": ld.get("thron_susF"),  # APEX SusF
                    "apex_susR": ld.get("thron_susR"),  # APEX SusR
                    "apex_whlF": None,
                    "apex_whlR": None,
                    "apex_spd":  ld.get("apex_spd"),
                    "brk_susF":  ld.get("brk_susF"),
                    "brk_susR":  ld.get("brk_susR"),
                    "brk_spd":   None,
                })

            if not matched_rows:
                st.info(f"マッチするセッションが見つかりません（LAP_SUS={len(ls_map)}件 / LT={len(lt_best)}件）。\n\n"
                        "lap_suspension_data.json が最新か確認してください。")
            else:
                st.caption(f"✅ APEX / {len(matched_rows)} セッションマッチ")
                df_m = pd.DataFrame(matched_rows)

                # Tier classification per rider×circuit（groupby.apply を避けて手動ループ）
                df_m = df_m.copy()
                df_m["tier"] = "MED"
                for (rider_k, circ_k), idx in df_m.groupby(["rider","circuit"]).groups.items():
                    sub = df_m.loc[idx].sort_values("best_s")
                    n = len(sub)
                    idxs = list(sub.index)
                    for rank, orig_idx in enumerate(idxs):
                        pct = rank / max(n - 1, 1)
                        if n < 3:
                            t = "FAST" if rank == 0 else "SLOW"
                        elif pct <= 0.33:
                            t = "FAST"
                        elif pct >= 0.67:
                            t = "SLOW"
                        else:
                            t = "MED"
                        df_m.at[orig_idx, "tier"] = t

                METRICS = ["apex_susF","apex_susR","brk_susF","brk_susR","apex_spd"]
                METRIC_LABELS = {
                    "apex_susF": "APEX SusF (mm)", "apex_susR": "APEX SusR (mm)",
                    "brk_susF":  "Brk SusF (mm)",  "brk_susR":  "Brk SusR (mm)",
                    "apex_spd":  "APEX Spd (km/h)",
                }

                # ── Rider filter ──────────────────────────
                _st_riders = sorted(df_m["rider"].unique())
                _st_sel_rider = st.selectbox("Rider", ["All"] + _st_riders, key="st_rider")
                df_m_f = df_m if _st_sel_rider == "All" else df_m[df_m["rider"] == _st_sel_rider]

                # ── Summary table ─────────────────────────
                st.markdown('<p class="section-title">Setup Target Reference Table</p>', unsafe_allow_html=True)

                summary_rows = []
                for (rider, circ), grp in df_m_f.groupby(["rider","circuit"]):
                    fast = grp[grp["tier"] == "FAST"]
                    slow = grp[grp["tier"] == "SLOW"]
                    n = len(grp)
                    row = {"Rider": rider, "Circuit": circ, "N Sessions": n,
                           "Best Lap": f"{int(grp['best_s'].min())//60}:{grp['best_s'].min()%60:06.3f}"}
                    for m in METRICS:
                        fv = fast[m].dropna().mean() if not fast.empty else None
                        sv = slow[m].dropna().mean() if not slow.empty else None
                        row[f"★FAST {METRIC_LABELS[m]}"] = round(fv,1) if fv is not None else None
                        row[f"SLOW {METRIC_LABELS[m]}"]  = round(sv,1) if sv is not None else None
                        if fv is not None and sv is not None:
                            row[f"Δ {METRIC_LABELS[m]}"] = round(fv-sv,1)
                        else:
                            row[f"Δ {METRIC_LABELS[m]}"] = None
                    summary_rows.append(row)

                if summary_rows:
                    df_sum = pd.DataFrame(summary_rows)

                    # Color-coded delta display
                    def _color_delta(val):
                        if val is None or (isinstance(val, float) and pd.isna(val)):
                            return ""
                        try:
                            v = float(val)
                        except Exception:
                            return ""
                        if v > 0.5:   return "background-color:#C6EFCE; color:#276221; font-weight:bold"
                        elif v < -0.5: return "background-color:#FFC7CE; color:#9C0006; font-weight:bold"
                        else:          return "background-color:#FFEB9C; color:#7D6608"

                    delta_cols = [c for c in df_sum.columns if c.startswith("Δ ")]
                    _styler_fn = getattr(df_sum.style, "map", None) or getattr(df_sum.style, "applymap")
                    st.dataframe(
                        _styler_fn(_color_delta, subset=delta_cols),
                        use_container_width=True, height=320
                    )

                    # ── Δ bar chart — key metrics ──────────
                    st.divider()
                    st.markdown('<p class="section-title">Δ (FAST − SLOW) — Suspension Direction per Circuit</p>',
                                unsafe_allow_html=True)
                    bar_metrics = [("Δ APEX SusF (mm)", "APEX SusF"), ("Δ APEX SusR (mm)", "APEX SusR"),
                                   ("Δ Brk SusF (mm)",  "Brk SusF"),  ("Δ Brk SusR (mm)",  "Brk SusR")]
                    bar_rows = []
                    for _, sr in df_sum.iterrows():
                        for col, short in bar_metrics:
                            v = sr.get(col)
                            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                                bar_rows.append({"Circuit": sr["Circuit"],
                                                 "Rider":   sr["Rider"],
                                                 "Metric":  short,
                                                 "Δ (mm)":  float(v)})
                    if bar_rows:
                        df_bar = pd.DataFrame(bar_rows)
                        _metric_colors = {
                            "APEX SusF": "#0078D4",
                            "APEX SusR": "#50B0F0",
                            "Brk SusF":  "#E8543A",
                            "Brk SusR":  "#F4A28C",
                        }
                        _riders_sorted = sorted(df_bar["Rider"].unique())
                        _n_riders = len(_riders_sorted)
                        # ── Sort circuits alphabetically for consistent axis order
                        _circ_order = sorted(df_bar["Circuit"].unique())
                        fig_d = px.line(
                            df_bar, x="Circuit", y="Δ (mm)",
                            color="Metric", markers=True,
                            facet_col="Rider",
                            facet_col_wrap=_n_riders,
                            color_discrete_map=_metric_colors,
                            category_orders={"Rider": _riders_sorted, "Circuit": _circ_order},
                            labels={"Δ (mm)": "Δ mm (FAST − SLOW)", "Circuit": ""},
                            custom_data=["Metric", "Rider"],
                        )
                        # Marker style: large filled dots with white border
                        fig_d.update_traces(
                            mode="lines+markers",
                            marker=dict(size=10, line=dict(width=2, color="white")),
                            line=dict(width=2.5),
                        )
                        # Zero reference line
                        fig_d.add_hline(y=0, line_color="#222", line_width=1.8,
                                        line_dash="dot")
                        # Y-axis range: data range + 30% padding
                        _y_vals = df_bar["Δ (mm)"].dropna()
                        _y_pad  = max(abs(_y_vals.max()), abs(_y_vals.min())) * 0.35
                        _y_min  = _y_vals.min() - _y_pad
                        _y_max  = _y_vals.max() + _y_pad
                        # Shade positive / negative regions within data range
                        fig_d.add_hrect(y0=0,     y1=_y_max, fillcolor="#0078D4", opacity=0.05, line_width=0)
                        fig_d.add_hrect(y0=_y_min, y1=0,     fillcolor="#E8543A", opacity=0.05, line_width=0)
                        fig_d.update_layout(
                            height=480,
                            plot_bgcolor="white",
                            paper_bgcolor="white",
                            legend=dict(
                                title="Metric",
                                orientation="v",
                                x=1.01, xanchor="left", y=0.5,
                                font=dict(size=12),
                                bgcolor="rgba(255,255,255,0.9)",
                                bordercolor="#E5E7EB", borderwidth=1,
                            ),
                            margin=dict(t=70, b=60, l=60, r=170),
                            title=dict(
                                text="Suspension Trend: positive = more compression when fast  |  negative = less",
                                font=dict(size=12, color="#555"),
                                x=0, xanchor="left",
                            ),
                        )
                        fig_d.update_xaxes(
                            showgrid=False, linecolor="#CCCCCC",
                            tickfont=dict(size=11), tickangle=-20,
                        )
                        fig_d.update_yaxes(
                            range=[_y_min, _y_max],
                            gridcolor="#E5E7EB", gridwidth=1,
                            linecolor="#CCCCCC", zeroline=False,
                            ticksuffix=" mm", tickfont=dict(size=11),
                        )
                        fig_d.for_each_annotation(lambda a: a.update(
                            text=f"<b>{a.text.split('=')[-1]}</b>",
                            font=dict(size=14, color="#222"),
                        ))
                        st.plotly_chart(fig_d, use_container_width=True, config={"displayModeBar": False})

                    # ── Setup recommendation text ──────────
                    st.divider()
                    st.markdown('<p class="section-title">Setup Direction Summary</p>', unsafe_allow_html=True)
                    for _, sr in df_sum.iterrows():
                        rider = sr["Rider"]; circ = sr["Circuit"]
                        parts = []
                        for col, short in bar_metrics:
                            v = sr.get(col)
                            if v is None or (isinstance(v, float) and pd.isna(v)): continue
                            if abs(v) < 0.3:
                                parts.append(f"{short}: ≈ same")
                            elif v > 0:
                                parts.append(f"{short}: **+{v:.1f} mm** ↑ (more compression when fast)")
                            else:
                                parts.append(f"{short}: **{v:.1f} mm** ↓ (less compression when fast)")
                        if parts:
                            with st.expander(f"**{rider} @ {circ}** — {sr['N Sessions']} sessions · Best {sr['Best Lap']}", expanded=False):
                                for p in parts:
                                    st.markdown(f"  • {p}")

                # ── Detail table ──────────────────────────
                st.divider()
                st.markdown('<p class="section-title">All Matched Sessions</p>', unsafe_allow_html=True)
                disp_m = df_m_f[["rider","circuit","date","run","best_s","tier",
                                  "apex_susF","apex_susR","brk_susF","brk_susR","apex_spd"]].copy()
                disp_m["best_lap"] = disp_m["best_s"].apply(
                    lambda s: f"{int(s)//60}:{s%60:06.3f}" if pd.notna(s) else "—")
                disp_m = disp_m.drop(columns=["best_s"])
                disp_m.columns = ["Rider","Circuit","Date","Run","Tier",
                                   "APEX SusF","APEX SusR","Brk SusF","Brk SusR",
                                   "APEX Spd","Best Lap"]

                def _tier_color(v):
                    return {"FAST":"background-color:#C6EFCE","MED":"background-color:#FFEB9C",
                            "SLOW":"background-color:#FFC7CE"}.get(v,"")

                _styler_fn2 = getattr(disp_m.style, "map", None) or getattr(disp_m.style, "applymap")
                st.dataframe(
                    _styler_fn2(_tier_color, subset=["Tier"]),
                    use_container_width=True, height=360
                )


    # ═══════════════════════════════════════════════════
    # PAGE — Corner Phase Analysis
    # ═══════════════════════════════════════════════════
    elif _NAV == "🔄  Corner Phase":
        st.markdown('<p class="section-title">🔄 Corner Phase Analysis — PH1-2 / PH3 / PH4-5 Timing</p>',
                    unsafe_allow_html=True)

        PH12_COLOR = "#0078D4"
        PH3_COLOR  = "#107C10"
        PH45_COLOR = "#D83B01"

        df_cp = _load_corner_phase()

        if df_cp.empty:
            st.warning("corner_phase_data.json が見つかりません。`python corner_phase_analysis.py` を実行してください。")
        else:
            # ── フィルター ────────────────────────────────────────────
            cp_circuits_raw = sorted(df_cp["circuit"].dropna().unique().tolist())
            # デフォルト: 最新日付のサーキット
            if cp_circuits_raw:
                _latest_circ_cp = (
                    df_cp.sort_values("date", ascending=False)
                    .iloc[0]["circuit"]
                )
            else:
                _latest_circ_cp = cp_circuits_raw[0] if cp_circuits_raw else "All"

            f1, f2, f3 = st.columns(3)
            with f1:
                cp_circuit = st.selectbox("Circuit", cp_circuits_raw,
                                          index=cp_circuits_raw.index(_latest_circ_cp)
                                          if _latest_circ_cp in cp_circuits_raw else 0,
                                          key="cp_circuit")
            df_c = df_cp[df_cp["circuit"] == cp_circuit].copy()

            with f2:
                cp_riders = sorted(df_c["rider"].dropna().unique().tolist())
                cp_rider  = st.selectbox("Rider", cp_riders, key="cp_rider")
            df_c = df_c[df_c["rider"] == cp_rider]

            with f3:
                cp_sessions = sorted(df_c["session_type"].dropna().unique().tolist())
                cp_session  = st.selectbox("Session", cp_sessions, key="cp_session")
            df_c = df_c[df_c["session_type"] == cp_session]

            cp_runs = sorted(df_c["run_no"].dropna().unique().tolist())
            if cp_runs:
                cp_run = st.selectbox("Run No", cp_runs,
                                      index=len(cp_runs) - 1, key="cp_run")
                df_c = df_c[df_c["run_no"] == cp_run]

            if df_c.empty:
                st.info("このセッションのコーナーフェーズデータがありません。")
            else:
                # ── FAST / SLOW 分類 ──────────────────────────────────
                lap_times = df_c.groupby("lap_no")["lap_time_s"].first().dropna()
                if len(lap_times) < 3:
                    st.info(f"ラップ数が少なすぎます ({len(lap_times)} laps)。3ラップ以上必要です。")
                else:
                    n_group = max(1, len(lap_times) // 3)
                    sorted_laps = lap_times.sort_values()
                    fast_laps   = set(sorted_laps.head(n_group).index.tolist())
                    slow_laps   = set(sorted_laps.tail(n_group).index.tolist())

                    df_fast = df_c[df_c["lap_no"].isin(fast_laps)]
                    df_slow = df_c[df_c["lap_no"].isin(slow_laps)]

                    # KPI
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Total Laps", len(lap_times))
                    k2.metric("FAST Laps (top 1/3)", len(fast_laps),
                              f"avg {sorted_laps.head(n_group).mean():.3f}s")
                    k3.metric("SLOW Laps (bot 1/3)", len(slow_laps),
                              f"avg {sorted_laps.tail(n_group).mean():.3f}s")
                    all_corners = sorted(df_c["corner_no"].dropna().unique().tolist())
                    k4.metric("Corners detected", len(all_corners))

                    st.divider()

                    # ── SECTION A: FAST vs SLOW Δtime per corner ─────
                    st.markdown('<p class="section-title">Section A — FAST vs SLOW Δtime per Corner (SLOW − FAST)</p>',
                                unsafe_allow_html=True)

                    _phase_cols = ["ph12_duration_ms", "ph3_duration_ms", "ph45_duration_ms"]
                    _phase_labels = {"ph12_duration_ms": "PH1-2",
                                     "ph3_duration_ms":  "PH3",
                                     "ph45_duration_ms": "PH4-5"}
                    _phase_colors = {"PH1-2": PH12_COLOR,
                                     "PH3":   PH3_COLOR,
                                     "PH4-5": PH45_COLOR}

                    delta_rows = []
                    for cn in all_corners:
                        fast_cn = df_fast[df_fast["corner_no"] == cn]
                        slow_cn = df_slow[df_slow["corner_no"] == cn]
                        if fast_cn.empty or slow_cn.empty:
                            continue
                        for col in _phase_cols:
                            f_avg = fast_cn[col].dropna().mean()
                            s_avg = slow_cn[col].dropna().mean()
                            if pd.notna(f_avg) and pd.notna(s_avg):
                                delta_rows.append({
                                    "Corner":   f"C{int(cn)}",
                                    "Phase":    _phase_labels[col],
                                    "Δ (ms)":  round(s_avg - f_avg, 1),
                                })

                    if delta_rows:
                        df_delta = pd.DataFrame(delta_rows)
                        corner_order = [f"C{int(c)}" for c in sorted(all_corners)]
                        fig_delta = go.Figure()
                        for phase, color in _phase_colors.items():
                            dph = df_delta[df_delta["Phase"] == phase]
                            if dph.empty:
                                continue
                            # align to corner_order
                            dph_map = dict(zip(dph["Corner"], dph["Δ (ms)"]))
                            vals    = [dph_map.get(c, 0) for c in corner_order]
                            fig_delta.add_trace(go.Bar(
                                name=phase,
                                y=corner_order,
                                x=vals,
                                orientation="h",
                                marker_color=color,
                                text=[f"{v:+.0f}" for v in vals],
                                textposition="outside",
                                textfont=dict(size=9),
                            ))
                        fig_delta.add_vline(x=0, line_color="#333", line_width=1.5,
                                            line_dash="dot")
                        chart_layout(fig_delta, height=max(300, len(all_corners) * 28))
                        fig_delta.update_layout(
                            barmode="stack",
                            xaxis_title="Δ time ms (SLOW − FAST)  [positive = slower]",
                            yaxis_title="Corner",
                            yaxis=dict(autorange="reversed"),
                            legend=dict(orientation="h", y=1.04),
                        )
                        st.plotly_chart(fig_delta, use_container_width=True,
                                        config={"displayModeBar": False})
                    else:
                        st.info("FAST/SLOW 比較データ不足。")

                    st.divider()

                    # ── SECTION B: APEX Speed Heatmap ────────────────
                    st.markdown('<p class="section-title">Section B — APEX Speed Heatmap (ph3_speed_min km/h)</p>',
                                unsafe_allow_html=True)

                    lap_order = sorted(df_c["lap_no"].dropna().unique().tolist())
                    hm_data = []
                    for cn in all_corners:
                        row_vals = []
                        for ln in lap_order:
                            val = df_c[(df_c["corner_no"] == cn) & (df_c["lap_no"] == ln)]["ph3_speed_min"]
                            row_vals.append(float(val.iloc[0]) if len(val) > 0 and pd.notna(val.iloc[0]) else None)
                        hm_data.append(row_vals)

                    # fill None with np.nan for plotly
                    import math as _math
                    hm_z = [[v if v is not None else float("nan") for v in row] for row in hm_data]

                    fig_hm = go.Figure(data=go.Heatmap(
                        z=hm_z,
                        x=[f"Lap {ln}" for ln in lap_order],
                        y=[f"C{int(cn)}" for cn in all_corners],
                        colorscale=[[0, "#D83B01"], [0.5, "#FFF2CC"], [1, "#0078D4"]],
                        colorbar=dict(title="Speed (km/h)", tickfont=dict(size=10)),
                        hovertemplate="Corner %{y}<br>%{x}<br>Speed: %{z:.1f} km/h<extra></extra>",
                    ))
                    chart_layout(fig_hm, height=max(300, len(all_corners) * 26))
                    fig_hm.update_layout(
                        xaxis_title="Lap",
                        yaxis_title="Corner",
                        yaxis=dict(autorange="reversed"),
                    )
                    st.plotly_chart(fig_hm, use_container_width=True,
                                    config={"displayModeBar": False})

                    st.divider()

                    # ── SECTION C: Phase timing detail table ─────────
                    st.markdown('<p class="section-title">Phase Timing Detail — per Lap</p>',
                                unsafe_allow_html=True)
                    disp_cols = ["lap_no","corner_no","lap_time_s",
                                 "ph12_duration_ms","ph12_brake_peak_bar",
                                 "ph3_duration_ms","ph3_speed_min","ph3_susf_avg",
                                 "ph45_duration_ms","ph45_gas_avg","total_corner_ms"]
                    disp_cp = df_c[[c for c in disp_cols if c in df_c.columns]].copy()
                    # ラップタイムを mm:ss.00 形式に変換
                    if "lap_time_s" in disp_cp.columns:
                        def _fmt_lt(sec):
                            if sec is None or (isinstance(sec, float) and pd.isna(sec)):
                                return "—"
                            m = int(sec // 60); s = sec - m * 60
                            return f"{m}:{s:05.2f}"
                        disp_cp["lap_time_s"] = disp_cp["lap_time_s"].apply(_fmt_lt)
                    disp_cp.columns = [c.replace("_", " ").upper() for c in disp_cp.columns]
                    st.dataframe(disp_cp, use_container_width=True, height=340)

        render_float_chat_component(
            st.session_state.get("claude_api_key", ""),
            st.session_state.get("race_memory", {}),
            {"page": "Corner Phase", "circuit": sel_circuit, "rider": sel_rider},
        )

    # ═══════════════════════════════════════════════════
    # PAGE 7 — Trend Analysis
    # ═══════════════════════════════════════════════════
    elif _NAV == "📉  Trend Analysis":
        st.markdown('<p class="section-title">Lap Time Trend — Season Overview</p>', unsafe_allow_html=True)

        if laps.empty:
            st.info("No lap time data. Run lap_sync.py to import Chrono Analysis PDFs.")
        else:
            df_lap = laps.copy()
            df_lap = df_lap[df_lap["rider_num"].isin([77, 52])]
            df_lap["rider_id"] = df_lap["rider_num"].map({77: "DA77", 52: "JA52"})

            # Filter: valid laps only
            if "is_valid" in df_lap.columns:
                df_lap = df_lap[df_lap["is_valid"] == 1]

            # Compute per-session best lap
            best_laps = (
                df_lap.groupby(["round_id", "session_type", "rider_id"])["lap_time"]
                .min().reset_index(name="best_lap_s")
            )
            best_laps["best_lap_str"] = best_laps["best_lap_s"].apply(
                lambda s: f"{int(s)//60}:{s%60:06.3f}" if pd.notna(s) else "—"
            )
            best_laps["session_label"] = best_laps["round_id"] + " " + best_laps["session_type"]

            # ── Session filter ──
            session_types_avail = sorted(best_laps["session_type"].unique())
            sel_st = st.multiselect(
                "Session type", session_types_avail,
                default=[s for s in ["FP", "SP", "RACE1", "RACE2"] if s in session_types_avail],
                key="trend_ses"
            )
            if sel_st:
                best_laps = best_laps[best_laps["session_type"].isin(sel_st)]

            # ── Best lap trend chart ──
            if not best_laps.empty:
                fig_bl = px.line(
                    best_laps.sort_values("session_label"),
                    x="session_label", y="best_lap_s",
                    color="rider_id",
                    markers=True,
                    color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                    hover_data={"best_lap_str": True, "session_type": True},
                    labels={"session_label": "", "best_lap_s": "Best Lap (s)", "rider_id": "Rider"},
                )
                fig_bl.update_traces(marker=dict(size=9), line=dict(width=2.5))
                chart_layout(fig_bl, height=320, title="Best Lap per Session")
                fig_bl.update_layout(xaxis_tickangle=-35)
                st.plotly_chart(fig_bl, use_container_width=True, config={"displayModeBar": False})

            # ── Lap count per round ──
            st.markdown('<p class="section-title">Total Laps per Round</p>', unsafe_allow_html=True)
            lap_cnt = (
                df_lap.groupby(["round_id", "rider_id"]).size().reset_index(name="lap_count")
            )
            if not lap_cnt.empty:
                fig_lc = px.bar(
                    lap_cnt, x="round_id", y="lap_count", color="rider_id",
                    barmode="group",
                    color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                    labels={"round_id": "", "lap_count": "Laps", "rider_id": "Rider"},
                )
                chart_layout(fig_lc, height=260)
                st.plotly_chart(fig_lc, use_container_width=True, config={"displayModeBar": False})

            # ── Lap time distribution by round ──
            st.markdown('<p class="section-title">Lap Time Distribution by Round</p>', unsafe_allow_html=True)
            rider_trend = st.radio("Rider", ["DA77", "JA52"], horizontal=True, key="trend_rider")
            df_dist = df_lap[df_lap["rider_id"] == rider_trend]
            if not df_dist.empty:
                rounds_avail = sorted(df_dist["round_id"].unique())
                sel_rounds_t = st.multiselect("Rounds", rounds_avail, default=rounds_avail[-3:] if len(rounds_avail) >= 3 else rounds_avail, key="trend_rounds")
                if sel_rounds_t:
                    df_dist = df_dist[df_dist["round_id"].isin(sel_rounds_t)]
                    fig_box = px.box(
                        df_dist, x="round_id", y="lap_time",
                        color="round_id",
                        labels={"round_id": "", "lap_time": "Lap Time (s)"},
                        title=f"{rider_trend} — Lap Time Distribution",
                    )
                    chart_layout(fig_box, height=300)
                    fig_box.update_layout(showlegend=False)
                    st.plotly_chart(fig_box, use_container_width=True, config={"displayModeBar": False})

            # ── Gap DA77 vs JA52 per round ──
            st.markdown('<p class="section-title">Gap DA77 vs JA52 (Best Lap Delta)</p>', unsafe_allow_html=True)
            pivot_gap = best_laps.pivot_table(index="session_label", columns="rider_id", values="best_lap_s")
            if "DA77" in pivot_gap.columns and "JA52" in pivot_gap.columns:
                pivot_gap["gap"] = (pivot_gap["DA77"] - pivot_gap["JA52"]).round(3)
                pivot_gap = pivot_gap.dropna(subset=["gap"]).reset_index()
                fig_gap = px.bar(
                    pivot_gap, x="session_label", y="gap",
                    color=pivot_gap["gap"].apply(lambda x: "DA77 faster" if x < 0 else "JA52 faster"),
                    color_discrete_map={"DA77 faster": DA77_COLOR, "JA52 faster": JA52_COLOR},
                    labels={"session_label": "", "gap": "Gap (s) — negative = DA77 faster"},
                )
                chart_layout(fig_gap, height=260, title="DA77 − JA52 Best Lap Gap")
                fig_gap.update_layout(xaxis_tickangle=-35, showlegend=True)
                st.plotly_chart(fig_gap, use_container_width=True, config={"displayModeBar": False})


    # ═══════════════════════════════════════════════════
    # PAGE 8 — AI Advice
    # ═══════════════════════════════════════════════════
    elif _NAV == "🤖  AI Advice":
        st.markdown('<p class="section-title">AI Setup Advice — Claude Analysis</p>', unsafe_allow_html=True)

        if not claude_ready:
            st.warning("⚠️  Anthropic API key required. Enter it above.")
        else:
            # Session state for persisting response across reruns
            if "adv_response"    not in st.session_state: st.session_state["adv_response"]    = ""
            if "adv_tag_summary" not in st.session_state: st.session_state["adv_tag_summary"] = None
            if "adv_ctx_caption" not in st.session_state: st.session_state["adv_ctx_caption"] = ""

            col_a1, col_a2 = st.columns([1, 2], gap="medium")

            # ── LEFT: all inputs wrapped in form (no rerun on widget change) ──
            with col_a1:
                st.markdown("**Analysis Settings**")
                with st.form("adv_form", clear_on_submit=False):
                    advice_rider   = st.selectbox("Rider", ["DA77", "JA52", "Both"])
                    advice_circuit = st.selectbox("Circuit",
                        ["(current filter)"] + sorted(sessions["circuit"].dropna().unique()))
                    advice_focus   = st.selectbox("Focus area", [
                        "Overall setup recommendation",
                        "Front end (braking & entry)",
                        "Rear grip & traction",
                        "Mid-corner balance",
                        "High-speed stability",
                        "Race pace consistency",
                    ])
                    advice_extra = st.text_area(
                        "Additional context / specific question", height=100,
                        placeholder="e.g. 'Rider says front chatters on long left-handers'")
                    submitted = st.form_submit_button(
                        "🤖  Generate AI Advice", type="primary", use_container_width=True)

            # ── Process on submit (only one rerun, on button click) ──
            if submitted:
                ctx_rider_filter = None if advice_rider == "Both" else advice_rider
                ctx_sessions_adv = df_s.copy() if ctx_rider_filter is None else df_s[df_s["rider"] == ctx_rider_filter]
                ctx_circuit_adv  = advice_circuit if advice_circuit != "(current filter)" else sel_circuit
                if ctx_circuit_adv != "All":
                    ctx_sessions_adv = ctx_sessions_adv[
                        ctx_sessions_adv["circuit"].str.upper() == ctx_circuit_adv.upper()]
                ctx_tags_adv  = df_t[df_t["session_id"].isin(ctx_sessions_adv["session_id"])]
                tag_summary_adv = (ctx_tags_adv.groupby(["phase","tag"]).size()
                                   .reset_index(name="n").sort_values("n", ascending=False).head(15))
                tag_text = "\n".join([f"  {r['phase']} | {r['tag']} — {r['n']} sessions"
                                      for _, r in tag_summary_adv.iterrows()])
                best_lap_text = ""
                if not laps.empty:
                    bl_df = laps[laps["is_valid"] == 1] if "is_valid" in laps.columns else laps.copy()
                    if ctx_rider_filter:
                        bl_df = bl_df[bl_df["rider_num"] == (77 if ctx_rider_filter == "DA77" else 52)]
                    best_s = bl_df.groupby(["round_id","session_type"])["lap_time"].min().reset_index().tail(10)
                    best_lap_text = "\n".join([
                        f"  {r['round_id']} {r['session_type']}: {int(r['lap_time'])//60}:{r['lap_time']%60:06.3f}"
                        for _, r in best_s.iterrows()])
                system_prompt = (
                    "You are an expert motorcycle racing engineer in WorldSSP. "
                    "Analyze the provided session data and give specific, actionable setup recommendations. "
                    "Be concise and technical. Use motorcycle engineering terminology. Respond in English.")
                user_msg = (
                    f"Rider: {advice_rider}\nCircuit: {ctx_circuit_adv}\nFocus: {advice_focus}\n\n"
                    f"Problem tag history:\n{tag_text or 'No tag data'}\n\n"
                    f"Recent best laps:\n{best_lap_text or 'No data'}\n\n"
                    f"Additional context: {advice_extra or 'None'}\n\n"
                    "Please provide specific setup recommendations.")
                with st.spinner("Asking Claude..."):
                    resp = call_claude(st.session_state["claude_api_key"], user_msg, system_prompt, 1500)
                st.session_state["adv_response"]    = resp
                st.session_state["adv_tag_summary"] = tag_summary_adv
                st.session_state["adv_ctx_caption"] = (
                    f"Sessions: {len(ctx_sessions_adv)} | Problem tags: {len(ctx_tags_adv)}")

            # ── RIGHT: context preview + response (from session state) ──
            with col_a2:
                if st.session_state["adv_ctx_caption"]:
                    st.markdown("**Data context sent to Claude:**")
                    st.caption(st.session_state["adv_ctx_caption"])
                    if st.session_state["adv_tag_summary"] is not None and not st.session_state["adv_tag_summary"].empty:
                        st.dataframe(st.session_state["adv_tag_summary"],
                                     hide_index=True, use_container_width=True, height=200)
                if st.session_state["adv_response"]:
                    st.divider()
                    st.markdown("**Claude's Setup Recommendations:**")
                    # Use native st.markdown — properly renders Claude's markdown output
                    st.markdown(st.session_state["adv_response"])


    # ═══════════════════════════════════════════════════
    # PAGE 9 — Setup Chat
    # ═══════════════════════════════════════════════════
    elif _NAV == "💬  Setup Chat":
        st.markdown('<p class="section-title">Setup Chat — Direct Consultation with Claude</p>', unsafe_allow_html=True)

        if not claude_ready:
            st.warning("⚠️  Anthropic API key required. Enter it above.")
        else:
            if "chat_history" not in st.session_state:
                st.session_state["chat_history"] = []

            CHAT_SYSTEM = (
                "You are a senior motorcycle racing engineer in WorldSSP. "
                "You are helping the team's setup engineer discuss and solve chassis and setup problems. "
                "Riders: DA77 and JA52. "
                "Be direct, technical, and practical. Give specific values and ranges when relevant. "
                "Respond in English unless explicitly asked otherwise.")

            # ── Controls (outside form — these cause reruns but no problem) ──
            col_c1, col_c2 = st.columns([2, 1])
            with col_c1:
                inject_ctx = st.toggle("Include DB context", value=True, key="chat_ctx")
            with col_c2:
                if st.button("🗑  Clear chat", key="chat_clear"):
                    st.session_state["chat_history"] = []

            # ── Chat history — native chat_message (no HTML, no scroll issue) ──
            for msg in st.session_state["chat_history"]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            # ── Input — st.chat_input stays at bottom, no page scroll reset ──
            user_input = st.chat_input(
                "Ask about setup — e.g. 'DA77 has front chatter in turn 5, what should we check?'")

            if user_input:
                # Show user bubble immediately
                with st.chat_message("user"):
                    st.markdown(user_input)
                st.session_state["chat_history"].append({"role": "user", "content": user_input})

                # Build context snippet
                ctx_snippet = ""
                if inject_ctx:
                    recent_tags = df_t_event.groupby("tag").size().nlargest(5).index.tolist()
                    recent_sessions = df_s.sort_values("session_date", ascending=False).head(3)
                    ctx_lines = [
                        f"  {rs.get('session_date','')} | {rs.get('rider','')} | "
                        f"{rs.get('circuit','')} | {rs.get('session_type','')} | Best: {rs.get('best_lap','—')}"
                        for _, rs in recent_sessions.iterrows()
                    ]
                    ctx_snippet = (
                        f"\n\n[DB Context] Top issues: {', '.join(recent_tags)}\n"
                        + "\n".join(ctx_lines))

                # Build full message list for API (history + current)
                messages = [{"role": h["role"], "content": h["content"]}
                            for h in st.session_state["chat_history"][:-1]]
                messages.append({"role": "user", "content": user_input + ctx_snippet})

                payload = {
                    "model":      CLAUDE_API_MODEL,
                    "max_tokens": 1500,
                    "system":     CHAT_SYSTEM,
                    "messages":   messages,
                }
                data = json.dumps(payload).encode("utf-8")
                req  = urllib.request.Request(
                    CLAUDE_API_URL, data=data,
                    headers={"x-api-key": st.session_state["claude_api_key"],
                             "anthropic-version": "2023-06-01",
                             "content-type": "application/json"})

                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        try:
                            with urllib.request.urlopen(req, timeout=90) as resp:
                                result        = json.loads(resp.read().decode("utf-8"))
                                assistant_reply = result["content"][0]["text"]
                        except urllib.error.HTTPError as e:
                            body = e.read().decode("utf-8", errors="replace")
                            try:
                                err = json.loads(body)
                                assistant_reply = f"API Error {e.code}: {err.get('error',{}).get('message', body)}"
                            except Exception:
                                assistant_reply = f"API Error {e.code}: {body}"
                        except Exception as ex:
                            assistant_reply = f"Error: {type(ex).__name__}: {ex}"
                    st.markdown(assistant_reply)

                st.session_state["chat_history"].append(
                    {"role": "assistant", "content": assistant_reply})

    # ═══════════════════════════════════════════════════
    # PAGE 10 — Submit Data (engineer + viewer + admin)
    # ═══════════════════════════════════════════════════
    elif _NAV == "📤  Submit Data":
        st.markdown('<p class="section-title">📤 Submit Session Data</p>', unsafe_allow_html=True)

        # Role check: all roles can upload (viewer = read + upload)
        _submit_role = get_user_role(st.session_state.get("current_user", ""))
        if _submit_role not in ("admin", "engineer", "viewer"):
            st.error("⛔  You do not have permission to access this page.")
            st.stop()

        cfg10       = load_config()
        supa_url10  = cfg10.get("supabase_url", "")
        anon_key10  = cfg10.get("supabase_anon_key", "")
        submit_user = st.session_state.get("current_user", "unknown")
        submit_rider_default = get_user_rider(submit_user) or "DA77"

        if not supa_url10 or not anon_key10:
            st.warning("⚠️  Supabase is not configured. Please contact the administrator.")
        else:
            sub_tab1, sub_tab2 = st.tabs(["📊 Excel Upload (Recommended)", "📋 Manual Form"])

            # ── Excel Upload (Recommended) ───────────────────
            with sub_tab1:
                st.markdown("#### Steps")
                st.markdown(
                    "1. **Download the template** and fill it in\n"
                    "2. Upload the completed Excel file here\n"
                    "3. Review the contents and submit"
                )

                # Template download link
                tmpl_path = SCRIPT_DIR.parent / "03_TEMPLATES" / "NEW_EVENT_TEAM_REPORT_TEMPLATE.xlsx"
                if tmpl_path.exists():
                    with open(tmpl_path, "rb") as f:
                        tmpl_bytes = f.read()
                    st.download_button(
                        "📥 Download Template",
                        data=tmpl_bytes,
                        file_name="NEW_EVENT_TEAM_REPORT_TEMPLATE.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

                st.divider()
                uploaded = st.file_uploader(
                    "Upload completed Excel file",
                    type=["xlsx", "xlsm"],
                    key="excel_upload"
                )

                if uploaded:
                    try:
                        from excel_parser import parse_report_excel
                        file_bytes = uploaded.read()
                        parsed = parse_report_excel(file_bytes, submit_user)

                        if parsed["errors"]:
                            for err in parsed["errors"]:
                                st.warning(f"⚠️ {err}")

                        sessions_p = parsed["sessions"]
                        laps_p     = parsed["laps"]

                        if not sessions_p:
                            st.error("No session data found in the file.")
                        else:
                            st.success(f"✅ Parsed: **{len(sessions_p)} sessions** / **{len(laps_p)} laps** detected")

                            # Preview
                            with st.expander("📋 Data Preview", expanded=True):
                                prev_cols = ["session_date","circuit","session_type","rider",
                                             "track_temp","f_tyre","r_tyre","best_lap"]
                                prev_data = [{k: s.get(k) for k in prev_cols} for s in sessions_p]
                                st.dataframe(pd.DataFrame(prev_data), use_container_width=True, hide_index=True)

                            if st.button("📤 Submit to Supabase", type="primary", use_container_width=True,
                                         key="excel_submit_btn"):
                                ok_s, ok_l = 0, 0
                                for sess in sessions_p:
                                    if supa_insert("pending_sessions", sess, anon_key10, supa_url10) is not False:
                                        ok_s += 1
                                for lap in laps_p:
                                    if supa_insert("pending_lap_times", lap, anon_key10, supa_url10) is not False:
                                        ok_l += 1
                                st.success(f"✅ Submitted! Sessions: {ok_s} / Laps: {ok_l}\nAwaiting administrator approval.")
                                st.cache_data.clear()
                    except ImportError:
                        st.error("excel_parser.py not found. Please contact the administrator.")
                    except Exception as e:
                        st.error(f"Parse error: {e}")

            # ── Manual Form (sub-tab) ────────────────────────
            with sub_tab2:
                with st.form("submit_session_form", clear_on_submit=True):
                    st.markdown("**Session Info**")
                    c1, c2, c3, c4 = st.columns(4)
                    s_date   = c1.date_input("Date")
                    s_circuit = c2.text_input("Circuit", placeholder="e.g. ASSEN")
                    s_type   = c3.selectbox("Session", ["FP", "SP", "WUP", "RACE1", "RACE2", "TEST"])
                    s_rider  = c4.selectbox("Rider", ["DA77", "JA52"],
                                            index=0 if submit_rider_default == "DA77" else 1)

                    st.markdown("**Conditions**")
                    cc1, cc2 = st.columns(2)
                    s_ttrack = cc1.number_input("Track Temp (°C)", value=25.0, step=0.5)
                    s_tair   = cc2.number_input("Air Temp (°C)",   value=22.0, step=0.5)

                    st.markdown("**Front Suspension**")
                    f1, f2, f3, f4, f5 = st.columns(5)
                    s_ftype    = f1.text_input("Fork Type", placeholder="e.g. SHOWA")
                    s_fspring  = f2.text_input("F Spring",  placeholder="e.g. 9.5N")
                    s_fpreload = f3.number_input("F Preload", value=10.0, step=0.5)
                    s_fcomp    = f4.number_input("F Comp",   value=12, step=1)
                    s_freb     = f5.number_input("F Reb",    value=12, step=1)

                    st.markdown("**Rear Suspension**")
                    r1, r2, r3, r4, r5, r6 = st.columns(6)
                    s_stype    = r1.text_input("Shock Type", placeholder="e.g. OHLINS")
                    s_rspring  = r2.number_input("R Spring",  value=85.0, step=0.5)
                    s_rpreload = r3.number_input("R Preload", value=8.0, step=0.5)
                    s_rcomp    = r4.number_input("R Comp",    value=10, step=1)
                    s_rreb     = r5.number_input("R Reb",     value=10, step=1)
                    s_swing    = r6.number_input("Swing Arm", value=0, step=1)

                    st.markdown("**Geometry & Tyres**")
                    g1, g2, g3, g4 = st.columns(4)
                    s_rh     = g1.number_input("Ride Height (mm)", value=0.0, step=0.5)
                    s_ftyre  = g2.text_input("F Tyre", placeholder="e.g. SCX")
                    s_rtyre  = g3.text_input("R Tyre", placeholder="e.g. SCX")
                    s_bestlap = g4.text_input("Best Lap", placeholder="e.g. 1:38.500")

                    st.markdown("**Rider Comments (Phase by Phase)**")
                    p1, p2 = st.columns(2)
                    s_ph1 = p1.text_area("PH1 Braking",  height=80, key="ph1")
                    s_ph2 = p1.text_area("PH2 Entry",    height=80, key="ph2")
                    s_ph3 = p1.text_area("PH3 Apex",     height=80, key="ph3")
                    s_ph4 = p2.text_area("PH4 Exit",     height=80, key="ph4")
                    s_ph5 = p2.text_area("PH5 Hi-Speed", height=80, key="ph5")
                    s_pho = p2.text_area("Other",        height=80, key="pho")

                    st.markdown("**Engineer Notes**")
                    e1, e2 = st.columns(2)
                    s_enote  = e1.text_area("Engineer Note", height=80)
                    s_next   = e2.text_area("Next Action",   height=80)

                    submitted10 = st.form_submit_button("📤 Submit to Cloud DB", type="primary",
                                                        use_container_width=True)

                if submitted10:
                    payload = {
                        "submitted_by":  submit_user,
                        "session_date": str(s_date),
                        "circuit":      s_circuit.upper(),
                        "session_type": s_type,
                        "rider":        s_rider,
                        "bike_model":   "",
                        "track_temp":   s_ttrack,
                        "air_temp":     s_tair,
                        "fork_type":    s_ftype,
                        "f_spring":     s_fspring,
                        "f_preload":    s_fpreload,
                        "f_comp":       int(s_fcomp),
                        "f_reb":        int(s_freb),
                        "shock_type":   s_stype,
                        "r_spring":     s_rspring,
                        "r_preload":    s_rpreload,
                        "r_comp":       int(s_rcomp),
                        "r_reb":        int(s_rreb),
                        "swing_arm":    int(s_swing),
                        "ride_height":  s_rh,
                        "f_tyre":       s_ftyre,
                        "r_tyre":       s_rtyre,
                        "best_lap":     s_bestlap,
                        "ph1_braking":  s_ph1,
                        "ph2_entry":    s_ph2,
                        "ph3_mid":      s_ph3,
                        "ph4_exit":     s_ph4,
                        "ph5_speed":    s_ph5,
                        "ph_other":     s_pho,
                        "engineer_note": s_enote,
                        "next_action":   s_next,
                        "status":        "pending",
                    }
                    ok = supa_insert("pending_sessions", payload, anon_key10, supa_url10)
                    if ok is not False:
                        st.success("✅ Submitted! Awaiting administrator approval.")
                    else:
                        st.error("Submission failed. Please check your network connection.")

            # ── Lap Time Submission ──────────────────────────
            with sub_tab2:
                with st.form("submit_laps_form", clear_on_submit=True):
                    st.markdown("**Session Info**")
                    lc1, lc2, lc3, lc4 = st.columns(4)
                    l_round   = lc1.text_input("Round ID", placeholder="e.g. ROUND3")
                    l_circuit = lc2.text_input("Circuit",  placeholder="e.g. ASSEN")
                    l_stype   = lc3.selectbox("Session", ["FP", "SP", "WUP", "RACE1", "RACE2", "TEST"])
                    l_rider   = lc4.selectbox("Rider", ["DA77 (77)", "JA52 (52)"],
                                              index=0 if submit_rider_default == "DA77" else 1)

                    st.markdown("**Lap Times** (one row per lap: lap_no, seg1, seg2, seg3, seg4, lap_time, speed)")
                    st.caption("Example: 1, 28.5, 27.3, 25.1, 17.6, 98.500, 189.2")
                    laps_text = st.text_area("Lap data (CSV format)", height=200,
                                             placeholder="1, 28.5, 27.3, 25.1, 17.6, 98.500, 189.2\n2, 28.1, 27.0, 24.9, 17.4, 97.400, 191.0")

                    submitted_laps = st.form_submit_button("📤 Submit Lap Times", type="primary",
                                                           use_container_width=True)

                if submitted_laps and laps_text.strip():
                    rider_num  = 77 if "77" in l_rider else 52
                    rider_name = "DA77" if rider_num == 77 else "JA52"
                    errors, count = [], 0
                    for i, line in enumerate(laps_text.strip().splitlines(), 1):
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) < 6:
                            errors.append(f"Row {i}: insufficient columns")
                            continue
                        try:
                            payload_l = {
                                "submitted_by": submit_user,
                                "round_id":     l_round,
                                "circuit":      l_circuit.upper(),
                                "session_type": l_stype,
                                "rider_num":    rider_num,
                                "rider_name":   rider_name,
                                "lap_no":       int(parts[0]),
                                "seg1":         float(parts[1]),
                                "seg2":         float(parts[2]),
                                "seg3":         float(parts[3]),
                                "seg4":         float(parts[4]),
                                "lap_time":     float(parts[5]),
                                "speed":        float(parts[6]) if len(parts) > 6 else None,
                                "flag":         parts[7] if len(parts) > 7 else "",
                                "is_valid":     1,
                                "status":       "pending",
                            }
                            supa_insert("pending_lap_times", payload_l, anon_key10, supa_url10)
                            count += 1
                        except Exception as e:
                            errors.append(f"Row {i}: {e}")
                    if count:
                        st.success(f"✅ {count} laps submitted! Awaiting administrator approval.")
                    if errors:
                        st.warning("Errors:\n" + "\n".join(errors))


    # ═══════════════════════════════════════════════════
    # PAGE 11 — Approvals (admin-only approval workflow)
    # ═══════════════════════════════════════════════════
    elif _NAV == "✅  Approvals":
        st.markdown('<p class="section-title">✅ Pending Approvals — Admin Only</p>', unsafe_allow_html=True)

        _a_user = st.session_state.get("current_user", "")
        _a_role = get_user_role(_a_user)

        if _a_role != "admin":
            st.warning("🔒 This tab is for administrators only.")
            st.stop()

        cfg11      = load_config()
        supa_url11 = cfg11.get("supabase_url", "")
        svc_key11  = cfg11.get("supabase_service_key", "")

        if not supa_url11 or not svc_key11 or svc_key11 == "PASTE_SERVICE_ROLE_KEY_HERE":
            st.error("⚠️  Supabase Service Role Key is not configured.")
            st.info("Enter the service_role key in the sidebar under '☁️ Supabase Settings'.\n"
                    "(Supabase Dashboard → Settings → API → service_role)")
        else:
            if st.button("🔄 Refresh Data from Supabase", key="refresh_approvals", type="primary"):
                st.cache_data.clear()

            # ── Session Reports ───────────────────────────────
            pending_s = supa_fetch("pending_sessions", svc_key11, supa_url11)

            st.markdown(f"### 📋 Session Reports — {len(pending_s)} pending")

            if not pending_s:
                st.info("No session reports pending approval.")
            else:
                for rec in pending_s:
                    with st.expander(
                        f"[{rec.get('submitted_by','?')}] "
                        f"{rec.get('session_date','?')} | {rec.get('circuit','?')} | "
                        f"{rec.get('session_type','?')} | Rider: {rec.get('rider','?')}",
                        expanded=False
                    ):
                        c_l, c_r = st.columns(2)
                        with c_l:
                            st.markdown("**Setup**")
                            st.write({
                                "Fork":    f"{rec.get('fork_type','')} / {rec.get('f_spring','')}",
                                "F Comp/Reb": f"{rec.get('f_comp','')} / {rec.get('f_reb','')}",
                                "Shock":   f"{rec.get('shock_type','')} / {rec.get('r_spring','')}",
                                "R Comp/Reb": f"{rec.get('r_comp','')} / {rec.get('r_reb','')}",
                                "Tyres":   f"F:{rec.get('f_tyre','')} R:{rec.get('r_tyre','')}",
                                "Best Lap": rec.get("best_lap", "—"),
                            })
                        with c_r:
                            st.markdown("**Rider Comments**")
                            for ph_key, ph_label in [
                                ("ph1_braking","PH1 Braking"), ("ph2_entry","PH2 Entry"),
                                ("ph3_mid","PH3 Apex"), ("ph4_exit","PH4 Exit"),
                                ("ph5_speed","PH5 Hi-Speed")
                            ]:
                                val = rec.get(ph_key, "")
                                if val:
                                    st.caption(f"**{ph_label}:** {val}")
                            if rec.get("engineer_note"):
                                st.caption(f"**Engineer Note:** {rec['engineer_note']}")

                        col_app, col_rej, _ = st.columns([1, 1, 4])
                        if col_app.button("✅ Approve", key=f"app_s_{rec['id']}", type="primary"):
                            # Update Supabase status to approved
                            supa_update_status("pending_sessions", rec["id"], "approved", svc_key11, supa_url11)
                            # Insert into local SQLite only if Mother DB is present
                            try:
                                if DB_PATH is None:
                                    st.info("ℹ️ Approved in Supabase. Sync to Mother DB will run automatically on local Mac.")
                                    st.rerun()
                                conn_a = sqlite3.connect(str(DB_PATH))
                                from datetime import datetime as _dt
                                conn_a.execute("""
                                    INSERT OR IGNORE INTO sessions
                                    (session_id, session_date, circuit, session_type, rider, bike_model,
                                     track_temp, air_temp, fork_type, f_spring, f_preload, f_comp, f_reb,
                                     shock_type, r_spring, r_preload, r_comp, r_reb, swing_arm, ride_height,
                                     f_tyre, r_tyre, best_lap, ph1_braking, ph2_entry, ph3_mid,
                                     ph4_exit, ph5_speed, ph_other, engineer_note, next_action,
                                     created_at, updated_at)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                """, (
                                    f"CLOUD_{rec['id']}_{rec.get('submitted_by','')}",
                                    rec.get("session_date"), rec.get("circuit"), rec.get("session_type"),
                                    rec.get("rider"), rec.get("bike_model", ""),
                                    rec.get("track_temp"), rec.get("air_temp"),
                                    rec.get("fork_type"), rec.get("f_spring"), rec.get("f_preload"),
                                    rec.get("f_comp"), rec.get("f_reb"),
                                    rec.get("shock_type"), rec.get("r_spring"), rec.get("r_preload"),
                                    rec.get("r_comp"), rec.get("r_reb"),
                                    rec.get("swing_arm"), rec.get("ride_height"),
                                    rec.get("f_tyre"), rec.get("r_tyre"), rec.get("best_lap"),
                                    rec.get("ph1_braking"), rec.get("ph2_entry"), rec.get("ph3_mid"),
                                    rec.get("ph4_exit"), rec.get("ph5_speed"), rec.get("ph_other"),
                                    rec.get("engineer_note"), rec.get("next_action"),
                                    _dt.now().isoformat(), _dt.now().isoformat()
                                ))
                                conn_a.commit()
                                conn_a.close()
                                st.success("✅ Approved and saved to Mother DB.")
                                st.cache_data.clear()
                            except Exception as e:
                                st.error(f"DB save error: {e}")

                        if col_rej.button("❌ Reject", key=f"rej_s_{rec['id']}"):
                            supa_update_status("pending_sessions", rec["id"], "rejected", svc_key11, supa_url11)
                            st.warning("Rejected.")

            st.divider()

            # ── Lap Times ────────────────────────────────────
            pending_l = supa_fetch("pending_lap_times", svc_key11, supa_url11)

            st.markdown(f"### ⏱ Lap Times — {len(pending_l)} pending")

            if not pending_l:
                st.info("No lap times pending approval.")
            else:
                import pandas as _pd_ap
                df_pending_l = _pd_ap.DataFrame(pending_l)
                st.dataframe(
                    df_pending_l[["id","submitted_by","round_id","circuit","session_type",
                                   "rider_name","lap_no","lap_time","speed","submitted_at"]],
                    use_container_width=True, hide_index=True
                )
                col_la, col_lr, _ = st.columns([1, 1, 4])
                if col_la.button("✅ Approve All Laps", key="app_all_laps", type="primary"):
                    if DB_PATH is None:
                        # Update Supabase only (sync to Mother DB runs automatically on local Mac)
                        for lap in pending_l:
                            supa_update_status("pending_lap_times", lap["id"], "approved", svc_key11, supa_url11)
                        st.success(f"✅ {len(pending_l)} laps approved in Supabase. Sync to Mother DB will run automatically on local Mac.")
                        st.cache_data.clear()
                        st.stop()
                    conn_b = sqlite3.connect(str(DB_PATH))
                    ok_count = 0
                    for lap in pending_l:
                        try:
                            conn_b.execute("""
                                INSERT OR IGNORE INTO lap_times
                                (round_id, circuit, session_type, rider_num, rider_name,
                                 lap_no, seg1, seg2, seg3, seg4, lap_time, speed, flag, is_valid)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """, (
                                lap.get("round_id"), lap.get("circuit"), lap.get("session_type"),
                                lap.get("rider_num"), lap.get("rider_name"), lap.get("lap_no"),
                                lap.get("seg1"), lap.get("seg2"), lap.get("seg3"), lap.get("seg4"),
                                lap.get("lap_time"), lap.get("speed"),
                                lap.get("flag", ""), lap.get("is_valid", 1)
                            ))
                            supa_update_status("pending_lap_times", lap["id"], "approved", svc_key11, supa_url11)
                            ok_count += 1
                        except Exception as e:
                            st.warning(f"Lap {lap.get('id')}: {e}")
                    conn_b.commit()
                    conn_b.close()
                    st.success(f"✅ {ok_count} laps saved to Mother DB.")
                    st.cache_data.clear()

                if col_lr.button("❌ Reject All Laps", key="rej_all_laps"):
                    for lap in pending_l:
                        supa_update_status("pending_lap_times", lap["id"], "rejected", svc_key11, supa_url11)
                    st.warning("All laps rejected.")


    # ═══════════════════════════════════════════════════
    # PAGE 13 — Problem→Solution Search
    # ═══════════════════════════════════════════════════
    elif _NAV == "🔍  Problem→Solution":
        st.markdown('<p class="section-title">🔍 Problem → Solution Search</p>', unsafe_allow_html=True)
        st.caption("Select a phenomenon (problem tag) to find past sessions, setups used, and engineer solutions.")

        # ── Data prep ──
        if tags.empty or sessions.empty:
            st.info("No session tag data available.")
        else:
            # Merge tags → sessions
            _ps_tags = tags.copy()
            _ps_sess = sessions.copy()

            # All unique tags
            all_tags_list = sorted(_ps_tags["tag"].dropna().unique().tolist())
            tag_labels = {
                "chattering_brake":  "🔴 Chattering (Brake)",
                "front_dive":        "🟠 Front Dive",
                "nervousness":       "🟡 Nervousness (Entry)",
                "no_turn_in":        "🟠 No Turn-In",
                "understeer_apex":   "🟢 Understeer (Apex)",
                "push_rear_exit":    "🔵 Push Rear (Exit)",
                "line_loss_exit":    "🟣 Line Loss (Exit)",
            }
            tag_display = [tag_labels.get(t, t) for t in all_tags_list]
            tag_map = dict(zip(tag_display, all_tags_list))

            # ── Filters ──
            col_f1, col_f2, col_f3 = st.columns([3, 1, 1])
            with col_f1:
                sel_phenomena = st.multiselect(
                    "Select Phenomenon (Problem Tag)",
                    options=tag_display,
                    default=tag_display[:1] if tag_display else [],
                    key="ps_tags",
                )
            with col_f2:
                phase_opts = ["All"] + sorted(_ps_tags["phase"].dropna().unique().tolist())
                sel_phase = st.selectbox("Phase", phase_opts, key="ps_phase")
            with col_f3:
                rider_opts = ["All", "DA77", "JA52"]
                sel_ps_rider = st.selectbox("Rider", rider_opts, key="ps_rider")

            selected_raw_tags = [tag_map[d] for d in sel_phenomena if d in tag_map]

            if not selected_raw_tags:
                st.info("Select at least one phenomenon above.")
            else:
                # Filter tags by selection + phase
                _ft = _ps_tags[_ps_tags["tag"].isin(selected_raw_tags)]
                if sel_phase != "All":
                    _ft = _ft[_ft["phase"] == sel_phase]

                # Unique session_ids that have all/any of the selected tags
                matched_sessions = _ft["session_id"].unique().tolist()

                # Filter sessions by rider
                _ms = _ps_sess[_ps_sess["session_id"].isin(matched_sessions)].copy()
                if sel_ps_rider != "All":
                    _ms = _ms[_ms["rider"] == sel_ps_rider]

                st.markdown(f"**{len(_ms)} session(s) found** with selected problem(s)")

                if _ms.empty:
                    st.warning("No sessions match the selected filters.")
                else:
                    # ── Best lap per session from lap_times ──
                    best_laps_map = {}
                    if not laps.empty:
                        _laps_iv = laps.copy()
                        _laps_iv["is_valid"] = pd.to_numeric(_laps_iv["is_valid"], errors="coerce").fillna(0)
                        _laps_valid = _laps_iv[_laps_iv["is_valid"] != 0].copy()
                        _laps_valid["lap_time"] = pd.to_numeric(_laps_valid["lap_time"], errors="coerce")
                        _laps_valid["_rnum_str"] = pd.to_numeric(_laps_valid["rider_num"], errors="coerce").apply(
                            lambda x: str(int(x)) if pd.notna(x) else "")
                        rider_num_map_ps = {"DA77": "77", "JA52": "52"}
                        for _, _lrow in _ms.iterrows():
                            sid = _lrow["session_id"]  # e.g. 20260220-ROUND1-DA77
                            parts = sid.split("-")
                            if len(parts) >= 3:
                                _rnd = parts[1]  # ROUND1
                                _rider_key = parts[2]  # DA77
                                _rnum_s = rider_num_map_ps.get(_rider_key)
                                if _rnum_s:
                                    _lap_sub = _laps_valid[
                                        (_laps_valid["round_id"] == _rnd) &
                                        (_laps_valid["_rnum_str"] == _rnum_s)
                                    ]
                                    if not _lap_sub.empty:
                                        best_laps_map[sid] = _lap_sub["lap_time"].min()

                    # ── NaN-safe helper ──
                    def _sv(val, fallback="—"):
                        """Return string value; fallback if None/NaN/empty/nan."""
                        try:
                            if val is None or (isinstance(val, float) and val != val):
                                return fallback
                            if pd.isna(val):
                                return fallback
                        except (TypeError, ValueError):
                            pass
                        s = str(val).strip()
                        return s if s and s.lower() not in ("nan", "none", "") else fallback

                    # ── Build result table ──
                    rows_out = []
                    for _, row in _ms.iterrows():
                        sid = row["session_id"]
                        _sess_tags = _ft[_ft["session_id"] == sid]["tag"].tolist()

                        # Setup summary — collect all non-null setup fields
                        setup_parts = []
                        for _scol, _slabel in [
                            ("fork_type","Fork"), ("f_spring","F-Spring"),
                            ("f_comp","F-Comp"), ("f_reb","F-Reb"),
                            ("shock_type","Shock"), ("r_spring","R-Spring"),
                            ("r_comp","R-Comp"), ("r_reb","R-Reb"),
                            ("swing_arm","SwingArm"), ("ride_height","RideH"),
                            ("f_tyre","F-Tyre"), ("r_tyre","R-Tyre"),
                        ]:
                            v = _sv(row.get(_scol))
                            if v != "—":
                                setup_parts.append(f"{_slabel}: {v}")

                        # Best lap
                        best_lap_s = best_laps_map.get(sid)
                        if best_lap_s and pd.notna(best_lap_s):
                            _m = int(best_lap_s // 60)
                            _s = best_lap_s - _m * 60
                            best_lap_str = f"{_m}'{_s:06.3f}"
                        else:
                            best_lap_str = _sv(row.get("best_lap"))

                        next_act = _sv(row.get("next_action"))
                        circuit  = _sv(row.get("circuit"))

                        rows_out.append({
                            "Session":               sid,
                            "Date":                  _sv(row.get("session_date",""))[:10],
                            "Circuit":               circuit,
                            "Rider":                 _sv(row.get("rider")),
                            "Problem Tags":          ", ".join(_sess_tags),
                            "Setup":                 " | ".join(setup_parts) if setup_parts else "—",
                            "Best Lap":              best_lap_str,
                            "Next Action / Solution": next_act,
                        })

                    df_ps_out = pd.DataFrame(rows_out)

                    # ── Display each session as an expander card ──
                    for _, card in df_ps_out.iterrows():
                        next_act_val = str(card["Next Action / Solution"])
                        has_solution = next_act_val not in ("—", "", "None", "nan")
                        icon = "✅" if has_solution else "📋"
                        label = (f"{icon} **{card['Session']}** — "
                                 f"{card['Rider']} | {card['Circuit']} | {card['Best Lap']}")
                        with st.expander(label, expanded=has_solution):
                            cc1, cc2 = st.columns([1, 1])
                            with cc1:
                                st.markdown("**🔴 Problem Tags**")
                                for tg in card["Problem Tags"].split(", "):
                                    st.markdown(f"- {tag_labels.get(tg.strip(), tg.strip())}")
                                st.markdown("**⚙️ Setup Used**")
                                if card["Setup"] != "—":
                                    for sp in card["Setup"].split(" | "):
                                        st.markdown(f"- {sp}")
                                else:
                                    st.caption("No setup data in DB for this session")
                                st.markdown(f"**⏱ Best Lap:** `{card['Best Lap']}`")
                            with cc2:
                                _sess_row = _ms[_ms["session_id"] == card["Session"]].iloc[0]
                                st.markdown("**📋 Engineer Notes (by Phase)**")
                                any_note = False
                                for ph_col, ph_label in [
                                    ("ph1_braking","PH1 Braking"), ("ph2_entry","PH2 Entry"),
                                    ("ph3_mid","PH3 Mid-Corner"), ("ph4_exit","PH4 Exit"),
                                    ("ph5_speed","PH5 Speed"),
                                ]:
                                    v = _sv(_sess_row.get(ph_col))
                                    if v != "—":
                                        st.markdown(f"**{ph_label}:** {v}")
                                        any_note = True
                                if not any_note:
                                    st.caption("No phase notes recorded")
                                if has_solution:
                                    st.markdown("**💡 Solution / Next Action**")
                                    st.info(next_act_val)

                    # ── Summary: tag frequency ──
                    st.divider()
                    st.markdown("**Tag Occurrence Summary**")
                    _tag_freq = _ft[_ft["session_id"].isin(_ms["session_id"])].groupby(["tag","phase"]).size().reset_index(name="count")
                    if not _tag_freq.empty:
                        fig_tf = px.bar(
                            _tag_freq.sort_values("count", ascending=False),
                            x="tag", y="count", color="phase",
                            color_discrete_map=PHASE_COLORS,
                            labels={"tag": "Problem Tag", "count": "Sessions", "phase": "Phase"},
                            title="How often each selected problem occurred (by Phase)",
                            height=280,
                        )
                        fig_tf = chart_layout(fig_tf, height=280)
                        st.plotly_chart(fig_tf, use_container_width=True)

    # ═══════════════════════════════════════════════════
    # PAGE 14 — Comprehensive Performance Analysis
    # ═══════════════════════════════════════════════════
    elif _NAV == "🏆  Performance":
        st.markdown('<p class="section-title">🏆 Comprehensive Performance Analysis</p>', unsafe_allow_html=True)
        st.caption("Season-wide performance trends: lap times, race results, and setup correlations.")

        # ── ヘルパー ──────────────────────────────────────
        _ROUND_ORDER_P = ["ROUND11","ROUND12","TEST1","TEST2","TEST3",
                          "TEST4","TEST5","ROUND1","ROUND2","ROUND3"]
        def _rnd_sort(r):
            try:    return _ROUND_ORDER_P.index(r)
            except: return 99

        def _to_rid(x):
            """rider_num (int/float/str 全対応) → 'DA77'/'JA52'/None"""
            try:
                return {77: "DA77", 52: "JA52"}.get(int(float(str(x))))
            except (ValueError, TypeError):
                return None

        def _fmt_t(t):
            """秒 → M'SS.mmm 形式"""
            try:
                t = float(t)
                if t != t: return "—"   # NaN check
                m = int(t // 60); s = t - m * 60
                return f"{m}'{s:06.3f}"
            except:
                return "—"

        _P_LABEL = {
            "f_comp":"F-Comp","f_reb":"F-Reb","r_comp":"R-Comp","r_reb":"R-Reb",
            "r_spring":"R-Spring","swing_arm":"SwingArm","ride_height":"Ride Height",
            "f_preload":"F-Preload","r_preload":"R-Preload",
        }

        # ── laps を正規化（一度だけ） ─────────────────────
        def _normalize_laps(df):
            if df.empty:
                return df
            d = df.copy()
            for c in ["lap_time","rider_num","lap_no","is_valid"]:
                if c in d.columns:
                    d[c] = pd.to_numeric(d[c], errors="coerce")
            # is_valid: 0以外を有効 (1, True, 1.0 すべて対応)
            d = d[d["is_valid"].fillna(0) != 0].copy()
            d = d.dropna(subset=["lap_time"])
            d["rider_id"] = d["rider_num"].apply(_to_rid)
            return d

        _laps_all = _normalize_laps(laps)
        _laps_da77 = _laps_all[_laps_all["rider_id"] == "DA77"] if not _laps_all.empty else pd.DataFrame()
        _laps_ja52 = _laps_all[_laps_all["rider_id"] == "JA52"] if not _laps_all.empty else pd.DataFrame()

        # ── Tab layout ──
        perf_tab1, perf_tab2, perf_tab3 = st.tabs(["📈 Lap Time Evolution", "🏁 Race Results Trend", "🔧 Setup Correlation"])

        # ───────────────────────────────────────────────
        # TAB 1 — Lap Time Evolution
        # ───────────────────────────────────────────────
        with perf_tab1:
            if _laps_all.empty:
                n_total = len(laps)
                iv_vals = laps["is_valid"].unique().tolist() if not laps.empty else []
                st.warning(f"有効ラップデータなし。総ラップ数: {n_total}, is_valid値: {iv_vals}")
            else:
                _lv2 = _laps_all.copy()
                _avail_sess = sorted(_lv2["session_type"].dropna().unique().tolist())
                _default_sess = [s for s in ["FP","SP","RACE1","RACE2"] if s in _avail_sess] or _avail_sess[:4]

                sel_sess_types = st.multiselect(
                    "Session types to include",
                    options=_avail_sess,
                    default=_default_sess,
                    key="perf_sess_types",
                )
                if sel_sess_types:
                    _lv2 = _lv2[_lv2["session_type"].isin(sel_sess_types)]

                if _lv2.empty:
                    st.info("選択したセッションタイプにデータがありません。")
                else:
                    # Best lap per round × rider
                    _best = (_lv2.groupby(["round_id","rider_id"], as_index=False)["lap_time"]
                             .min().dropna(subset=["rider_id"]))
                    _best["round_sort"] = _best["round_id"].apply(_rnd_sort)
                    _best = _best.sort_values("round_sort").reset_index(drop=True)
                    _best["circuit"]      = _best["round_id"].map(ROUND_CIRCUIT_MAP).fillna(_best["round_id"])
                    _best["x_label"]      = _best["round_id"] + "<br>" + _best["circuit"]
                    _best["best_lap_str"] = _best["lap_time"].apply(_fmt_t)

                    # Y軸ティック: M'SS.mmm 形式でカスタム表示
                    _y_min = _best["lap_time"].min()
                    _y_max = _best["lap_time"].max()
                    _y_pad = max((_y_max - _y_min) * 0.15, 1.0)
                    # 5秒刻みのティック
                    import math as _math
                    _tick_start = _math.floor((_y_min - _y_pad) / 5) * 5
                    _tick_end   = _math.ceil((_y_max + _y_pad) / 5) * 5
                    _tick_vals  = list(range(_tick_start, _tick_end + 1, 5))
                    _tick_texts = [_fmt_t(v) for v in _tick_vals]

                    # ── ラップ推移折れ線グラフ ──
                    fig_evo = go.Figure()
                    for rider, color in [("DA77", DA77_COLOR), ("JA52", JA52_COLOR)]:
                        _rd = _best[_best["rider_id"] == rider]
                        if _rd.empty:
                            continue
                        fig_evo.add_trace(go.Scatter(
                            x=_rd["x_label"], y=_rd["lap_time"],
                            mode="lines+markers", name=rider,
                            line=dict(color=color, width=2.5),
                            marker=dict(size=10, symbol="circle"),
                            customdata=_rd[["circuit","best_lap_str"]].values,
                            hovertemplate=(
                                f"<b>{rider}</b><br>"
                                "%{customdata[0]}<br>"
                                "Best Lap: <b>%{customdata[1]}</b>"
                                "<extra></extra>"
                            ),
                        ))
                    fig_evo.update_layout(
                        yaxis=dict(
                            title="Best Lap Time",
                            autorange="reversed",
                            tickvals=_tick_vals,
                            ticktext=_tick_texts,
                            range=[_y_max + _y_pad, _y_min - _y_pad],
                        ),
                        xaxis=dict(title="Round", tickangle=-20),
                        legend=dict(orientation="h", y=1.12),
                        height=400,
                        margin=dict(t=50, b=60, l=80, r=20),
                    )
                    fig_evo = chart_layout(fig_evo, height=400, title="Best Lap per Round — Season Progress")
                    st.plotly_chart(fig_evo, use_container_width=True)

                    # ── ライダー間ギャップ棒グラフ ──
                    try:
                        _piv = _best.pivot(index="round_id", columns="rider_id", values="lap_time").reset_index()
                        if "DA77" in _piv.columns and "JA52" in _piv.columns:
                            _piv["Gap (s)"] = (_piv["DA77"] - _piv["JA52"]).round(3)
                            _piv["round_sort"] = _piv["round_id"].apply(_rnd_sort)
                            _piv = _piv.sort_values("round_sort")
                            st.markdown("**DA77 − JA52 Gap per Round**")
                            st.caption("マイナス = DA77が速い / プラス = JA52が速い")
                            _piv_plot = _piv.dropna(subset=["Gap (s)"])
                            if not _piv_plot.empty:
                                _piv_plot = _piv_plot.copy()
                                _piv_plot["color"] = _piv_plot["Gap (s)"].apply(
                                    lambda v: DA77_COLOR if v < 0 else JA52_COLOR)
                                fig_gap = go.Figure(go.Bar(
                                    x=_piv_plot["round_id"], y=_piv_plot["Gap (s)"],
                                    marker_color=_piv_plot["color"],
                                    hovertemplate="%{x}: %{y:.3f}s<extra></extra>",
                                ))
                                fig_gap.add_hline(y=0, line_dash="dash", line_color="#666")
                                fig_gap = chart_layout(fig_gap, height=240)
                                st.plotly_chart(fig_gap, use_container_width=True)
                    except Exception:
                        pass

                    # ── データテーブル ──
                    with st.expander("📋 Raw Data Table"):
                        _disp = _best[["round_id","circuit","rider_id","best_lap_str","lap_time"]].copy()
                        _disp.columns = ["Round","Circuit","Rider","Best Lap","Best Lap (s)"]
                        st.dataframe(_disp, use_container_width=True, hide_index=True)

        # ───────────────────────────────────────────────
        # TAB 2 — Race Results Trend
        # ───────────────────────────────────────────────
        with perf_tab2:
            if results.empty:
                st.info("No race results data available.")
            else:
                _rr = results[results["rider_id"].isin(["DA77","JA52"])].copy()
                _rr["position"] = pd.to_numeric(_rr["position"], errors="coerce")
                _rr["round_sort"] = _rr["round_no"].apply(_rnd_sort)
                _rr = _rr.sort_values(["round_sort","session_type"]).reset_index(drop=True)

                # ── レース結果のみ（RACE1/RACE2）──
                _rr_race = _rr[_rr["session_type"].isin(["RACE1","RACE2"])].copy()
                if not _rr_race.empty:
                    _rr_race["label"] = _rr_race["round_no"] + " " + _rr_race["session_type"]
                    fig_pos = go.Figure()
                    for rider, color in [("DA77", DA77_COLOR), ("JA52", JA52_COLOR)]:
                        _rd2 = _rr_race[_rr_race["rider_id"] == rider]
                        if _rd2.empty: continue
                        fig_pos.add_trace(go.Scatter(
                            x=_rd2["label"], y=_rd2["position"],
                            mode="lines+markers", name=rider,
                            line=dict(color=color, width=2), marker=dict(size=10),
                            text=_rd2["best_lap"].fillna("—"),
                            hovertemplate="<b>%{x}</b><br>Position: %{y}<br>Best Lap: %{text}<extra>" + rider + "</extra>",
                        ))
                    fig_pos.update_layout(
                        yaxis=dict(title="Finishing Position", autorange="reversed",
                                   tickmode="linear", tick0=1, dtick=1),
                        xaxis_title="Race", legend=dict(orientation="h", y=1.12),
                        height=360, margin=dict(t=50, b=80, l=60, r=20),
                    )
                    fig_pos = chart_layout(fig_pos, height=360, title="Race Finishing Position — Season")
                    st.plotly_chart(fig_pos, use_container_width=True)

                    st.markdown("**Race Summary Table**")
                    _rcols = [c for c in ["round_no","session_type","rider_id","position",
                                          "best_lap","gap_to_top","conditions"] if c in _rr_race.columns]
                    _rr_disp = _rr_race[_rcols].copy()
                    _rr_disp.columns = ["Round","Session","Rider","Position","Best Lap","Gap to Top","Conditions"][:len(_rcols)]
                    st.dataframe(_rr_disp.sort_values(["Round","Session","Position"]),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info("No RACE1/RACE2 results available.")

                # ── 全セッション散布図 ──
                st.divider()
                st.markdown("**All Sessions — Position Overview**")
                _avail_rr = sorted(_rr["session_type"].dropna().unique().tolist())
                _def_rr   = [s for s in ["FP","SP","RACE1","RACE2"] if s in _avail_rr] or _avail_rr[:4]
                sel_rr_types = st.multiselect("Session types", _avail_rr, default=_def_rr, key="rr_type_sel")
                _rr_filt = _rr[_rr["session_type"].isin(sel_rr_types)] if sel_rr_types else _rr
                if not _rr_filt.empty:
                    _rr_filt = _rr_filt.copy()
                    _rr_filt["label"] = _rr_filt["round_no"] + " " + _rr_filt["session_type"]
                    fig_all = px.scatter(
                        _rr_filt, x="label", y="position",
                        color="rider_id", symbol="session_type",
                        color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                        labels={"label":"Round + Session","position":"Position","rider_id":"Rider"},
                        height=300,
                    )
                    fig_all.update_yaxes(autorange="reversed")
                    fig_all = chart_layout(fig_all, height=300)
                    st.plotly_chart(fig_all, use_container_width=True)

        # ───────────────────────────────────────────────
        # TAB 3 — Setup Correlation
        # ───────────────────────────────────────────────
        with perf_tab3:
            if sessions.empty:
                st.info("No session setup data available.")
            else:
                _sc = sessions.copy()
                _num_cols = [c for c in ["f_comp","f_reb","r_comp","r_reb","r_spring",
                                          "swing_arm","ride_height","f_preload","r_preload"]
                             if c in _sc.columns]
                for c in _num_cols:
                    _sc[c] = pd.to_numeric(_sc[c], errors="coerce")

                # session_id → round_id マッピング（YYYYMMDD-ROUND_X-RIDER → ROUND_X）
                def _sid_to_rnd(sid):
                    try: return sid.split("-")[1]
                    except: return None
                def _sid_to_rider(sid):
                    try: return sid.split("-")[2]
                    except: return None

                # 各セッションのベストラップを _laps_all から取得
                if not _laps_all.empty:
                    _laps_for_sc = _laps_all.copy()
                    _rnum_to_rider = {"77": "DA77", "52": "JA52"}
                    _laps_for_sc["_rider_str"] = _laps_for_sc["rider_id"].fillna("")

                    _best_by_rnd = (_laps_for_sc
                                    .groupby(["round_id","rider_id"], as_index=False)["lap_time"]
                                    .min()
                                    .rename(columns={"lap_time":"_best_lap_s"}))

                    _sc["_rnd"]   = _sc["session_id"].apply(_sid_to_rnd)
                    _sc["_rider"] = _sc["session_id"].apply(_sid_to_rider)
                    _sc = _sc.merge(_best_by_rnd,
                                    left_on=["_rnd","_rider"],
                                    right_on=["round_id","rider_id"],
                                    how="left")
                else:
                    _sc["_best_lap_s"] = float("nan")

                _sc["_best_lap_s"] = pd.to_numeric(_sc["_best_lap_s"], errors="coerce")
                _sc_with_lap = _sc.dropna(subset=["_best_lap_s"]).copy()

                # ── セットアップテーブル（常時表示）──
                st.markdown("**Full Setup Data — All Sessions**")
                _disp_cols = [c for c in ["session_id","rider","circuit","session_type",
                                          "fork_type","f_spring","f_comp","f_reb",
                                          "shock_type","r_spring","r_comp","r_reb",
                                          "swing_arm","ride_height","f_tyre","r_tyre"]
                              if c in sessions.columns]
                st.dataframe(sessions[_disp_cols].reset_index(drop=True),
                             use_container_width=True, hide_index=True)

                if _sc_with_lap.empty:
                    st.info("ラップタイムと紐づくセッションデータが不足しています（相関分析には3件以上必要）。")
                else:
                    st.divider()
                    st.markdown("**Setup Parameter Correlation with Best Lap Time**")
                    st.caption("マイナス相関 = 値が大きいほど速い / プラス相関 = 値が大きいほど遅い")

                    _corr_vals = {}
                    for c in _num_cols:
                        _sub_c = _sc_with_lap[[c,"_best_lap_s"]].dropna()
                        if len(_sub_c) >= 3:
                            _corr_vals[c] = float(_sub_c[c].corr(_sub_c["_best_lap_s"]))

                    if _corr_vals:
                        _corr_df = pd.DataFrame({
                            "Parameter": list(_corr_vals.keys()),
                            "Correlation": list(_corr_vals.values()),
                        }).sort_values("Correlation")
                        _corr_df["Label"] = _corr_df["Parameter"].map(_P_LABEL).fillna(_corr_df["Parameter"])
                        _corr_df["Color"] = _corr_df["Correlation"].apply(
                            lambda v: DA77_COLOR if v < 0 else JA52_COLOR)
                        fig_corr = go.Figure(go.Bar(
                            x=_corr_df["Correlation"], y=_corr_df["Label"],
                            orientation="h", marker_color=_corr_df["Color"].tolist(),
                            hovertemplate="%{y}: %{x:.3f}<extra></extra>",
                        ))
                        fig_corr.add_vline(x=0, line_dash="dash", line_color="#666", line_width=1)
                        fig_corr = chart_layout(fig_corr, height=320, title="Correlation: Setup vs Best Lap")
                        fig_corr.update_layout(xaxis=dict(title="Pearson r", range=[-1,1]))
                        st.plotly_chart(fig_corr, use_container_width=True)

                    # ── スキャッタープロット ──
                    st.divider()
                    st.markdown("**Scatter: Setup Parameter vs Best Lap**")
                    _avail_p = [c for c in _num_cols if _sc_with_lap[c].notna().sum() >= 2]
                    if _avail_p:
                        sel_param = st.selectbox(
                            "X-axis parameter", _avail_p,
                            format_func=lambda c: _P_LABEL.get(c, c),
                            key="sc_x_param",
                        )
                        _sdf = _sc_with_lap[[sel_param,"_best_lap_s","rider","session_id"]].dropna()
                        if not _sdf.empty:
                            _sdf = _sdf.copy()
                            _sdf["best_lap_str"] = _sdf["_best_lap_s"].apply(_fmt_t)
                            fig_sc = px.scatter(
                                _sdf, x=sel_param, y="_best_lap_s",
                                color="rider",
                                color_discrete_map={"DA77": DA77_COLOR, "JA52": JA52_COLOR},
                                hover_data={"session_id": True, "best_lap_str": True, "_best_lap_s": False},
                                labels={"_best_lap_s":"Best Lap (s)",
                                        sel_param: _P_LABEL.get(sel_param, sel_param)},
                                height=320,
                            )
                            fig_sc.update_yaxes(autorange="reversed")
                            fig_sc = chart_layout(fig_sc, height=320)
                            st.plotly_chart(fig_sc, use_container_width=True)

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
