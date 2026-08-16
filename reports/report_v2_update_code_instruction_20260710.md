# Report v2 Update: Code Instruction

Date: 2026-07-10
Priority: P1 report quality update after Race Weekend safety hardening
Scope: Workbench-generated Report v2 chart/readability improvements
Mode: implement report-only changes; no DB writes and no extraction changes

## User source note

Obsidian note:

```text
08_OBSIDIAN/TS24_Engineering_Knowledge/2026-07-10　Report Update.md
```

Tatsuki requests several upgrades to improve the quality of Reports generated from Workbench.

Main requests:

1. Existing graphs are readable, but real numeric values should be added above the relevant graph elements so actual values can be checked directly.
2. Add one page showing, for each phase, all laps from all runs selected for Report generation in one graph so trend behavior can be checked.
3. Outliers that clearly jump away from the trend must be visually obvious, using color or another intuitive marker.
4. Add one more page with a Lap Time distribution chart in addition to the existing lap-time progression chart.

## Required scope

This is a Report v2 presentation/readability update only.

Primary target:

```text
05_SCRIPTS/suspension_report.py
```

Only touch `ts24_workbench.py` if strictly necessary for parameter wiring. The existing `Create Report v2` button should continue to work without requiring new user input.

## Non-negotiable constraints

- Do not write canonical business tables.
- Do not change extraction logic.
- Do not change metric definitions.
- Do not change phase masks.
- Do not change provisional import / Race Weekend data ops.
- Do not run DB Master refresh.
- Do not run Supabase sync.
- Do not commit or push.
- Keep provisional report behavior:
  - `PROVISIONAL_` filename token;
  - cover provisional ribbon;
  - existing confirmation behavior from Workbench;
  - mixed final+provisional safety behavior.
- Keep report-only lap filter disclosure on page 2.

## Required implementation

### 1. Numeric value labels on summary charts

Add direct numeric labels to aggregation charts where values are summarized by run:

- phase summary F position;
- phase summary R position;
- phase summary damping speed F/R;
- any other existing summary chart where labels are useful and do not cause clutter.

Formatting:

- Position: one decimal or integer mm, depending on current precision.
- Suspension-speed index: compact integer or one decimal, with no excessive decimals.
- Lap time: keep existing `M:SS,CC` formatting.
- Labels must sit above bars or near line markers without overlapping the axes/title.
- If values are missing, show no label, not `0`.

Existing `chart_run_overview()` already labels best/median lap bars; keep it working.

### 2. Add all-laps phase trend page

Add a new Report page after the three phase summary pages and before existing lap-by-lap pages:

```text
All Laps Phase Trend & Outliers
```

Purpose:

- For each phase (`Braking`, `Apex`, `Exit`), show all laps from all selected runs in one visual context.
- The chart must make run-to-run trend behavior visible.
- It must include all selected runs and all valid laps after the existing report-only lap filter.
- Do not apply a silent new filter.

Suggested implementation:

- One page with 3 phase panels, or 3 compact rows.
- X axis: lap sequence or lap number.
- Color: selected run.
- Marker: each lap.
- Line: light trend/median line per run or phase.
- Include F/R position or the most relevant existing phase metric. If showing both F and R would overcrowd one page, use the clearest single metric family and state it in the page note.

Outlier detection:

- Use a report-only robust rule such as IQR or median absolute deviation per phase/metric.
- Mark outliers with a red/orange ring/star and a short label (`Run L# value`), capped to avoid clutter.
- Do not remove outliers from the data.
- Add a page note explaining the rule, e.g. `Outlier markers are report-only visual flags; no DB/extraction change`.

### 3. Add Lap Time distribution page

Add one page after the existing lap-time progression page:

```text
Lap Time Distribution
```

Purpose:

- Show lap-time spread for selected runs, not only lap-by-lap progression.
- Make consistency, spread, and outliers visible.

Suggested implementation:

- Box plot or violin/strip plot by run.
- Overlay individual lap points.
- Y axis formatted as `M:SS,CC`.
- Highlight lap-time outliers using the same report-only robust rule.
- Label or annotate the fastest lap and visible outliers.

This page must work for:

- final-only reports;
- provisional-only reports;
- mixed final + provisional reports.

### 4. Maintain PPTX and PDF parity

Both outputs must include the new pages:

- `build_report_v2()` PPTX
- `build_report_pdf()` PDF

Do not add a page to one output and forget the other.

### 5. Visual quality

- Keep English-only report text.
- Do not use Japanese text in generated Report slides/pages.
- Avoid label overlap; cap labels if necessary.
- Use phase colors consistently:
  - Braking = red
  - Apex = blue
  - Exit = green
- Keep legends outside or below plots when needed.
- Make the output usable on the team side without needing Workbench open.

## Validation checklist

1. `PYTHONPYCACHEPREFIX=/private/tmp/ts24_pycache python3 -m py_compile suspension_report.py ts24_workbench.py`
2. Generate a sample PPTX and PDF using current Round8 provisional data if possible.
3. Verify:
   - existing pages still generate;
   - new numeric labels appear;
   - `All Laps Phase Trend & Outliers` page appears;
   - outliers are visually marked and explained;
   - `Lap Time Distribution` page appears;
   - provisional filename/cover behavior remains intact;
   - page 2 lap-filter disclosure remains intact.
4. Confirm DB counts before/after are unchanged:
   - runs
   - laps
   - lap_suspension
   - race_results
   - provisional tables
   - registry/queue
5. Run one offscreen Workbench smoke if `ts24_workbench.py` changes.

## Deliverable

Create:

```text
05_SCRIPTS/reports/report_v2_update_20260710.md
```

The deliverable must include:

- implemented changes;
- sample output paths;
- before/after DB counts;
- screenshots or rendered-page checks if available;
- any remaining limitations, especially label caps/outlier label caps.
