# TS24 Dashboard — Architecture Reference

**Last updated:** 2026-05-01  
**Branch:** `claude/ai-capabilities-comparison-ACtNs`

---

## Directory layout

```
ts24-dashboad/
├── dashboard.py          ← Streamlit entry point (UI + routing only)
│
├── domain/               ← Pure analysis logic — NO Streamlit dependency
│   └── lap_analysis.py   ← Normalization, tier classification, map builders
│
├── services/             ← External I/O — NO Streamlit dependency
│   ├── claude_client.py  ← Anthropic API wrapper
│   ├── data_loader.py    ← SQLite / Excel / JSON loaders
│   ├── memory_service.py ← race_memory.json read/write + context builder
│   └── supabase_client.py← Supabase REST API (pagination, CRUD)
│
├── components/           ← Rendering helpers — NO Streamlit dependency
│   └── charts.py         ← Plotly theme, color constants
│
├── tests/
│   └── test_lap_analysis.py ← unittest + regression fixtures
│
└── docs/
    └── ARCHITECTURE.md   ← this file
```

---

## Backward-compatible aliases in `dashboard.py`

All original function / variable names still work inside `dashboard.py`.
They are provided by `import … as …` at the top of the file.
**Do not remove these aliases until all call-sites inside dashboard.py
have been migrated to the new names.**

| Alias (old name in dashboard.py)   | New canonical name              | Defined in                    |
|------------------------------------|----------------------------------|-------------------------------|
| `_dyn_norm_circuit`                | `normalize_circuit`              | `domain.lap_analysis`         |
| `_dyn_norm_session`                | `normalize_session`              | `domain.lap_analysis`         |
| `_sql_to_df`                       | `sql_to_df`                      | `services.data_loader`        |
| `_coerce_dyn_numerics`             | `coerce_dynamics_numerics`       | `services.data_loader`        |
| `call_claude`                      | `call_claude`                    | `services.claude_client`      |
| `build_memory_context`             | `build_memory_context`           | `services.memory_service`     |
| `_supa_req_base`                   | `supa_request`                   | `services.supabase_client`    |
| `fetch_table_paginated`            | `fetch_table_paginated`          | `services.supabase_client`    |
| `_supa_upsert_base`                | `supa_upsert`                    | `services.supabase_client`    |
| `_supa_delete_row_base`            | `supa_delete_row`                | `services.supabase_client`    |
| `chart_layout`                     | `apply_chart_layout`             | `components.charts`           |
| `DA77_COLOR`                       | `DA77_COLOR`                     | `components.charts`           |
| `JA52_COLOR`                       | `JA52_COLOR`                     | `components.charts`           |
| `PHASE_COLORS`                     | `PHASE_COLORS`                   | `components.charts`           |
| `PHASE_LABELS`                     | `PHASE_LABELS`                   | `components.charts`           |
| `CHART_FONT`                       | `CHART_FONT`                     | `components.charts`           |

> **Note:** `_ms_load_race_memory` and `_ms_save_race_memory` are used only
> inside `load_race_memory()` / `save_race_memory()` wrappers in dashboard.py,
> which supply the path constants (`MEMORY_FILE`, `_TMP_MEMORY`).

---

## PRODUCT-CANDIDATE catalogue

29 annotations across 6 files.  
Organised by functional category for commercial product planning.

### Category A — Data normalisation
*Low complexity, high reuse value. Ship as-is.*

| Function | File | Notes |
|----------|------|-------|
| `normalize_circuit(c)` | `domain/lap_analysis.py` | Maps variant spellings → canonical circuit name |
| `normalize_session(s)` | `domain/lap_analysis.py` | Maps FP1/L1/… → canonical session codes |

### Category B — APEX / suspension analysis
*Core racing domain logic. Most differentiating for the product.*

| Function | File | Notes |
|----------|------|-------|
| `build_lap_sus_map(df_ls)` | `domain/lap_analysis.py` | (rider, circuit, date, run) → THR_ON/BRK averages |
| `build_lap_time_map(df_lt)` | `domain/lap_analysis.py` | (rider, circuit, date, run) → best valid lap time |
| `join_sus_and_laptimes(ls_map, lt_best)` | `domain/lap_analysis.py` | Joins suspension map with lap-time map |

### Category C — Lap comparison / setup target calculation
*The FAST/SLOW algorithm is the core value-add for commercial users.*

| Function | File | Notes |
|----------|------|-------|
| `classify_fast_slow_tiers(df)` | `domain/lap_analysis.py` | FAST/MED/SLOW per rider×circuit, n-independent |

### Category D — Data loading (framework-agnostic)
*Replace with DB adapter when moving to product backend.*

| Function | File | Notes |
|----------|------|-------|
| `sql_to_df(conn, query)` | `services/data_loader.py` | SQLite → DataFrame |
| `coerce_dynamics_numerics(df)` | `services/data_loader.py` | Type-safe numeric cast for DYNAMICS sheet |
| `coerce_lap_suspension(df)` | `services/data_loader.py` | Upper-case cols + cast for LAP_SUSPENSION |
| `load_dynamics_from_excel(path)` | `services/data_loader.py` | Master Excel → (df_dyn, df_lt) |
| `load_dynamics_from_json(dyn, lt)` | `services/data_loader.py` | JSON fallback → (df_dyn, df_lt) |
| `load_lap_suspension_from_excel(path)` | `services/data_loader.py` | Excel LAP_SUSPENSION sheet |
| `load_lap_suspension_from_sqlite(path)` | `services/data_loader.py` | SQLite lap_suspension table |
| `load_lap_suspension_from_json(path)` | `services/data_loader.py` | JSON fallback |

### Category E — AI / external APIs
*Replace model / endpoint in `claude_client.py` for product version.*

| Function | File | Notes |
|----------|------|-------|
| `call_claude(api_key, user_msg, system_msg, max_tokens)` | `services/claude_client.py` | Anthropic API; change `CLAUDE_API_MODEL` for prod |
| `load_race_memory(primary, fallback)` | `services/memory_service.py` | JSON-based persistent knowledge store |
| `save_race_memory(memory, *paths)` | `services/memory_service.py` | Multi-path write with silent failure |
| `build_memory_context(memory, circuit, rider)` | `services/memory_service.py` | Injects past insights into system prompt |

### Category F — Supabase / database client
*Swap for direct PostgreSQL or other DB in product version.*

| Function | File | Notes |
|----------|------|-------|
| `supa_request(method, url, key, data)` | `services/supabase_client.py` | Low-level REST call |
| `fetch_table_paginated(table, key, url, order, where)` | `services/supabase_client.py` | Handles >1000-row tables |
| `supa_upsert(table, data, key, url)` | `services/supabase_client.py` | INSERT OR UPDATE |
| `supa_delete_row(table, filter, key, url)` | `services/supabase_client.py` | DELETE with filter |

### Category G — Visualisation / display
*Plotly helpers are framework-agnostic; embed directly in product.*

| Function / Constant | File | Notes |
|---------------------|------|-------|
| `apply_chart_layout(fig, height, title)` | `components/charts.py` | Standard Power BI theme |
| `DA77_COLOR`, `JA52_COLOR` | `components/charts.py` | Brand colours (change for product theming) |
| `PHASE_COLORS`, `PHASE_LABELS` | `components/charts.py` | Corner-phase legend |
| `CHART_FONT` | `components/charts.py` | Typography spec |

---

## Next-phase extraction candidates

Ranked by effort / value. The pages below contain non-trivial data
transformation logic that could move to `domain/` or `services/` in
Phase 2, leaving only `st.*` calls in `dashboard.py`.

| Priority | Page | Lines | Signals | Suggested target |
|----------|------|-------|---------|-----------------|
| 🔴 High | **📊 Lap Sus Stats** | 321 | groupby, correlation matrix | `domain/lap_stats.py` — `compute_run_averages()`, `compute_lap_correlation()` |
| 🔴 High | **🏆 Performance** | 349 | groupby, merge, scatter | `domain/performance.py` — `compute_rider_performance()` |
| 🔴 High | **⏱ Race Pace** | 318 | groupby | `domain/race_pace.py` — `compute_stint_pace()`, `compute_lap_delta()` |
| 🟡 Med  | **📐 Lap Analysis** | 378 | groupby, 3-metric calc | `domain/lap_analysis.py` (extend) — `compute_3metric_delta()` |
| 🟡 Med  | **🔍 Problem→Solution** | 206 | groupby, frequency | `domain/tag_analysis.py` — `compute_tag_frequency()` |
| 🟡 Med  | **📊 Problem Analysis** | 111 | groupby, merge | `domain/tag_analysis.py` — `compute_tag_by_rider()` |
| 🟢 Low  | **📤 Submit Data** | 248 | mostly UI | Minor — some form-validation logic |
| 🟢 Low  | **✅ Approvals** | 168 | mostly UI | Minor |

### What to NOT extract next

- `🏁 Race Results`, `📋 Session Detail`, `👤 Accounts` — mostly table display / CRUD UI, limited pure logic.
- `💬 Setup Chat`, `🤖 AI Advice` — tightly coupled to streaming state; separate only if adding async.

---

## Dependency rules (enforced by convention)

```
dashboard.py  →  domain/*
              →  services/*
              →  components/*

domain/*      →  (stdlib, pandas, numpy only)
services/*    →  (stdlib, pandas, requests/urllib only)
components/*  →  (stdlib, plotly only)
```

**None of `domain/`, `services/`, or `components/` may import from each other
or from `dashboard.py`.**  
This keeps them independently testable and deployable.

---

## Running tests

```bash
# From repo root (requires pandas, plotly installed):
python -m pytest tests/ -v

# Or with unittest:
python -m unittest discover tests -v
```

Current test coverage:

| Module | Tests | Type |
|--------|-------|------|
| `domain/lap_analysis.py` | 28 | Unit + regression |
| `services/*` | — | Planned Phase 2 |
| `components/*` | — | Planned Phase 2 |
