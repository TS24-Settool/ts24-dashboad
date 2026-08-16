# Workbench APEX / Damping Run Filter — Code Instruction

Date: 2026-07-11
Priority: P1 — Workbench analysis usability
Approval: Tatsuki's 2026-07-11 request for run selection/search in both pages is approval for this **read-only UI-only** change.

## User need

In `🦾 Suspension/Posture`, both `📊 APEX分析（基本）` and `⚙️ Damping / Phase` currently show all laps after the global Circuit filter. Add a compact Run Search / Selection panel so an engineer can choose exactly which runs feed the plots and numeric tables.

## Required UX

1. Add the same clearly labelled `🔎 Run Filter` surface to both pages. It may be one shared control surface in `PostureAnalysisTab` if it is visibly available while either of those two tabs is active.
2. Filter hierarchy: Circuit (existing global control) -> Rider -> Session -> Data stage (`All`, `Final`, `Provisional`) -> searchable Run list.
3. Run list must support text search, multi-selection by checkbox, `Select all`, and `Clear`.
4. Every selected-run label must be unambiguous: rider, round, session, run number/ID, and `⏳ (prov)` for provisional data. Include lap count or best lap only when it is already available from the in-memory DataFrame.
5. Graphs and numeric tables on both pages must use exactly the selected run IDs. Empty selection must show an explicit empty-state message; it must not silently fall back to all runs.
6. Defaults must preserve present behaviour: after the existing Circuit choice, all eligible runs are selected. Retain a valid selection across redraw/reload where possible.
7. `🔧 3フェーズ Run比較` keeps its own existing independent controls and selection. Do not couple or regress it.

## Implementation guidance

- Reuse the existing `PhaseRunCompareWidget` filter/list pattern (`ts24_workbench.py` around its `Run 選択（複数可）` UI) rather than duplicating selection semantics.
- Keep filtering in-memory on `PostureAnalysisTab._df`; use `data_stage` when available. No new SQL queries, tables, columns, or writes.
- Apply selection after current physical/lap-time validity filters. Never convert NULL to zero or alter metric/phase definitions.
- Make the control compact and collapsible or splitter-based so the analysis panels remain useful on a laptop screen.
- Preserve provisional provenance visually; final and provisional may be filtered independently but must never be silently merged as indistinguishable selected runs.

## Verification

1. `py_compile ts24_workbench.py`.
2. Offscreen Workbench smoke: 7 top-level tabs, 3 Suspension/Posture inner tabs, no exceptions.
3. Fixture/real read-only DataFrame checks:
   - circuit/rider/session/data-stage filtering;
   - one run, several runs, all runs, and empty selection;
   - final/provisional label and selection behavior;
   - both APEX and Damping graphs plus Damping numeric table reflect the exact same selected IDs;
   - 3-phase compare selection remains independent.
4. Assert canonical/provisional/registry/queue table counts before == after.
5. Tatsuki GUI check: select a single run, then multiple runs, then a provisional Round8 run; confirm graphs and table change accordingly.

## Forbidden

- Any changes to `extraction_scan.py`, `session_extract_staging.py`, import queue, staging/finalization, report generation, metric/phase extraction, DB schema, DB Master, Supabase, commit/push.
- Any database writes, including testing writes.
- Any weakening of the active ROUND8 fail-closed intake controls.

## Deliverables

- `05_SCRIPTS/reports/workbench_apex_damping_run_filter_apply_20260711.md`
- Update `05_SCRIPTS/CLAUDE.md`, Obsidian `log.md`, `CURRENT_STATE.md`, `AI_HANDOFF_LATEST.md`, and the Code inbox Result.
