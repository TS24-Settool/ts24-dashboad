"""
services/supabase_client.py — Supabase REST API client
=======================================================
Thin urllib wrapper around the Supabase PostgREST API.
No Streamlit dependency.

# PRODUCT-CANDIDATE: F_DB_CLIENT — This entire module.
"""

import json
import urllib.request
from typing import Optional

import pandas as pd


def supa_request(
    method: str,
    url: str,
    key: str,
    data: Optional[dict] = None,
):
    """Make a Supabase REST API request and return the parsed JSON response.

    Args:
        method: HTTP method ("GET", "POST", "PATCH", "DELETE").
        url:    Full Supabase REST URL.
        key:    API key (anon or service role).
        data:   Optional request body dict (JSON-serialised automatically).

    Returns:
        Parsed JSON (list or dict), or [] on any error.

    # PRODUCT-CANDIDATE: F_DB_CLIENT
    """
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


def fetch_table_paginated(
    table: str,
    svc_key: str,
    supa_url: str,
    order: str = "",
    where: str = "",
) -> pd.DataFrame:
    """Fetch all rows from a Supabase table using 1 000-row pagination.

    Args:
        table:    Table name in Supabase.
        svc_key:  Service role API key.
        supa_url: Supabase project URL (https://xxx.supabase.co).
        order:    Optional PostgREST order parameter (e.g. "session_date").
        where:    Optional PostgREST filter (e.g. "rider_num=in.(52,77)").

    Returns:
        DataFrame of all rows, or empty DataFrame on failure.

    # PRODUCT-CANDIDATE: F_DB_CLIENT
    """
    CHUNK = 1000
    all_rows: list = []
    offset = 0
    base_q = "select=*"
    if where:
        base_q += f"&{where}"
    if order:
        base_q += f"&order={order}"

    headers = {
        "apikey":        svc_key,
        "Authorization": f"Bearer {svc_key}",
        "Prefer":        "count=none",
    }

    while True:
        url = f"{supa_url}/rest/v1/{table}?{base_q}&limit={CHUNK}&offset={offset}"
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
            break
        offset += CHUNK
        if offset > 50_000:  # safety cap
            break

    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()


def supa_upsert(
    table: str,
    data: dict,
    key: str,
    supa_url: str,
) -> bool:
    """Insert or update a single row (merge-duplicates on primary key).

    # PRODUCT-CANDIDATE: F_DB_CLIENT
    """
    url = f"{supa_url}/rest/v1/{table}"
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates,return=minimal",
    }
    body = json.dumps(data).encode()
    req  = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def supa_delete_row(
    table: str,
    filter_str: str,
    key: str,
    supa_url: str,
) -> bool:
    """Delete rows matching a PostgREST filter string (e.g. "username=eq.alice").

    # PRODUCT-CANDIDATE: F_DB_CLIENT
    """
    url = f"{supa_url}/rest/v1/{table}?{filter_str}"
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False
