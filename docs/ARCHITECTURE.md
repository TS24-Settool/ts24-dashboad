# TS24 Dashboard — Architecture Reference

**Last updated:** 2026-05-01 (rev 2 — dependency matrix + forbidden examples + PRODUCT-CANDIDATE tags)  
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
Each annotation in code uses the tag format: `# PRODUCT-CANDIDATE: <TAG>`

| Tag | Meaning |
|-----|---------|
| `A_NORMALIZE` | Data normalisation — low complexity, high reuse |
| `B_APEX` | APEX / suspension analysis — core racing domain logic |
| `C_SETUP_TARGET` | Lap comparison / setup target calculation |
| `D_DATA_LOADER` | Data loading (framework-agnostic) |
| `E_AI_CLIENT` | AI / external API wrappers |
| `F_DB_CLIENT` | Supabase / database client |
| `G_VISUALIZE` | Visualisation helpers |

### A_NORMALIZE — Data normalisation
*Low complexity, high reuse value. Ship as-is.*

| Function | File | In-code tag |
|----------|------|-------------|
| `normalize_circuit(c)` | `domain/lap_analysis.py` | `A_NORMALIZE` |
| `normalize_session(s)` | `domain/lap_analysis.py` | `A_NORMALIZE` |

### B_APEX — APEX / suspension analysis
*Core racing domain logic. Most differentiating for the product.*

| Function | File | In-code tag |
|----------|------|-------------|
| `build_lap_sus_map(df_ls)` | `domain/lap_analysis.py` | `B_APEX` |
| `build_lap_time_map(df_lt)` | `domain/lap_analysis.py` | `B_APEX` |
| `join_sus_and_laptimes(ls_map, lt_best)` | `domain/lap_analysis.py` | `B_APEX` |

### C_SETUP_TARGET — Lap comparison / setup target calculation
*The FAST/SLOW algorithm is the core value-add for commercial users.*

| Function | File | In-code tag |
|----------|------|-------------|
| `classify_fast_slow_tiers(df)` | `domain/lap_analysis.py` | `C_SETUP_TARGET` |

### D_DATA_LOADER — Data loading (framework-agnostic)
*Replace with DB adapter when moving to product backend.*

| Function | File | In-code tag |
|----------|------|-------------|
| `sql_to_df(conn, query)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `coerce_dynamics_numerics(df)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `coerce_lap_suspension(df)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `load_dynamics_from_excel(path)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `load_dynamics_from_json(dyn, lt)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `load_lap_suspension_from_excel(path)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `load_lap_suspension_from_sqlite(path)` | `services/data_loader.py` | `D_DATA_LOADER` |
| `load_lap_suspension_from_json(path)` | `services/data_loader.py` | `D_DATA_LOADER` |

### E_AI_CLIENT — AI / external APIs
*Replace model / endpoint in `claude_client.py` for product version.*

| Function | File | In-code tag |
|----------|------|-------------|
| `call_claude(api_key, user_msg, system_msg, max_tokens)` | `services/claude_client.py` | `E_AI_CLIENT` |
| `load_race_memory(primary, fallback)` | `services/memory_service.py` | `E_AI_CLIENT` |
| `save_race_memory(memory, *paths)` | `services/memory_service.py` | `E_AI_CLIENT` |
| `build_memory_context(memory, circuit, rider)` | `services/memory_service.py` | `E_AI_CLIENT` |

### F_DB_CLIENT — Supabase / database client
*Swap for direct PostgreSQL or other DB in product version.*

| Function | File | In-code tag |
|----------|------|-------------|
| `supa_request(method, url, key, data)` | `services/supabase_client.py` | `F_DB_CLIENT` |
| `fetch_table_paginated(table, key, url, order, where)` | `services/supabase_client.py` | `F_DB_CLIENT` |
| `supa_upsert(table, data, key, url)` | `services/supabase_client.py` | `F_DB_CLIENT` |
| `supa_delete_row(table, filter, key, url)` | `services/supabase_client.py` | `F_DB_CLIENT` |

### G_VISUALIZE — Visualisation / display
*Plotly helpers are framework-agnostic; embed directly in product.*

| Function / Constant | File | In-code tag |
|---------------------|------|-------------|
| `apply_chart_layout(fig, height, title)` | `components/charts.py` | `G_VISUALIZE` |
| `DA77_COLOR`, `JA52_COLOR` | `components/charts.py` | `G_VISUALIZE` |
| `PHASE_COLORS`, `PHASE_LABELS` | `components/charts.py` | `G_VISUALIZE` |
| `CHART_FONT` | `components/charts.py` | `G_VISUALIZE` |

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

## Dependency rules

### Allowed import directions

```
                 ┌─────────────────────────────────┐
                 │         dashboard.py             │
                 │  (Streamlit UI + routing only)   │
                 └────────┬────────┬────────┬───────┘
                          │        │        │
                    import│  import│  import│
                          ▼        ▼        ▼
                     domain/  services/  components/
                          │        │
                    import│  import│  (services → domain: allowed)
                    (min) │        │
                          ▼        ▼
                       domain/  domain/
```

| From \ To        | dashboard.py | domain/ | services/ | components/ | stdlib / 3rd-party |
|------------------|:---:|:---:|:---:|:---:|:---:|
| **dashboard.py** | —   | ✅  | ✅  | ✅  | ✅  |
| **domain/**      | ❌  | —   | ❌  | ❌  | ✅  |
| **services/**    | ❌  | ✅  | —   | ❌  | ✅  |
| **components/**  | ❌  | ✅ ¹| ❌  | —   | ✅  |

¹ `components → domain` is allowed for **shared constants only**
(e.g. colour maps keyed on domain-defined identifiers).
It must **not** call domain computation functions.

### Rules in plain language

1. **`domain/`** — pure logic only. Allowed imports: `stdlib`, `pandas`, `numpy`.  
   Must never import `streamlit`, `services`, `components`, or `dashboard`.

2. **`services/`** — I/O and external APIs. May import from `domain/` to apply
   normalisation before returning data (e.g. calling `normalize_circuit`).  
   Must never import `streamlit`, `components`, or `dashboard`.

3. **`components/`** — rendering helpers. May import domain constants
   (colour maps, label dicts) when those constants are semantically part of
   the domain model. Must never import `services` or `dashboard`.

4. **`dashboard.py`** — Streamlit entry point. The only layer that may import
   from all three layers and from `streamlit` itself.

### Forbidden examples

The following imports are **compile-time errors** in this project's convention.
If you see them in a PR, reject.

```python
# ❌ domain importing a service — breaks isolation
# domain/lap_analysis.py
from services.data_loader import load_lap_suspension_from_json   # FORBIDDEN

# ❌ domain importing Streamlit — breaks testability
# domain/lap_analysis.py
import streamlit as st                                            # FORBIDDEN

# ❌ services importing a chart helper — wrong direction
# services/data_loader.py
from components.charts import apply_chart_layout                  # FORBIDDEN

# ❌ components calling a data service — bypasses pages layer
# components/charts.py
from services.supabase_client import fetch_table_paginated        # FORBIDDEN

# ❌ any sub-module importing dashboard.py — circular and wrong
# services/memory_service.py
import dashboard                                                   # FORBIDDEN
```

### Allowed examples

```python
# ✅ services calling a domain normaliser before returning data
# services/data_loader.py
from domain.lap_analysis import normalize_circuit
df["circuit"] = df["circuit"].apply(normalize_circuit)

# ✅ components referencing a domain colour constant
# components/charts.py
from domain.lap_analysis import APEX_PHASE_COLORS   # hypothetical constant

# ✅ dashboard importing from all three layers
# dashboard.py
from domain.lap_analysis    import classify_fast_slow_tiers
from services.data_loader   import load_lap_suspension_from_json
from components.charts      import apply_chart_layout
```

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
