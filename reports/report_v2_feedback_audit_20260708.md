# Report v2 Feedback — Phase A Read-only Audit

**Date:** 2026-07-08
**Author:** Claude Code (multi-agent read-only audit, 5 investigation dimensions + 3 adversarial verifiers)
**Scope:** READ-ONLY. No canonical DB write, no metric-definition change, no extraction-logic change, no DB Master / Supabase / origin push.
**Instruction:** `05_SCRIPTS/reports/report_v2_feedback_code_instruction_20260708.md`
**Feedback source:** `08_OBSIDIAN/TS24_Engineering_Knowledge/08_REPORT_NOTES/2026-07-08_Report_Feedback.md`
**Reference report:** `08_OBSIDIAN/.../suspension_report_v2_MISANO_JA52_ALL_PROVISIONAL_20260708_164053.pdf`

---

## 0. Executive summary

The P0 concern — that the report's `Sus_Speed` shows **Apex front-dive speed higher than Braking front-dive speed**, opposite to the engineering expectation — is **confirmed as a real, systematic pattern in the data**, but it is **not a computation bug**. It is a **phase-window artifact**: the numbers are computed correctly and self-consistently under the current metric definition, but the definition of the `FULL_BRAKING` window makes the "Braking F-Dive" value structurally *understate* the true braking dive, so comparing it against "Apex F-Dive" is engineering-misleading.

- **Classification:** `metric label / phase-window definition issue` (NOT sign, unit, extraction, or report-mapping bug).
- **Confidence:** HIGH. 3 independent adversarial verifiers (numerics, motorcycle-dynamics, data-artifact lenses) each tried to refute the phase-window explanation and **all 3 failed (0/3 refuted)**.
- **Two-tier fix path** (both require an explicit GO — see §7): a report-only relabel/annotation tier, and a stronger extraction-metric tier (new brake-onset dive metric).

The two decisive facts:
1. **Systematic & cross-circuit:** `apex_f_dive_spd_avg > brk_f_dive_spd_avg` in **1111/1146 laps = 97%** (median ratio ~2.1×), at *every* circuit (MOST 100%, ASSEN 96%, ARAGON 96%, PHILLIP ISLAND 98%, JEREZ 99%, MISANO 85%). Not a MISANO fluke.
2. **The average inverts but the peak does NOT:** `brk_f_dive_spd_peak` (mean 471.8) > `apex_f_dive_spd_peak` (mean 345.4); apex peak exceeds braking peak in only ~31% of laps. Braking retains the fastest *instantaneous* dive spikes — the effect lives entirely in the *averaging window*, not in the physics, the sign, or the noise.

---

## 1. Current report path, input data source, provisional/final

| Item | Value |
|---|---|
| Reference PDF | `suspension_report_v2_MISANO_JA52_ALL_PROVISIONAL_20260708_164053.pdf` (generated 2026-07-08 16:40) |
| Generator | `05_SCRIPTS/suspension_report.py` (`build_report_v2` / `build_report_pdf`), launched from Workbench `PhaseRunCompareWidget._on_create_report` |
| Primary data source | `lap_suspension` table in canonical `02_DATABASE/ts24_unified.db` (per-lap, self-contained; `laps.is_outlap` joined for best-lap logic) — `suspension_report.py` L139, §48a |
| Data stage of the PDF | **provisional** — the filename carries the `PROVISIONAL` token and the report was generated at 16:40, *before* the Round7 finalization apply at ~20:00 (§65, backup `_backup_round7_targeted_20260708_200025/`). |
| Data stage **now** | **final**. Round7/MISANO JA52 is now canonical (`runs` 13 / `laps` 77 / `lap_suspension` 77; provisional cleared to 0/0/0 — §65). |
| Does the finalization change this audit? | **No.** §65b proved the Round7 lap 2D values (incl. `f_dive_spd`/`r_dive_spd`) are **77/77 byte-identical** between the provisional and final extraction paths. All queries in this audit were run against the **final** data (`round='ROUND7' AND rider='JA52'`) and reproduce the inversion identically. Regenerating the report now would drop the `PROVISIONAL` ribbon but show the same Sus_Speed values. |

---

## 2. Exact current Report v2 metric mapping (position & Sus_Speed)

From `suspension_report.py` (verified against current source):

**Position** — `PHASE_POS` (L43-45), units mm, sensor position:
| Phase | F column | R column |
|---|---|---|
| Braking | `brk_susf_avg` | `brk_susr_avg` |
| Apex | `apex_susf_avg` | `apex_susr_avg` |
| Exit | `ce_susf_avg` | `ce_susr_avg` |

**Sus_Speed** — `PHASE_SPD` (L48-54), units = uncalibrated relative damping-speed index (mm/s), bars use the `*_avg` columns:
| Phase | F column (label) | R column (label) |
|---|---|---|
| Braking | `brk_f_dive_spd_avg` (**F-Dive**) | `brk_r_reb_spd_avg` (**R-Reb**) |
| Apex | `apex_f_dive_spd_avg` (**F-Dive**) | `apex_r_dive_spd_avg` (**R-Dive**) |
| Exit | `ce_f_reb_spd_avg` (**F-Reb**) | `ce_r_spd_avg` (**R\|v\|**, absolute magnitude) |

Phase → extraction mask (`build_master_db.py` L41-47, §18/§19/§43/§44):
`Braking = FULL_BRAKING`, `Apex = MID_CORNER`, `Exit = CORNER_EXIT`.

**Consistency checks (PASS):**
- Report `PHASE_SPD`/`PHASE_POS` are **column-for-column and label-for-label identical** to the Workbench `PhaseRunCompareWidget._PHASE_SPD`/`_PHASE_POS` (`ts24_workbench.py` L3093-3099 / L3080-3084). → **no report/Workbench mislabel.**
- `SPEED_NOTE` (L59): *"Susp speed = relative damping-speed index (mm/s, uncalibrated) — NOT vehicle speed (km/h)"* is present.

---

## 3. Sus_Speed anomaly audit (P0)

### 3.1 The anomaly is real, systematic, and cross-circuit

Read-only queries over `lap_suspension`:

- **MISANO JA52 (final, 77 laps):** `apex_f_dive_spd_avg > brk_f_dive_spd_avg` on **63/74 = 85%** of laps with both non-null; apex mean 119.4 vs braking mean 89.4 mm/s.
- **Whole DB (1146 laps, both columns non-null):** inversion on **1111/1146 = 97%**, median ratio **2.11×**; apex mean **122.5** vs braking mean **58.2** mm/s.
- **Per circuit:** MOST 100%, JEREZ 99%, PHILLIP ISLAND 98%, BALATON 97%, ARAGON 96%, ASSEN 96%, MISANO 85%. → **systemic, not MISANO-specific.**
- Cited example laps reproduce exactly: MISANO FP R1 L2 `brk=63.2` / `apex=189.6`; QP R1 L2 `brk=102.8` / `apex=177.5`.

### 3.2 Phase masks verified (`build_master_db.py` L41-47)

| Mask (phase) | Channel conditions |
|---|---|
| `FULL_BRAKING` (Braking) | `BRAKE_FRONT ∈ [9,20]` bar **AND** `SUSP_FRONT ∈ [90,130]` mm **AND** `SUSP_REAR ∈ [-0.5,2]` mm |
| `MID_CORNER` (Apex) | `BRAKE_FRONT ∈ [-0.3,3]`, `THROTTLE ∈ [-0.5,5]`, `DELTA_GAS > 0`, `SUSP_FRONT ∈ [50,100]`, `SUSP_REAR ∈ [8,40]` |
| `CORNER_EXIT` (Exit) | `BRAKE_FRONT ∈ [-0.5,0]`, `THROTTLE ∈ [50,100]`, `SUSP_FRONT ∈ [0,70]`, `SUSP_REAR ∈ [2,30]` |

### 3.3 Direction / sign / unit / resampling / avg-peak / sample-count (all verified correct)

- **Sign convention — self-consistent (PASS).** Larger `SUSP_FRONT` mm = more compressed. Phase-mean fork position: Braking **107.4 mm** (near the ~122 mm bottom) > Apex **75.1 mm** (mid-stroke) > Exit **19.8 mm** (extended). `dive = v>0` (position increasing = compressing); `reb = -v` for `v<0`. No sign divergence between phases.
- **Velocity / resampling (PASS).** Channels resampled to a per-lap grid of length `M = max(channel lengths)` via `np.interp` (L249-254); `dtg = lap_t/M` (L292); `vf = np.gradient(SUSP_FRONT)/dtg` (L293-295, L302). **Both** phases consume the **same** `vf` array and the **same** `v>0` rule (L306 vs L327-334) → a sign or unit error would be common-mode and could never produce a directional 2× split between two masks.
- **avg / peak semantics (PASS, but note asymmetry).** `avg = mean(directional samples)` if `n ≥ NMIN_Z=5`, else NULL; new-22 `peak = p95` if `n ≥ PEAK_NMIN=10`, else NULL (L327-334). **Reducer asymmetry:** the frozen legacy `brk_f_dive_spd_peak` uses `.max()` (L309), while every other phase's `*_peak` uses p95 (L333). → the report's *peak* bars are **max-vs-p95, apples-to-oranges** across phases (see §3.5).
- **Sample count — not a small-n artifact.** `fullbrk_count` mean ~2034 (2000–3100/lap); `apex_count` min 57 / mean 781; no lap has `apex_count<20`. Restricting to `apex_count≥300` leaves the inversion at 97.2%. The 3 MISANO NULL braking laps all have `fullbrk_count=0` (out/aggregate laps), not a compute error.

### 3.4 Root cause — the phase-window mechanism (byte-exact trace reconstruction)

A verifier re-ran the exact build pipeline (imported `build_master_db`, re-resampled raw `SUSP_FRONT`/`BRAKE_FRONT` from `DATA 2D/20260612-ROUND7-JA52/{FP,QP}-JA52-*.MES`, recomputed `vf`) and **reproduced the DB values byte-exactly** (FP R1 L2 → 63.2/189.6; QP R1 L2 → 102.8/177.5). This confirms there is no compute/sign/unit bug and localizes the effect to the mask geometry:

- The **`FULL_BRAKING` mask excludes the dive-in transient twice over**: it requires `SUSP_FRONT ≥ 90` (fork already deep) **and** `BRAKE_FRONT ≥ 9` bar (pressure already ramped). The genuinely fast front dive — the fork rushing down from ~30 → ~90 mm as brake pressure *ramps* — happens at `SUSP_FRONT < 90` and is structurally excluded.
- **Empirical split:** **82–95% of the total positive front-compression "speed mass" sits below `SUSF=90`** (outside `FULL_BRAKING`); only **2–5%** falls inside the window. Even within genuine hard braking (`BRAKE≥9`), the fork compresses at ~164–216 mm/s while `SUSF<90` but has slowed to ~65–107 mm/s once inside `[90,130]`. So `brk_f_dive_spd_avg` measures the **settled, near-bottom dwell**, not the dive.
- `MID_CORNER [50,100]` sits at compliant **mid-stroke**, where any `v>0` sample is structurally faster → higher conditional-mean `apex_f_dive_spd_avg`.

### 3.5 Why it is NOT the alternatives (adversarial verification, 0/3 refuted)

| Alternative hypothesis | Verdict | Decisive reason |
|---|---|---|
| Sign / unit bug | **Rejected** | Common-mode: both phases use identical `vf` + `v>0`; a flip/scale would hit both equally, not split them 2×. |
| Differentiation (np.gradient) noise | **Rejected** | Noise would inflate the **peak** too; but peak does **not** invert (braking keeps 471.8 vs apex 345.4). Also `FULL_BRAKING` is the denser window, so noise would bias braking *up* — against the observed inversion. |
| Genuinely physical (apex really dives faster) | **Rejected** | Braking still owns the fastest instantaneous dives (peaks don't invert); the deep-braking window just averages over the quasi-static dwell. Trail-braking = brake *bleeding off* = fork *extending*, not out-diving the initial dive. |
| MISANO-specific 2D quirk (seg NULL / new layout) | **Rejected** | Systemic at every circuit; MISANO is actually the *mildest* case (85% vs 96–100% elsewhere). |
| Report mislabel (wrong column mapping) | **Rejected** | `suspension_report.py` L48-54 maps the correct columns; Workbench mapping is identical. |

**Independent secondary finding (report-level, valid concern):** the report's cross-phase **"peak" bars are not comparable** because Braking peak = MAX (frozen legacy) while Apex/Exit peak = p95. This is a distinct report-only issue layered on top of the avg-window effect.

---

## 4. Öhlins definition lookup

**Files found (whole-tree search):**
- `04_REFERENCE/FKR-1xx-setting-library-version-1.0.pdf` (+ a copy in the vault `10_RAW_SOURCE_NOTES/PDF_SOURCES/`) — Öhlins **front-fork** cartridge shim-stack setting library (25 mm piston). Page 1 = Compression stacks C101–C106 + Rebound stacks R101–R106; page 2 = separate "Compression graph" and "Rebound graph", both **Force [N] (0–2000) vs Velocity [m/s] (0–1.0)**.
- **`04_REFERENCE/TTX36-GP-v3.6.xlsm` — an Öhlins rear-shock "Setting library" Excel (TTX36 GP R&T, v3.6, 2019).** This is effectively the "Öhlins Setting Bank" the feedback asked for. `InData` shaft-speed rows: 0.001–1.0 m/s; `OutData` = `Velocity [m/s]` vs `Comp_1..3` / `Reb_1..3` force [N]. Same force-vs-shaft-velocity framework as FKR.
- Not present locally: a file literally named "Ohlins Setting Bank"; the `NIX 30` workbook referenced by `TTX36-GP`'s `OutData`.

**Mapping / comparability conclusion:**
- **Neither** Öhlins document defines a numeric low-speed/high-speed threshold or even uses those words; the low/high split is only implicit in the velocity axis and sampling density (dense 0.001–0.05 m/s, coarse 0.1–1.0 m/s).
- **TS24's `Sus_Speed` is a fundamentally different quantity** and is **NOT directly comparable** to the Öhlins framework:
  1. Öhlins = the damper's **force-vs-velocity transfer function** (force produced at a given shaft velocity). TS24 = the **observed travel-rate** the suspension experiences (`np.gradient(position)/dtg`).
  2. TS24 is an **uncalibrated, within-dataset relative index** on an interp grid; Öhlins is calibrated absolute m/s. TS24's number cannot be placed on the Öhlins 0–1.0 m/s axis.
  3. TS24 differentiates the **position sensor** (rear has a rising-rate linkage motion ratio; front ≈1:1); Öhlins uses dyno **shaft** velocity.
  4. TS24 does no low-speed(bleed)/high-speed(shim) band split.
- **Only the direction convention corresponds:** TS24 `dive` (v>0, compression) ↔ Öhlins Compression stack; TS24 `reb` (v<0) ↔ Öhlins Rebound stack.
- **Recommendation:** do **not** relabel TS24 metrics with Öhlins low/high-speed C/R terminology — the semantics differ. If future work wants an Öhlins-comparable channel, it must be a calibrated shaft-velocity histogram (compression vs rebound, low/high band), which is a separate metric, not a rename. Keep the "uncalibrated relative index" caveat.

---

## 5. Lap filter proposal (report-only, deterministic — feedback item 2)

Slow/first/out laps stretch the chart scale. Proposed **report-generation-only, deterministic** filter (no DB write, no silent removal):

**Exclusion rule (applied in `suspension_report.py` at read time, per run):**
1. **Out lap / in lap:** `laps.is_outlap = 1` (already joined; §48a).
2. **First flying lap after pit / formation:** the first non-outlap lap of a run when its lap time > session-median + threshold (covers cold-tyre/warm-up laps).
3. **Lap-time outlier vs session median:** exclude laps with `lap_time_s > median(session valid laps) × 1.07` **or** `> median + 1.5·IQR` (whichever is chosen; document the exact rule). Physical guard already present: 60–300 s.

**Mandatory disclosure (feedback requirement):** Page 2 (Data Quality) must show a table listing:
- the exact filter rule and thresholds applied,
- the list of **excluded lap_ids** (run/lap_no/lap_time),
- the reason per lap (out-lap / in-lap / first-flying / time-outlier).

**Guardrails:** filtering is **report-only** (never writes DB, never mutates `is_outlap`); if no laps are excluded, the disclosure table states "no laps filtered". This preserves §12 (no silent 0-fill, no hidden filtering).

---

## 6. Visualization proposal (feedback item 1 — F/R position readability)

Problem: `F_Sus` position range dominates the chart, hiding `R_Sus` movement.

| Option | Pro | Risk |
|---|---|---|
| **Small multiples (recommended)** — separate F and R panels, each with its own auto-scaled Y | No shared-scale domination; no false cross-axis coupling; matches existing report style (§48) | Slightly more vertical space |
| Dual Y-axis (F left / R right) | Compact, keeps F/R on one plot | **Misleading risk:** two different scales on one frame invite false "F crossed R" reads; gridlines ambiguous |
| Normalized index (each series ÷ its own range) | Shape comparison in one panel | Hides absolute mm; can imply equal magnitude |

**Recommendation:** **small multiples (F panel + R panel, independent Y-scales), with a shared X (lap_no)** — the least-misleading option; explicitly label units (mm) on each. If a single-panel view is required, dual-Y is acceptable **only** with distinct colors, both axes labeled with units, and a note that the axes are independent. Avoid normalized index for position (absolute mm matters for setup). This is a **report-only** change.

---

## 7. Recommendation

**Classification:** the Sus_Speed inversion is **NOT** "no issue", NOT a sign/unit/extraction defect, and NOT a report-mapping mislabel. It is a **metric-label + phase-window-definition issue**: valid-as-computed but misleading-as-presented. The concrete fixes split into two approval tiers.

### Tier 1 — Report-only (recommended first; no DB, no extraction change)
Fixes the misleading *presentation* without touching data or definitions:
1. **Relabel the F-Dive bars** so the phase window is explicit, e.g. *"Braking F-Dive (deep-stroke / settled)"* vs *"Apex F-Dive (mid-stroke)"*, and add a note: *"Braking F-Dive avg measures the settled near-bottom dwell, not the initial dive-in rate."* Stop presenting `brk_f_dive_spd_avg` as "how fast the front dives under braking."
2. **Fix the peak-reducer asymmetry:** do not plot the Braking "peak" bar (MAX) against Apex/Exit "peak" bars (p95) as-is. Either recompute a p95 for display consistency at report time, or annotate the axis that Braking-peak = MAX (frozen legacy). *(avg comparison is unaffected — both are mean.)*
3. **F/R position readability** → small multiples (§6).
4. **Slow-lap filter** with page-2 disclosure (§5).
5. Keep the uncalibrated-relative-index / not-km/h note; do **not** adopt Öhlins low/high-speed terminology (§4).

**Required approval text for Tier 1:**
```text
Report v2 feedback report-only GO
```

### Tier 2 — Extraction / metric change (only if Tatsuki wants a true dive-in metric)
The current columns cannot express "peak braking dive-in rate" because `FULL_BRAKING` excludes the transient. To capture it, **add a new brake-onset dive metric** keyed to *rising* `SUSP_FRONT` below 90 mm while `BRAKE_FRONT` ramps (~0.3–9 bar, `dSUSP_FRONT/dt>0`) — as an **additive** new column, leaving the frozen `brk_f_dive_spd_*` legacy column and all existing values byte-unchanged (same non-destructive pattern as §44). This is a metric-definition change and requires the stronger gate.

**Required approval text for Tier 2:**
```text
Suspension speed extraction fix GO
```

### Not recommended
- Do **not** widen/move the `FULL_BRAKING` mask in place — it would silently change the frozen legacy column and every historical value. Add a new metric instead.
- Do **not** change any metric definition or write the DB during Phase A.

---

## 8. Guardrails honored / scope

- Read-only throughout: DB opened only as `file:...ts24_unified.db?mode=ro` (write-probe confirmed "attempt to write a readonly database"); no `.py`, no DB, no metric definition modified; only throwaway scripts under the session scratchpad.
- No canonical write, no provisional clear, no Round7 change, no DB Master refresh, no Supabase, no origin push, no silent report filtering.
- Raw 2D confirmed readable for the reconstructed MISANO outings (not iCloud-offloaded); reconstruction ran under a 120 s guard.

**Deliverable:** this report. **Next:** await Tatsuki's Tier-1 (`Report v2 feedback report-only GO`) and/or Tier-2 (`Suspension speed extraction fix GO`) decision before any implementation.
