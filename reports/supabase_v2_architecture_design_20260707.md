# TS24 Supabase v2 Architecture Design

- **Date:** 2026-07-07
- **Status:** DESIGN / LOCAL ARTIFACTS ONLY
- **Source:** Tatsuki handwritten architecture photo `IMG_1089 2.png`
- **Scope:** Supabase / online DB architecture redesign for future data integrity
- **Production impact:** None. No Supabase SQL was executed.

---

## 1. Conclusion

Tatsuki案の中心思想は正しい。

現行の TS24 システムは、`02_DATABASE/ts24_unified.db` を正本とし、Supabase は cloud mirror、DB Master は派生Excel、Workbench は分析UIとして動いている。
将来の正確性を上げるには、Supabaseを「縦長一本の保存先」や「何でも入る巨大テーブル」にするのではなく、以下の構成にするべき。

```text
2D data / Report PDF
        ↓ save / scan / gate
DATA TS24 cloud intake
        ↓ staging / quality gate
Core original archive
        ↓ approved import
Local canonical DB = ts24_unified.db
        ↓ derived / read-only
TS24 Workbench = deep analysis UI
        ↓ upsert mirror after audit
Online DB = Supabase v2 normalized mirror
        ↓ derived output
TS24 DB Master / dashboard / team report
        ↓ scheduled backup
Backup DB
```

The key rule remains:

```text
Local SQLite / ts24_unified.db = canonical
Supabase = online mirror and query layer
DB Master / PowerPoint / dashboard = derived outputs
```

---

## 2. What is wrong with the current Supabase shape

Current online sync targets only four public mirror tables:

| Supabase table | Local source | Role |
|---|---|---|
| `race_results` | `race_results` | official PDF result mirror |
| `lap_times` | `pdf_lap_times` | legacy PDF lap detail mirror |
| `sessions_2d` | `runs` | 2D run/setup mirror |
| `lap_times_2d` | `laps` + `runs` | 2D lap mirror |

This works for current dashboard use, but it is not strong enough for future data management:

- It does not mirror `lap_suspension` and the new 3-phase suspension-speed columns.
- It does not model provenance strongly enough: source file, import batch, quality gate, provisional/final status.
- It mixes analysis output and source identity in a way that is hard to audit.
- It is easy to create `remote_extra` rows because Supabase is not treated as a strict projection of the canonical DB.
- It cannot represent race-weekend provisional data safely without risk of confusing it with final data.

---

## 3. Recommended architecture: normalized core + metric-long + compatibility views

Do not choose only one of “wide table” or “long table”.

Recommended shape:

1. **Normalized core tables**
   - `riders`
   - `circuits`
   - `events`
   - `sessions`
   - `runs`
   - `laps`
   - `run_setup`
   - `source_files`
   - `import_batches`
   - `quality_events`

2. **Official result tables**
   - `race_results`
   - `result_laps`

3. **Extensible metric table**
   - `lap_phase_metrics`
   - This is where braking/apex/exit suspension-speed metrics should live.
   - Columns: `lap_id`, `phase`, `subsystem`, `channel`, `side`, `direction`, `statistic`, `value_num`, `unit`, `metric_version`, `data_stage`.

4. **Compatibility views**
   - `v_sync_runs`
   - `v_lap_phase_metrics_dashboard`
   - Later: `v_lap_suspension_wide` if Workbench/dashboard needs the existing wide format.

This hybrid design is stronger than a single vertical table:

| Requirement | Best structure |
|---|---|
| Identify event/session/run/lap accurately | normalized core |
| Add future suspension metrics without schema churn | metric-long table |
| Fast Workbench/PowerPoint/dashboard output | views / materialized views |
| Prevent provisional/final confusion | `data_stage` on sessions/runs/laps/metrics |
| Trace every number back to the source | `source_files` + `import_batches` + `quality_events` |

---

## 4. Supabase v2 schema artifact

Created local DDL:

```text
04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707.sql
```

Important properties:

- Creates a separate schema: `ts24_v2`.
- Does not modify current `public.race_results`, `public.lap_times`, `public.sessions_2d`, `public.lap_times_2d`.
- Uses natural-key UNIQUE indexes with `NULLS NOT DISTINCT`.
- Keeps `data_stage` as `staging / provisional / final`.
- Adds source and quality provenance.
- Adds `lap_phase_metrics` for future suspension-speed and dynamics metrics.

This SQL should not be executed on production until explicit GO.

---

## 5. Migration strategy

### Phase A — Read-only architecture audit

Code should inspect:

- `02_DATABASE/ts24_unified.db`
- `05_SCRIPTS/sync_to_supabase.py`
- `05_SCRIPTS/supabase_audit.py`
- current Supabase report files
- `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707.sql`

Deliverable:

```text
05_SCRIPTS/reports/supabase_v2_migration_readiness_20260707.md
```

No DB writes. No Supabase writes.

### Phase B — Local projection builder

Build a read-only script that projects local SQLite rows into v2 payloads:

```text
05_SCRIPTS/supabase_v2_projection.py
```

It should emit JSON/CSV samples to `05_SCRIPTS/reports/supabase_v2_projection_samples/`.
It must not POST to Supabase.

### Phase C — Staging Supabase schema only

Only after explicit `Supabase v2 schema GO`:

- run `supabase_v2_core_schema_20260707.sql`
- confirm all tables/indexes/views exist
- do not backfill yet

### Phase D — Backfill dry-run then upsert

Only after explicit `Supabase v2 backfill GO`:

- upsert into `ts24_v2`
- compare old public mirror vs new v2 views
- keep old public tables active during transition

### Phase E — Dashboard / Workbench read switch

Only after validation:

- dashboard reads views, not raw v2 tables
- Workbench remains local-first
- PowerPoint report remains local-first unless a team-sharing online mode is explicitly designed

---

## 6. Race weekend operation

During race weekend:

```text
2D data / Report PDF
  → cloud intake folder
  → source_file_registry / import_queue
  → provisional staging
  → Workbench analysis
  → report output marked PROVISIONAL
  → final approval
  → canonical DB
  → Supabase v2 mirror
  → DB Master / backup
```

Supabase should not receive raw provisional data as final rows.
If provisional online sharing is needed, use `data_stage='provisional'` and views that clearly mark it.

---

## 7. Multi-agent operating model

| Agent | Responsibility |
|---|---|
| Architecture agent | Validate v2 schema against Tatsuki diagram and current DB |
| DB integrity agent | Ensure SQLite remains canonical and row counts are unchanged |
| Supabase agent | Build read-only audit/projection first; no POST until GO |
| Workbench agent | Confirm local-first analysis remains unchanged |
| Report agent | Ensure provisional/final labels remain visible |
| Supervisor | Stop all production DDL/sync/cleanup until Tatsuki explicit GO |

---

## 8. Decision

Adopt Tatsuki's hub architecture:

- **Local DB remains the center.**
- **Online DB mirrors clean, approved data.**
- **Core original archive keeps source truth.**
- **Workbench performs deep analysis locally.**
- **DB Master / reports are outputs, not sources.**
- **Backup DB is derived from canonical checkpoints.**

Supabase v2 should be a normalized, auditable, future-proof mirror, not a single vertical storage table.
