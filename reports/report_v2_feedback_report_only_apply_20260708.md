# Report v2 Feedback — Tier 1 Report-only Apply

**Date:** 2026-07-08 (validation carried into 07-09)
**GO:** Tatsuki approved **Tier 1 report-only only** (`Report v2 feedback report-only GO`; AskUserQuestion — Tier 2 NOT approved).
**Scope:** `05_SCRIPTS/suspension_report.py` ONLY. No canonical DB write, no metric/extraction change, no `build_master_db.py`, no `ts24_workbench.py`, no DB Master, no Supabase, no origin push.
**Instruction reconciled:** `reports/report_v2_feedback_report_only_code_instruction_20260708.md` (Codex) + audit `reports/report_v2_feedback_audit_20260708.md` (§66).
**Note on process:** the audit (§66) already contained the Tier-1 plan and Tatsuki gave the GO, so Phase B0 (plan) and B1 (implementation) were executed together under the received GO; this apply doc supersedes the separate `..._plan_20260708.md` deliverable.

## Changes (maps to Codex's 5 mandatory items)

| # | Codex requirement | Implementation |
|---|---|---|
| 1 | Rename/annotate Braking F-Dive as deep-stroke/settled | `PHASE_SPEED_REGION` map → phase-speed chart titles show the window (`Braking — Damping speed avg (deep-stroke / settled)`, Apex `(mid-stroke)`, Exit `(corner-exit (sparse))`). Compare-table headers → `Brk F-Dive [idx·deep]` / `Apex F-Dive [idx·mid]`. |
| 2 | Note: uncalibrated relative index, not comparable to Öhlins | `SPEED_NOTE` (uncalibrated, not km/h) kept; new `SPEED_WINDOW_NOTE` (mean-within-window, not dive-in rate, "do NOT read Apex>Braking as front dives faster at apex") + new `OHLINS_NOTE` ("NOT directly comparable to Ohlins low/high-speed C/R force-vs-shaft-velocity") on the Data-limits page (PPTX + PDF). |
| 3 | Disclose peak reducer asymmetry | `PEAK_NOTE`: peak columns not shown/compared across phases — `brk_f_dive_spd_peak` is legacy MAX while other `*_peak` are p95. (Confirmed: peak columns were never actually plotted; the old inaccurate "peak = p95" text is corrected.) |
| 4 | F/R position readability via small multiples | `chart_phase_summary` restructured 1×2 → **1×3** (F position / R position on independent Y-axes / F&R damping speed). Rear position (~0.7–1.6 mm under braking) is now readable instead of crushed by the ~100 mm front scale. Dual-Y not used (small multiples preferred, per instruction). |
| 5 | Report-only slow-lap filter + page-2 disclosure | New `apply_lap_filter` (deterministic, no DB write): excludes out/in laps (`_is_outlap==1`, when column present) and laps slower than session median × `SLOW_LAP_FACTOR` (1.07); degeneracy guard (never removes all laps). `lap_filter_note` renders the disclosure on the **Data Quality page (page 2)**: rule + excluded lap list + reason per lap, and an explicit "0 laps excluded" statement when none. `build_report_v2`/`build_report_pdf` gain `lap_filter=True` (default ON, backward-compatible); CLI `--no-lap-filter`. |

Robustness: enabled `word_wrap` on the affected PPTX text boxes so the longer notes/disclosures wrap.

## Validation (Codex Required Validation checklist)

1. `python3 -m py_compile suspension_report.py ts24_workbench.py` → **PASS** (both).
2. Sample generated (final MISANO JA52, all sessions): `reports/pptx/suspension_report_v2_MISANO_JA52_ALL_20260708_TIER1.pptx` / `.pdf`.
3. Filename carries `_ALL_`, **not `_PROVISIONAL_`** → confirms final data (post-§65) + provisional auto-detect correct.
4. **Page-2 filter disclosure present** (verified by reading the PDF): "Lap filter (report-only, no DB change): ON — excluded 12 lap(s): JA52 FP R1 L1 2:07,20 (out/in lap); … [+6 more]".
5. **F/R position readability improved** (verified): Braking/Apex phase-summary pages show F and R position on separate independent-Y panels; region label present on the speed panel; Data-limits page shows the misleading-comparison caveat + corrected peak note + Öhlins note.
6. **DB counts unchanged before/after**: runs 286 / laps 1279 / lap_suspension 1279 / race_results 866 (read-only report generation; identical before and after).
7. Recorded in this doc + Obsidian `log.md` / `CURRENT_STATE.md` / `03_AI_HANDOFF/AI_HANDOFF_LATEST.md` / `00_INBOX/FOR_CLAUDE_CODE.md` + `CLAUDE.md` §67.

Backward-compat smoke: Workbench-style df (no `_is_outlap` join) → `apply_lap_filter` degrades to slow-lap rule only (kept 65 / excluded 12); `build_report_v2` OK; filter-OFF path OK; offscreen `MainWindow` builds. Workbench (unchanged) picks up the new report + default filter automatically.

## Rollback / scope-out

- Rollback: `git checkout -- suspension_report.py` (revert) + delete the sample pptx/pdf. No DB/Excel/Workbench change to undo.
- **Not done (Tier 2, awaiting stronger GO `Suspension speed extraction fix GO`)**: brake-onset dive-in metric column, any `build_master_db.py` / canonical DB / phase-mask change.
- Forbidden items (all honored): canonical DB write, metric/phase-mask change, DB Master refresh, Supabase, origin push, silent filtering without page-2 disclosure.

**Changed:** `suspension_report.py`. **New:** sample pptx/pdf, this apply doc, `CLAUDE.md` §67.
