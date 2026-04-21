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
_TMP_CONFIG = Path("/tmp/ts24_dashboard_config.json")

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
    """Return {username: user_data} dict — Supabase first, JSON fallback."""
    # 1) Try Supabase (persistent across restarts)
    if _supa_users_available():
        supa_users = _supa_get_users()
        if supa_users is not None:
            if not supa_users:
                # Table exists but empty — migrate local users to Supabase
                cfg = load_config()
                local_users = cfg.get("users", {})
                for uname, udata in local_users.items():
                    if isinstance(udata, dict):
                        _supa_upsert_user(
                            uname, udata.get("password", ""),
                            udata.get("role", "engineer"), udata.get("rider"))
                return local_users or {
                    "ts24": {"password": _hash("Tatsuki1344"),
                             "role": "admin", "rider": None}
                }
            # Deduplicate: lowercase keys, keep most-privileged role on collision
            deduped = {}
            for uname, udata in supa_users.items():
                key_lower = uname.lower()
                if key_lower in deduped:
                    # Keep admin > engineer > viewer
                    order = {"admin": 0, "engineer": 1, "viewer": 2}
                    existing_role = deduped[key_lower].get("role", "engineer")
                    new_role      = udata.get("role", "engineer")
                    if order.get(new_role, 9) < order.get(existing_role, 9):
                        deduped[key_lower] = udata
                else:
                    deduped[key_lower] = udata
            return deduped

    # 2) Fallback: JSON config (local / Streamlit Cloud /tmp)
    cfg = load_config()
    users = cfg.get("users", {})
    # Deduplicate JSON users too (case-insensitive)
    deduped = {}
    for uname, udata in users.items():
        key_lower = uname.lower()
        if key_lower not in deduped:
            deduped[key_lower] = udata
    if not deduped:
        default = {"ts24": {"password": _hash("Tatsuki1344"),
                            "role": "admin", "rider": None}}
        cfg["users"] = default
        save_config(cfg)
        return default
    return deduped

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
    if _supa_users_available():
        if _supa_upsert_user(uname, phash, role, rider):
            return
    # 2) JSON fallback
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

def _supa_to_df(table: str, svc_key: str, supa_url: str, order: str = "") -> pd.DataFrame:
    """Fetch a Supabase table and convert to DataFrame."""
    filters = f"select=*{('&order=' + order) if order else ''}"
    # Pagination (max 10000 rows)
    url = f"{supa_url}/rest/v1/{table}?{filters}&limit=10000"
    headers = {
        "apikey":        svc_key,
        "Authorization": f"Bearer {svc_key}",
        "Range":         "0-9999",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def load_data():
    cfg      = load_config()
    supa_url = cfg.get("supabase_url", "")
    svc_key  = cfg.get("supabase_service_key", "")

    # If Supabase is configured, fetch from cloud
    if supa_url and svc_key and svc_key != "PASTE_SERVICE_ROLE_KEY_HERE":
        try:
            sessions = _supa_to_df("sessions",       svc_key, supa_url, "session_date")
            tags     = _supa_to_df("session_tags",   svc_key, supa_url)
            results  = _supa_to_df("race_results",   svc_key, supa_url, "round_no,session_type,rider_id")
            sectors  = _supa_to_df("sector_results", svc_key, supa_url)
            laps     = _supa_to_df("lap_times",      svc_key, supa_url, "round_id,session_type,rider_num,lap_no")
            return sessions, tags, results, sectors, laps
        except Exception:
            pass  # Fallback to SQLite

    # Fallback: local SQLite
    return _load_sqlite()

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
    initial_sidebar_state="expanded"
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

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #DDE1E7 !important;
    }
    section[data-testid="stSidebar"] * { color: #111111 !important; }

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
</style>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────
sessions, tags, results, sectors, laps = load_data()

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
        "📋  Session Detail",
        "📉  Trend Analysis",
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
            """97.901 → '1:37.901'"""
            if sec is None or pd.isna(sec):
                return "—"
            m = int(sec // 60)
            s = sec - m * 60
            return f"{m}:{s:06.3f}"

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

                if rnum in compare_nums:
                    # Compare rider: highlight in color
                    col = compare_colors[rnum]
                    fig_pace.add_trace(go.Scatter(
                        x=df_r["lap_no"], y=df_r["lap_time"],
                        mode="lines+markers",
                        name=lbl,
                        line=dict(color=col, width=2),
                        marker=dict(size=6, color=col),
                        hovertemplate=f"<b>{lbl}</b><br>Lap %{{x}}: %{{y:.3f}}s<extra></extra>",
                    ))
                else:
                    # Regular field rider: gray background
                    fig_pace.add_trace(go.Scatter(
                        x=df_r["lap_no"], y=df_r["lap_time"],
                        mode="lines+markers",
                        name=lbl,
                        line=dict(color="#CCCCCC", width=1),
                        marker=dict(size=4, color="#CCCCCC"),
                        hovertemplate=f"<b>{lbl}</b><br>Lap %{{x}}: %{{y:.3f}}s<extra></extra>",
                        legendgroup="field",
                        showlegend=False,
                    ))

            # Highlight DA77 in blue
            if has_da77:
                df_da = df_lp[df_lp["rider_num"] == 77].sort_values("lap_no")
                # Valid laps
                df_da_v = df_da[df_da["is_valid"] == 1]
                df_da_i = df_da[df_da["is_valid"] == 0]
                fig_pace.add_trace(go.Scatter(
                    x=df_da_v["lap_no"], y=df_da_v["lap_time"],
                    mode="lines+markers", name="DA77 D.Aegerter",
                    line=dict(color=DA77_COLOR, width=2.5),
                    marker=dict(size=7, color=DA77_COLOR),
                    hovertemplate="<b>DA77</b> Lap %{x}: %{y:.3f}s<extra></extra>",
                ))
                if not df_da_i.empty:
                    fig_pace.add_trace(go.Scatter(
                        x=df_da_i["lap_no"], y=df_da_i["lap_time"],
                        mode="markers", name="DA77 pit/cancel",
                        marker=dict(size=8, color=DA77_COLOR, symbol="x", opacity=0.5),
                        hovertemplate="<b>DA77 [%{customdata}]</b> Lap %{x}: %{y:.3f}s<extra></extra>",
                        customdata=df_da_i["flag"],
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
                    hovertemplate="<b>JA52</b> Lap %{x}: %{y:.3f}s<extra></extra>",
                ))
                if not df_ja_i.empty:
                    fig_pace.add_trace(go.Scatter(
                        x=df_ja_i["lap_no"], y=df_ja_i["lap_time"],
                        mode="markers", name="JA52 pit/cancel",
                        marker=dict(size=8, color=JA52_COLOR, symbol="x", opacity=0.5),
                        hovertemplate="<b>JA52 [%{customdata}]</b> Lap %{x}: %{y:.3f}s<extra></extra>",
                        customdata=df_ja_i["flag"],
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
            if has_da77 or has_ja52:
                st.markdown('<p class="section-title">Sector Time Evolution</p>', unsafe_allow_html=True)
                sc1, sc2 = st.columns(2, gap="medium")

                for col_idx, (rnum, rname, color) in enumerate([(77, "DA77", DA77_COLOR), (52, "JA52", JA52_COLOR)]):
                    col = sc1 if col_idx == 0 else sc2
                    df_r = df_lp[(df_lp["rider_num"] == rnum) & (df_lp["is_valid"] == 1)].sort_values("lap_no")
                    if df_r.empty:
                        col.info(f"{rname}: no data")
                        continue
                    fig_sec = go.Figure()
                    seg_colors = {"seg1": "#C0392B", "seg2": "#E67E22", "seg3": "#27AE60", "seg4": "#2980B9"}
                    seg_labels = {"seg1": "S1", "seg2": "S2", "seg3": "S3", "seg4": "S4"}
                    for seg, sc in seg_colors.items():
                        if df_r[seg].notna().any():
                            fig_sec.add_trace(go.Scatter(
                                x=df_r["lap_no"], y=df_r[seg],
                                mode="lines+markers", name=seg_labels[seg],
                                line=dict(color=sc, width=2),
                                marker=dict(size=5),
                                hovertemplate=f"{seg_labels[seg]} Lap %{{x}}: %{{y:.3f}}s<extra></extra>",
                            ))
                    chart_layout(fig_sec, height=240, title=f"{rname} — Sector Times per Lap")
                    fig_sec.update_layout(xaxis_title="Lap", yaxis_title="Sector Time (s)")
                    col.plotly_chart(fig_sec, use_container_width=True, config={"displayModeBar": False})

            # ── CHART 3: Lap Gap (vs. session best) ──────────────────
            st.markdown('<p class="section-title">Gap to Session Best Lap (per lap)</p>', unsafe_allow_html=True)

            gap_traces = []
            for rnum, rname, color in [(77, "DA77", DA77_COLOR), (52, "JA52", JA52_COLOR)]:
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
                df_valid = (df_round[df_round["is_valid"] == 1]
                            if "is_valid" in df_round.columns else df_round)
                sessions_avail = [s for s in SESSION_ORDER
                                  if s in df_valid["session_type"].unique()]

                # ── Build metrics table ──────────────────────
                def fmt_lap(s):
                    if s is None or (isinstance(s, float) and pd.isna(s)):
                        return "—"
                    m = int(s) // 60
                    return f"{m}:{s % 60:06.3f}"

                rows = []
                for ses in sessions_avail:
                    df_ses = df_valid[df_valid["session_type"] == ses]
                    p1_time = df_ses["lap_time"].min() if not df_ses.empty else None

                    for rider in riders_to_show:
                        rnum = RIDER_NUM[rider]
                        df_r = df_ses[df_ses["rider_num"] == rnum]
                        if df_r.empty:
                            continue
                        times = df_r["lap_time"].dropna().values
                        if len(times) == 0:
                            continue
                        best      = float(times.min())
                        avg       = float(times.mean())
                        sigma     = float(times.std()) if len(times) > 1 else 0.0
                        p1_gap    = round(best - p1_time, 3) if p1_time else 0.0
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
                    st.warning("No valid lap data for the selected riders/round.")
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
                    styled = (df_m[disp_cols].style
                              .applymap(_colour_p1,    subset=["P1 Gap (s)"])
                              .applymap(_colour_sigma, subset=["Consistency σ"])
                              .applymap(_colour_avg,   subset=["Avg vs Best (s)"]))
                    st.dataframe(styled, use_container_width=True, hide_index=True)

                    st.caption("🟢 Green = strong  🟡 Yellow = acceptable  🔴 Red = needs attention  "
                               "| P1 Gap: gap to session fastest  "
                               "| Consistency σ: std dev of valid laps  "
                               "| Avg vs Best: avg lap vs personal best")

                    st.divider()

                    # ── Performance Evolution Chart ──────────
                    st.markdown("#### Performance Evolution across Event")

                    import plotly.graph_objects as go

                    fig_evo = go.Figure()

                    # Session P1 reference
                    p1_ref = {}
                    for ses in sessions_avail:
                        d = df_valid[df_valid["session_type"] == ses]["lap_time"]
                        if not d.empty:
                            p1_ref[ses] = d.min()
                    if p1_ref:
                        fig_evo.add_trace(go.Scatter(
                            x=list(p1_ref.keys()), y=list(p1_ref.values()),
                            name="Session P1 (all riders)",
                            line=dict(color="#2ECC71", width=2, dash="dot"),
                            mode="lines+markers",
                            marker=dict(size=7, symbol="diamond"),
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
                        ))

                    fig_evo.update_layout(
                        xaxis_title="Session",
                        yaxis_title="Lap Time (s)",
                        yaxis_autorange="reversed",   # lower = faster = top
                        legend=dict(orientation="h", y=1.12),
                        height=420,
                        margin=dict(l=50, r=20, t=40, b=40),
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

                    # ── Setup Direction Summary ──────────────
                    st.markdown("#### Setup Direction — Session-over-Session Change")

                    for rider in riders_to_show:
                        rd = df_m[df_m["Rider"] == rider].reset_index(drop=True)
                        if len(rd) < 2:
                            continue
                        st.markdown(f"**{rider}**")
                        dir_cols = st.columns(len(rd) - 1)
                        for i in range(len(rd) - 1):
                            prev = rd.iloc[i]
                            curr = rd.iloc[i + 1]
                            d_pace  = curr["Best (s)"]   - prev["Best (s)"]
                            d_sigma = curr["Consistency σ"] - prev["Consistency σ"]
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

    # ═══════════════════════════════════════════════════
    # PAGE 6 — Session Detail
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
