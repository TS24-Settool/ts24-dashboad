# ROUND8 Final Integration — Phase 1 Read-Only Closure Audit (Readiness Report)

Date: 2026-07-13
Agent: Track A audit agent (Fable 5), READ-ONLY session
Instruction: `05_SCRIPTS/reports/round8_final_integration_code_instruction_20260713.md`
Canonical DB: `02_DATABASE/ts24_unified.db` — opened exclusively with `mode=ro`. **No `--apply` was run. No source code was modified.**

Canonical DB sha256 BEFORE session: `2eedecbd04f822e835a917e9fc4256907996acee5b5194229d8b530834a5cc22`
Canonical DB sha256 AFTER session: see §10 (verified identical).

Ground truth re-verified this session (read-only): canonical runs 286 / laps 1279 / lap_suspension 1279 / race_results 866 / pdf_lap_times 7613 / pdf_lap_times_v2_staging 7710; canonical ROUND8 = 0 in all of runs/laps/lap_suspension/race_results/pdf_lap_times/v2_staging. Provisional = 15 runs / 137 laps / 137 lap_suspension (per-session breakdown matches supervisor ground truth exactly).

---

## 1. Source inventory (every ROUND8 file, hash + disposition)

All files are fully local (st_blocks > 0; **zero iCloud-dataless items**; no forced downloads needed). `.MES` folders use a stat manifest hash (sha256 over sorted `name|size` lines, first 16 hex) per the large-folder rule.

### 1a. Result PDFs — `07_RESULTS/ROUND8_DONINGTON_20260710/`

| File | Size | mtime | sha256 (16) | Disposition |
|---|---|---|---|---|
| 20260710-ROUND8-FP.pdf | 390,624 | 2026-07-11 17:30 | dc20f06b5aa6ff99 | valid — extracts clean |
| 20260710-ROUND8-QP.pdf | 524,731 | 2026-07-11 17:31 | ddd13d24a25c249c | valid — extracts clean |
| 20260710-ROUND8-WUP1.pdf | 342,491 | 2026-07-11 17:32 | 44b005a6d709cb33 | valid — extracts clean |
| 20260710-ROUND8-WUP2.pdf | 345,284 | 2026-07-13 00:12 | 414a92f5682fb0aa | valid — extracts clean |
| 20260710-ROUND8-RACE1.pdf | 713,508 | 2026-07-11 17:33 | 7fd8d627ec6943fb | valid — extracts clean |
| 20260710-ROUND8-RACE2.pdf | 768,766 | 2026-07-13 00:13 | ee1e61fc850d329f | valid — extracts clean (official-PDF-only path) |

Coverage gate: FP/QP/WUP1/WUP2/RACE1/RACE2 all present. PASS.

### 1b. Report / Original

| File | Size | mtime | sha256 (16) | Disposition |
|---|---|---|---|---|
| 01_REPORTS/JA52/20260710-ROUND8-JA52.xlsx | 60,264 | 2026-07-12 19:10 | bee2b3643bf42eb9 | valid — parse_report OK |
| 04_REFERENCE/Data_Base_TS24_ORIGINAL.xlsx | 51,238 | 2026-07-12 19:10 | 84164f5406777bb1 | valid — contains 9 new ROUND8 JA52 rows (+2 legacy 2025 DONINGTON rows, see §3c) |
| 01_REPORTS/DA77/ (ROUND8) | — | — | — | **MISSING — no DA77 Round8 report exists** (latest DA77 report = 20260515-ROUND5). DA77 = 2D_ONLY path: no comments, no setup fields, wf_* NULL. Consistent with prior rounds. |

### 1c. 2D event folder — `DATA 2D/20260710-ROUND8-JA52` (8 outings, nested layout)

| Outing (.MES dir) | files | bytes | manifest16 | mtime | Disposition |
|---|---|---|---|---|---|
| FP-JA52-01 | 198 | 68,122,673 | 1e0f4aad9883b620 | 07-10 13:49 | valid-finalizable (FP R1, 15 laps) |
| FP-JA52-02 | 201 | 33,329,212 | 5f53e70e3d9c8b85 | 07-10 13:49 | valid-finalizable (FP R2, 6 laps) |
| QP-JA52-01 | 201 | 27,068,458 | ccaf1f46a2c91df4 | 07-10 20:05 | valid-finalizable (QP R1, 5 laps) |
| QP-JA52-02 | 201 | 26,951,619 | 67a71620aab82c22 | 07-10 20:05 | valid-finalizable (QP R2, 5 laps) |
| QP-JA52-03 | 200 | 44,392,818 | 6c21bed0abbf5225 | 07-10 20:05 | valid-finalizable (QP R3, 8 laps) |
| WUP1-JA52-01 | 201 | 36,824,697 | 7892f7728c500838 | 07-11 11:04 | valid-finalizable (WUP1 R1, 7 laps) |
| WUP2-JA52-01 | 201 | 36,366,725 | 6f3c42a210caedeb | 07-12 12:13 | valid-finalizable (WUP2 R1, 7 laps) |
| R1-JA52-01 | 201 | 97,123,823 | 4155f6b75ad2b046 | 07-11 17:30 | valid-finalizable (RACE1 R1, 20 laps) |

No JA52 Race2 .MES — confirmed absent (declared missing source).

### 1d. 2D event folder — `DATA 2D/20260710-ROUND8-DA77` (13 outing dirs + loose event files)

| Outing (.MES dir) | files | bytes | manifest16 | mtime | Disposition |
|---|---|---|---|---|---|
| F1-#77-01 | 186 | 48,693,844 | d28b4cf0da5c68be | 07-11 11:37 | valid-finalizable (FP R1, 13 laps) |
| F1-#77-02 | 187 | 27,259,236 | 365a4216908d2326 | 07-11 11:37 | valid-finalizable (FP R2, 6 laps) |
| SP-#77-01 | 187 | 22,047,510 | 9980eacd89d6a4dc | 07-11 11:30 | valid-finalizable (SP R1, 5 laps) |
| SP-#77-02 | 188 | 22,785,930 | e42bbddfec4e5254 | 07-11 11:30 | valid-finalizable (SP R2, 5 laps) |
| SP-#77-03 | 188 | 34,770,811 | 65dd89a4822d225f | 07-11 11:32 | valid-finalizable (SP R3, 8 laps) |
| **SP-77-03** (name variant, no `#`) | 254 | 80,116,222 | 69fb885c936ae370 | 07-11 11:34 | **rejected — registry status `incomplete`**; nonstandard content (26_DoGP_* analysis CSV exports mixed in); duplicate of SP-#77-03; never queued; must NOT be imported |
| **SX_F1-#77-01** | 29 | 10,109,082 | 8b96c4aaa5f6a090 | 07-11 11:37 | **rejected — known FAIL-quarantined in queue (status=failed)**; partial folder (29 files); telemetry duplicates F1-#77-01 (identical best 89.960 / 13 laps) |
| SX_F1-#77-01.MES.zip | (file) 3,162,470 | sha16 2751d02eafd62083 | | 07-10 13:22 | rejected — zip twin of above, not an outing |
| **SX_SP-#77-03** | 30 | 7,492,169 | 61637bd8922b102b | 07-11 11:34 | **rejected — known FAIL-quarantined (status=failed)**; partial; duplicates SP-#77-03 (identical best 89.622 / 8 laps) |
| SX_SP-#77-03.MES.zip | (file) 2,208,933 | sha16 1badf528f7b5aeba | | 07-10 18:53 | rejected — zip twin, not an outing |
| **WU1-#77-01** | 186 | 4,133,026 | 914a203baa2d3ff6 | 07-11 11:16 | **rejected — queue status=failed (zero-valid-lap outing, 4.1 MB = out-lap only)** |
| **WU1-#77-02** | 186 | 8,774,489 | bfccf4b72e1c529c | 07-11 11:20 | **rejected — queue status=failed (zero-valid-lap outing)** |
| WU1-#77-03 | 188 | 30,615,221 | 24ea7e19c8b1128f | 07-11 11:32 | valid-finalizable (WUP1 R1, 7 laps) |
| WU2-#77-01 | 187 | 29,970,248 | ba19d01e5f580201 | 07-12 12:14 | valid-finalizable (WUP2 R1, 7 laps) — **queue status=pending, never imported to provisional** |
| R1-#77-01 | 190 | 83,311,767 | ec159c46331aea81 | 07-11 17:45 | valid-finalizable (RACE1 R1, 20 laps) |

Loose event files (DBC_IMPORT.CAL 0B, Donington Park.line 36B sha16 3a12e2a9, EVENT.INI 777B a0eb8226, GPS SECTIONS.TXT 0B, RING.INI 267B, RING.REN 1592B, Ring.mps 0B, T.CSV 2751B, Users.ini 87B, .DS_Store) = event metadata, not outings; `.line` confirms circuit DONINGTON.

No DA77 Race2 .MES (no R2-#77-*) — confirmed absent. **No silent skip: every entry in both event folders is listed above with a disposition.**

Queue state (canonical, read-only): JA52 8× awaiting_gate; DA77 7× awaiting_gate + 4× failed (SX_F1, SX_SP, WU1-01, WU1-02) + 1× pending (WU2-#77-01). SP-77-03 registered `incomplete` (2d_outing, folder-level), correctly never queued.

## 2. Dry-run results (approved extractors, no writes)

- `session_extract_staging.py --event 20260710-ROUND8-JA52 --required-round ROUND8` (dry-run): 0 candidates — all 8 JA52 outings already imported (awaiting_gate). Expected.
- `session_extract_staging.py --event 20260710-ROUND8-DA77 --required-round ROUND8` (dry-run): circuit=DONINGTON (.line), 1 candidate = WU2-#77-01 → **gate WARNING (structural), run PROV_20260710_ROUND8_DONINGTON_WUP2_DA77_R1, laps=7, best=89.885**. Dry-run report: `reports/session_staging_dryrun_20260713_003641.md`. Provisional therefore lacks a valid DA77 WUP2 run that exists on disk.
- Report reader (`build_master_db.parse_report`, read-only): circuit_from_report = DONINGTON; comments for all 9 keys (FP1,FP2,QP1-3,WUP1,WUP2,RACE1,RACE2) + WEEKEND SUMMARY; start/end setups present (C106/R104).
- `Data_Base_TS24_ORIGINAL.xlsx` (openpyxl read-only): 11 JA52×DONINGTON rows, 0 DA77 rows.
  - Rows 260–268 (appended 2026-07-12): ROUND8 set — FP×2, QP×3, WUP1, RACE1, WUP2, RACE2, all setting C106.
  - Rows 14–15 (legacy, 2025 BSB Donington): RACE1, RACE2 with setting C104 — **same natural key (RIDER,CIRCUIT,SESSION,RUN) as the ROUND8 RACE1/RACE2 rows** (Original has no round/date column). See §3c.
- `pdf_result_extractor_v2.extract_pdf(path, all_riders=True)` on all 6 PDFs: all parse with meta round=ROUND8, circuit=DONINGTON, date=2026-07-10; team riders present in every session:

| PDF | riders | lap rows (all riders) | #52 pos/best (valid laps) | #77 pos/best (valid laps) |
|---|---|---|---|---|
| FP | 34 | 614 | 11 / 89.954 (19v/21) | 12 / 89.961 (18v/19) |
| QP | 34 | 612 | 4 / 89.128 (15v/19) | 13 / 89.622 (15v/19) |
| WUP1 | 33 | 193 | 3 / 89.206 (6v) | 21 / 90.109 (6v) |
| WUP2 | 34 | 201 | 24 / 89.997 (6v) | 19 / 89.888 (6v) |
| RACE1 | 33 | 587 | 3 / 89.205 (18v/19) | 12 / 89.739 (18v/19) |
| RACE2 | 33 | 579 | 6 / 89.040 (18v/19) | 14 / 89.493 (18v/19) |

Total PDF lap rows (v2 staging candidate scale): 2,786.

## 3. ROUND8-only scratch build

Command: `python3 build_master_db.py --all --round ROUND8 --out /tmp/ts24_r8_scratch.db` — completed; **acceptance gate |2D session best − PDF best| > 1.5s: 0 cases (PASS)**; circuit in every ROUND8 runs/lap_suspension row = exactly `DONINGTON`; `%PARK%` rows = 0.

ROUND8-scoped scratch content: **19 runs / 165 laps / 165 lap_suspension** (lap↔suspension equality holds):

| Rider | Session | Runs | Laps | Best | Source | Note |
|---|---|---|---|---|---|---|
| JA52 | FP | 2 | 21 | 89.960 | ORIGINAL+2D | |
| JA52 | QP | 3 | 18 | 89.123 | ORIGINAL+2D | |
| JA52 | WUP1 | 1 | 7 | 89.202 | ORIGINAL+2D | |
| JA52 | WUP2 | 1 | 7 | 89.994 | ORIGINAL+2D | |
| JA52 | RACE1 | 2 | 20 | 89.195 | R1=ORIGINAL+2D, R2=ORIGINAL 0-lap | **R1 carries C104 (2025 setup), R2 carries C106 — see §3c** |
| DA77 | FP | 2 | 19 | 89.960 | 2D_ONLY | |
| DA77 | SP | 3 | 18 | 89.622 | 2D_ONLY | |
| DA77 | WUP1 | 1 | 7 | 90.105 | 2D_ONLY | |
| DA77 | WUP2 | 1 | 7 | 89.885 | 2D_ONLY | **new vs provisional** |
| DA77 | RACE1 | 1 | 20 | 89.738 | 2D_ONLY | |
| DA77 | **SX** | **2** | **21** | — | 2D_ONLY | **CONTAMINANT — must be excluded (§3b)** |

RACE2 telemetry rows in scratch (round='ROUND8'): **0 runs / 0 laps / 0 lap_suspension — Race2 hold confirmed** (see §5).

### 3a. Scratch vs provisional lap-level comparison (§65b-style)

Join on (rider, session, run_no, lap_no); compared lap_time_s, lap_susF_mean, lap_susR_mean, f_dive_spd, r_dive_spd:

- Common laps: **137/137 — value mismatches: 0** (exact match to float precision).
- Provisional-only laps: 0.
- Scratch-only laps: 28 = DA77 SX 21 (contaminant) + DA77 WUP2 7 (legitimate new; queue-pending outing verified in dry-run: laps=7 best=89.885, identical in scratch).

Verdict: build_master_db and the live-provisional pipeline are numerically identical on all shared content.

### 3b. SX contamination (blocker for a naive apply)

`build_master_db` reads the event folders from disk and ingested `SX_F1-#77-01.MES` / `SX_SP-#77-03.MES` as session "SX" → runs `20260710_ROUND8_DONINGTON_SX_DA77_R1/R2` (13+8=21 laps), telemetry-identical duplicates of DA77 FP-01 and SP-03 (bests 89.960 / 89.622). The staging/queue layer FAIL-quarantined these, but the scratch-build layer has no such filter, and the PDF acceptance gate cannot catch them (no "SX" session in any PDF). **The Phase-2 targeted insert MUST exclude session='SX' rows (equivalently run_id LIKE '%_SX_%').** With SX excluded: valid scratch = 17 runs / 144 laps / 144 lap_suspension.

### 3c. Original duplicate-key / setup mis-attachment (JA52 RACE1) — decision required

Original keeps 2025 BSB Donington rows (C104) and 2026 ROUND8 rows (C106) under identical keys (JA52, DONINGTON, RACE1|RACE2, RUN 1). Build behavior observed in scratch:

- RACE1 (2D anchor exists): telemetry run R1 receives the **first** Original row = **C104 (2025, wrong for ROUND8)**; the correct 2026 C106 setup lands on the 0-lap ORIGINAL-only R2. Same mechanism as Round7 §64b, but here the stray row is **cross-event (2025 BSB)**, so the mis-attachment is factually wrong, not merely cosmetic.
- RACE2 (no 2D): the ×2 duplicate collapses to `NA_DONINGTON_RACE2_JA52_R1` (round=NULL) carrying **C104**; the 2026 C106 RACE2 setup is not represented anywhere in the scratch output.
- Canonical currently holds `NA_DONINGTON_RACE1_JA52_R1` and `NA_DONINGTON_RACE2_JA52_R1` (both C104, 0 laps, round=NULL) — these are pre-existing 2025-era Original-only rows, not Round8 placeholders.

Options for Phase 2 (operator decision, do not improvise):
1. **Preferred**: Tatsuki (or supervisor-approved edit) renames the two 2025 rows' CIRCUIT in Original (e.g. DONINGTON→DONINGTON_BSB25) or moves them out, then rebuild scratch → RACE1 R1 gets C106, no R2 ghost, RACE2 C106 goes to the NA_ placeholder. Clean fix at the source.
2. Apply as-is and post-fix the two setup payloads by UPDATE inside the same transaction (swap C104/C106 between RACE1 R1 and R2) — auditable but hand-edited canonical data.
3. Apply as-is and document the known mis-attachment — NOT recommended (wrong fork/shock setup attached to the ROUND8 RACE1 telemetry run).

Until one option is approved this is a **NO-GO flag on the telemetry apply for JA52 RACE1 setup fields** (telemetry values themselves are unaffected and fully verified).

## 4. Session/source matrix

| Rider | Session | 2D | Report | Original | Result PDF | Status |
|---|---|---|---|---|---|---|
| JA52 | FP | 2 outings ✓ | ✓ | ✓ (2) | ✓ | **valid-finalizable** |
| JA52 | QP | 3 outings ✓ | ✓ | ✓ (3) | ✓ | **valid-finalizable** |
| JA52 | WUP1 | 1 ✓ | ✓ | ✓ | ✓ | **valid-finalizable** |
| JA52 | WUP2 | 1 ✓ | ✓ | ✓ | ✓ | **valid-finalizable** |
| JA52 | RACE1 | 1 ✓ | ✓ | ✓ (dup-key ×2 → §3c) | ✓ | **valid-finalizable (setup attach pending §3c decision)** |
| JA52 | RACE2 | **missing (.MES none)** | comment only | ✓ (dup-key ×2) | ✓ | **official-PDF-only / telemetry pending** |
| DA77 | FP | 2 ✓ | none (no DA77 report) | none | ✓ | **valid-finalizable (2D_ONLY)** |
| DA77 | SP | 3 ✓ | none | none | ✓ (QP PDF) | **valid-finalizable (2D_ONLY)** |
| DA77 | WUP1 | 3 outings: 1 valid + 2 zero-lap | none | none | ✓ | **valid-finalizable (WU1-03); WU1-01/02 rejected: zero-valid-lap (queue failed)** |
| DA77 | WUP2 | 1 ✓ (queue pending) | none | none | ✓ | **valid-finalizable (2D_ONLY, new)** |
| DA77 | RACE1 | 1 ✓ | none | none | ✓ | **valid-finalizable (2D_ONLY)** |
| DA77 | RACE2 | **missing (.MES none)** | none | none | ✓ | **official-PDF-only / telemetry pending** |
| DA77 | (SX_F1/SX_SP) | partial dup folders | — | — | n/a | **rejected-with-reason: FAIL-quarantined duplicates of FP-01/SP-03; exclude from apply** |
| DA77 | (SP-77-03 variant) | nonstandard folder | — | — | n/a | **rejected-with-reason: registry `incomplete`, duplicate name variant with analysis CSVs** |

## 5. Race2 hold confirmation

- Scratch build round='ROUND8' RACE2 runs/laps/lap_suspension = **0 / 0 / 0** — no fabricated telemetry.
- No Race2 .MES exists for either rider (verified on disk; only declared missing source).
- RACE2 PDF extracts cleanly (33 riders, 579 lap rows; #52 pos 6 best 89.040, #77 pos 14 best 89.493) → race_results candidates CAN be generated.
- Canonical race_results ROUND8 rows = 0 (DONINGTON rows in race_results are ROUND2/COMPANY BSB only — natural key (round, session_type, rider_num) means no collision).
- Race2 apply tooling: Round7 used `apply_round7_race_results.py`. It hardcodes ROUND7 dir, MISANO physical lap-time range (~97–105s) and round literals → **a ROUND8 equivalent is needed** (see §8).

## 6. Cross-check matrix (Report ↔ Original ↔ PDF ↔ scratch 2D)

Run counts: Report comment keys (FP2/QP3/WUP1/WUP2/RACE1/RACE2 ×1) == Original ROUND8 rows (9) == scratch JA52 2D outings (8, RACE2 none) — consistent (RACE2 = comment+setup only, no 2D, as declared). DA77: no Report/Original (2D_ONLY) — expected, not a mismatch.

Best laps, scratch 2D vs official PDF (tolerance ~0.05s per §65):

| Rider/Session | 2D best | PDF best | Δ |
|---|---|---|---|
| JA52 FP | 89.960 | 89.954 | 0.006 ✓ |
| JA52 QP | 89.123 | 89.128 | 0.005 ✓ |
| JA52 WUP1 | 89.202 | 89.206 | 0.004 ✓ |
| JA52 WUP2 | 89.994 | 89.997 | 0.003 ✓ |
| JA52 RACE1 | 89.195 | 89.205 | 0.010 ✓ |
| DA77 FP | 89.960 | 89.961 | 0.001 ✓ |
| DA77 SP | 89.622 | 89.622 (QP PDF) | 0.000 ✓ |
| DA77 WUP1 | 90.105 | 90.109 | 0.004 ✓ |
| DA77 WUP2 | 89.885 | 89.888 | 0.003 ✓ |
| DA77 RACE1 | 89.738 | 89.739 | 0.001 ✓ |

10/10 within tolerance. Official positions available for all 6 sessions ×2 riders (see §2 table). Setup fields: present for all JA52 sessions (C106 line), with the single §3c attachment defect; absent by design for DA77. Lap-count triangulation: PDF valid-lap counts vs 2D lap counts differ only by known conventions (out/in-laps and cancelled laps; e.g. JA52 FP 2D 21 vs PDF 21 rows/19 valid; RACE1 2D 20 vs PDF 19 timed rows — race lap-1 convention, same as Round7). No unexplained mismatch. **Only open item = §3c setup attachment (flagged NO-GO until decided).**

## 7. Expected Phase-2 insert counts (after SX exclusion)

Telemetry targeted insert (runs / laps / lap_suspension):

| Rider | Session | Runs | Laps | LS |
|---|---|---|---|---|
| JA52 | FP | 2 | 21 | 21 |
| JA52 | QP | 3 | 18 | 18 |
| JA52 | WUP1 | 1 | 7 | 7 |
| JA52 | WUP2 | 1 | 7 | 7 |
| JA52 | RACE1 | 2 (R1 20-lap + R2 0-lap ORIGINAL) | 20 | 20 |
| DA77 | FP | 2 | 19 | 19 |
| DA77 | SP | 3 | 18 | 18 |
| DA77 | WUP1 | 1 | 7 | 7 |
| DA77 | WUP2 | 1 | 7 | 7 |
| DA77 | RACE1 | 1 | 20 | 20 |
| **Total** | | **17** | **144** | **144** |

Expected canonical totals after telemetry apply: runs 286+17=**303**, laps 1279+144=**1423**, lap_suspension 1279+144=**1423** (if the §3c decision leaves NA_DONINGTON_* rows untouched; option 1 rebuild does not change these counts; deleting the two NA_ rows would instead give runs 301 and remove 2025-era Original-only data — NOT recommended without separate approval, they are not Round8 placeholders).

race_results apply (§36a convention — RACE full field, FP/QP/WUP team only): RACE1 33 + RACE2 33 + FP 2 + QP 2 + WUP1 2 + WUP2 2 = **74 rows** → race_results 866→940. Existing ROUND8 collisions = 0 (verified).

pdf_lap_times / v2 staging: 6 PDFs, 2,786 lap rows total (all riders) as v2 staging candidate scale; exact PASS/WARNING counts to be produced by the approved `pdf_v2_scratch_gate.py` / `apply_pdf_v2_staging.py` dry-run path at apply time (out of Phase-1 scope; no dry-run writes attempted since gate tools write staging tables).

Provisional-clear expectation (after canonical verify): remove ROUND8 provisional 15 runs / 137 laps / 137 lap_suspension (keys `PROV_20260710_ROUND8_DONINGTON_*`); queue terminal states to record: 15 imported outings → done/promoted; WU2-#77-01 pending → promoted-via-final (or done) with note; 4 failed (SX_F1, SX_SP, WU1-01, WU1-02) and SP-77-03 `incomplete` remain as terminal evidence — do NOT delete.

## 8. Recommended apply procedure (Round7 §65 method, generalized — NOT executed)

`apply_round7_targeted_insert.py` is Round7-hardcoded and **needs a ROUND8 generalization** (a new `apply_round8_targeted_insert.py` or a parameterized tool; no code was modified this session). Required changes:

1. Round literal `ROUND7` → `ROUND8` in all gates/filters.
2. PLACEHOLDERS: Round7 deleted NA_MISANO_*; for ROUND8 default to **deleting nothing** (NA_DONINGTON_* are 2025-era rows, pending §3c decision).
3. EXPECT_BEST / EXPECT_ZERO_LAP tables → ROUND8 values from §3/§7 of this report (17 run_ids; zero-lap = 20260710_ROUND8_DONINGTON_RACE1_JA52_R2 only).
4. **New: SX exclusion filter** (`session != 'SX'`) applied to the insert SELECTs plus a hard assertion that no inserted run_id contains `_SX_`.
5. **New: Race2 hard assertion** — inserted rows with session='RACE2' must be exactly 0.
6. cross_source_gate: provisional_event_key is per-rider now — check both `20260710-ROUND8-JA52` and `20260710-ROUND8-DA77`; DA77 WUP2 has no provisional twin → verify against the staging dry-run values (laps=7, best 89.885) instead.
7. content_gate: NULL-setup check must exempt DA77 2D_ONLY runs (Round7 was JA52-only).
8. Keep: WAL-safe backup, single transaction, explicit column lists, protected-table before/after counts, orphan/duplicate checks, lap↔suspension equality, rollback on any failed invariant.

race_results: create `apply_round8_race_results.py` analogous to the Round7 tool with ROUND8_DIR=`07_RESULTS/ROUND8_DONINGTON_20260710`, round=ROUND8, Donington physical lap-time range (~85–100s; Round7's 97–105s MISANO range would reject every Donington lap), team-only non-race convention (74 candidates), collision gate (currently 0).

Order: (1) backup → (2) race_results + PDF path apply incl. Race2 → (3) telemetry targeted insert (SX excluded, Race2 assert 0) → (4) verify → (5) provisional clear → each with its own receipt.

## 9. Blockers / GO conditions

| # | Item | Severity | Status |
|---|---|---|---|
| 1 | §3c JA52 RACE1/RACE2 setup attachment (2025 C104 vs 2026 C106 duplicate key in Original) | **NO-GO until operator decision** (option 1 recommended: fix Original, rebuild scratch, re-verify) | OPEN |
| 2 | SX contamination in scratch (2 runs/21 laps) | Blocker for naive apply; resolved by mandatory SX exclusion filter + assertion (§8.4) | MITIGATION DEFINED |
| 3 | Round7 apply tools are round-hardcoded | Need generalized ROUND8 tools + dry-run before any write (§8) | OPEN (build task) |
| 4 | DA77 WUP2 missing from provisional | Not a blocker — scratch includes it and it is dry-run verified; provisional-clear bookkeeping must cover the pending queue row | NOTED |
| 5 | Everything else (inventory, hashes, PDF extraction ×6, circuit normalization, 137/137 lap match, best-lap deltas ≤0.010s, Race2 hold, race_results collision=0) | — | **PASS** |

Overall Phase-1 verdict: **conditional GO** — telemetry values and official data fully verified; apply may proceed only after (a) §3c decision executed and scratch rebuilt/re-verified, and (b) generalized ROUND8 apply tools exist and pass their own dry-run.

## 10. Canonical DB integrity (read-only proof)

- sha256 before session: `2eedecbd04f822e835a917e9fc4256907996acee5b5194229d8b530834a5cc22`
- sha256 after session: `2eedecbd04f822e835a917e9fc4256907996acee5b5194229d8b530834a5cc22` — **byte-identical; canonical DB untouched.**
- All canonical access used `file:...?mode=ro`. Scratch artifacts: `/tmp/ts24_r8_scratch.db` only. No `--apply` executed; no source files modified.
