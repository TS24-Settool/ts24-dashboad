# TS24 SET-UP TOOL — PUCCETTI KAWASAKI SUSPENSION MANAGEMENT SYSTEM
**Last Updated:** 2026-04-18 (ROUND3 ASSEN complete — official results in SQLite, Streamlit dashboard launched, automated PDF→DB workflow added)
**Language Policy:** All files in this folder use ENGLISH as the standard language (except .docx Word documents)
**Season:** TS24 (2025-10 – 2026 ongoing)
**Team:** Puccetti Racing | Bike: Kawasaki ZX-636
**Riders:** JA52, DA77
**Platform:** macOS (MacBook)

---

## FOLDER STRUCTURE (Active)

```
Data TS24 Claude/               ← ~/Desktop/Data TS24 Claude/  (iCloud synced)
├── 01_REPORTS/
│   ├── DA77/                   ← All DA77 event reports (.xlsx/.xlsm)
│   └── JA52/                   ← All JA52 event reports (.xlsx/.xlsm)
├── 02_DATABASE/
│   └── PUCCETTI_DB_MASTER.xlsx ← Main working file (always use this one)
├── 03_TEMPLATES/
│   ├── NEW_EVENT_TEMPLATE.xlsx
│   ├── NEW_EVENT_TEAM_REPORT_TEMPLATE.xlsx  ← Includes CLAUDE_BRIEFING sheet
│   └── NEW_EVENT_TEMPLATE_AI.xlsm
├── 04_REFERENCE/
│   ├── TS24_Knowledge_Base.md  ← Suspension theory, ZX-636 knowledge + RSL shim data (PART 10)
│   ├── TS24_Master_Knowledge_Backup.docx ← Full knowledge backup (.docx)
│   ├── SUSPENSION_DB_UserManual_JA.docx
│   └── Data_Bace_TS24_ORIGINAL.xlsx
├── SS Kawasaki/               ← Ohlins SS simulator data (added 2026-04-16)
│   ├── *.bkx / *.fork / *.shock / *.frame etc.  ← Encrypted binaries (not readable)
│   └── Damping/RSL/*.xlsm     ← RSL shim stack specs (analyzed → KB PART 10)
├── 05_SCRIPTS/
│   ├── _CLAUDE_INDEX.md        ← This file (read at the start of every session)
│   ├── _auto_process.py        ← Auto-processing script for new reports
│   ├── read_delta.py           ← Delta reader script for new entries
│   ├── sync_db_log.py          ← Report xlsx → DB_LOG + auto-calls db_sync.py
│   ├── db_init.py              ← Create/reset SQLite schema (run once)
│   ├── db_sync.py              ← Excel DB_LOG → SQLite sessions table
│   ├── result_sync.py          ← Official result PDFs → SQLite race_results table
│   ├── dashboard.py            ← Streamlit dashboard (Power BI-style)
│   ├── run_mac.sh              ← Mac launcher
│   └── setup_mac.sh            ← First-time setup
├── 06_DELTA/                   ← iPhone → iCloud drop folder
└── 07_RESULTS/                 ← Official WorldSSP result PDFs (per round)
    ├── DAILY_DELTA_TEMPLATE.txt ← Entry template
    ├── DELTA_SAMPLE_FP1_DA77.txt ← Sample entry
    └── DELTA_YYYYMMDD_SESSION_RIDER.txt  ← Actual delta files
```
> Note: The 06_DELTA folder can be posted to directly from iPhone via iCloud.

---

## MASTER DB STRUCTURE (02_DATABASE/PUCCETTI_DB_MASTER.xlsx)

| Sheet | Purpose |
|-------|---------|
| DB_LOG | Main session log (1 row = 1 session) — primary reference |
| RUN_LOG | Detailed per-run setup (from original Data Bace TS24) |
| SOLUTION_SEARCH | Problem → solution quick reference |
| TREND_ANALYSIS | Aggregated tag counts by rider and trend |
| DAY1 / DAY2 / REPORT | New event input templates |

---

## SESSION HISTORY (Latest First)

| # | SESSION_ID | DATE | CIRCUIT | RIDER | KEY PROBLEMS |
|---|-----------|------|---------|-------|-------------|
| 21 | 20260417-ROUND3-JA52 | 2026-04-17 | ASSEN | JA52 | nervousness, no_turn_in, push_rear_exit / BEST LAP: 1'37.4 (QP) |
| 20 | 20260417-ROUND3-DA77 | 2026-04-17 | ASSEN | DA77 | nervousness, no_turn_in, push_rear_exit / BEST LAP: 1'37.0 (QP) |
| 19 | 20260327-ROUND2-JA52 | 2026-03-27 | PORTIMAO | JA52 | chattering_brake, nervousness, no_turn_in, push_rear_exit |
| 18 | 20260327-ROUND2-DA77 | 2026-03-27 | PORTIMAO | DA77 | chattering_brake, no_turn_in, push_rear_exit, line_loss_exit |
| 16 | 20260313-TEST4-DA77 | 2026-03-13 | CREMONA | DA77 | chattering_brake, line_loss_exit |
| 15 | 20260313-TEST4-JA52 | 2026-03-13 | CREMONA | JA52 | chattering_brake, no_turn_in, push_rear_exit |
| 14 | 20260220-ROUND1-DA77 | 2026-02-20 | PI (Mugello) | DA77 | chattering_brake, no_turn_in, line_loss_exit |
| 13 | 20260220-ROUND1-JA52 | 2026-02-20 | PI (Mugello) | JA52 | no_turn_in, line_loss_exit |
| 12 | 20260216-TEST3-DA77 | 2026-02-16 | PI | DA77 | nervousness, line_loss_exit |
| 11 | 20260216-TEST3-JA52 | 2026-02-16 | PI | JA52 | chattering_brake, nervousness, push_rear_exit |
| 10 | 20260126-TEST2-DA77 | 2026-01-26 | PORTIMAO | DA77 | no_turn_in, line_loss_exit |
| 9  | 20260126-TEST2-JA52 | 2026-01-26 | PORTIMAO | JA52 | line_loss_exit |
| 8  | 20260121-TEST1-DA77 | 2026-01-21 | JEREZ | DA77 | chattering_brake, no_turn_in, understeer_apex, push_rear_exit |
| 7  | 20260121-TEST1-JA52 | 2026-01-21 | JEREZ | JA52 | chattering_brake, nervousness |
| 6  | 20251126-TEST1-DA77 | 2025-11-26 | — | DA77 | chattering_brake, nervousness, push_rear_exit |
| 5  | 20251017-ROUND12-JA52 | 2025-10-17 | — | JA52 | chattering_brake, front_dive, nervousness |
| 4  | 20251010-ROUND11-JA52 | 2025-10-10 | ESTORIL | JA52 | chattering_brake, nervousness, push_rear_exit, line_loss_exit |

---

## PROBLEM PHASE REFERENCE (5-Phase Model)

| Phase | Name | Moment on Track | Key Symptoms |
|-------|------|----------------|-------------|
| PH1 | BRAKING | Hard braking before corner | Chattering, front dive, rear light |
| PH2 | CORNER ENTRY / TURN-IN | Trail braking + tip-in | No turn-in, nervousness, vague front |
| PH3 | MID CORNER / APEX | Min speed, max lean | Understeer, push front, chatter on bumps |
| PH4 | CORNER EXIT | Progressive throttle | Push rear, line loss, wheelspin |
| PH5 | HIGH SPEED | Straights + fast sweepers | Weave, tank slapper, instability |

---

## TOP PROBLEM TAGS (All Sessions)

| Tag | Count | Phase | Notes |
|-----|-------|-------|-------|
| chattering_brake | 12 | PH1 | Most frequent for both riders — front-side primary cause |
| push_rear_exit | 9 | PH4 | Common to both riders |
| line_loss_exit | 9 | PH4 | Chronic PH4 issue |
| no_turn_in | 8 | PH2 | Confirmed for both riders in ROUND2 |
| nervousness | 8 | PH2 | Especially in wet / cold conditions |

---

## KEYWORD TAG DICTIONARY

| Tag | Phase | Meaning | Solution Direction |
|-----|-------|---------|-------------------|
| chattering_brake | PH1 | Front chattering under braking | F_SPRING↑, F_COMP soften, OIL_LEVEL↓ |
| front_dive | PH1 | Excessive front dive / bottoming | F_SPRING↑, F_PRELOAD↑, OIL_LEVEL↑ |
| nervousness | PH2 | General instability / peaky feel | F_REB slow, R_COMP soften, GEOMETRY check |
| no_turn_in | PH2 | Resistance to tip-in on corner entry | FRONT_HEIGHT↑, OFFSET↑, F_REB↓ |
| understeer_apex | PH3 | Understeer at apex | F_HEIGHT↑, R_HEIGHT↓, F_SPRING check |
| push_rear_exit | PH4 | Rear pushes outward on throttle | R_COMP↑(LSC), SWING_ARM↓, RIDE_HEIGHT balance |
| line_loss_exit | PH4 | Cannot hold line after throttle application | R_COMP↑, F_REB↓(TOS), RIDE_HEIGHT↑ |
| weave_highspeed | PH5 | High-speed weave | F_REB slow, R_REB slow, OFFSET↑ |

---

## HARDWARE REFERENCE

### Front Fork (FKR123)
- Spring: L/R independent (typical range 9–10 N/mm)
- TOS (Top Out Spring): mixed use of 2.7×60, 4×40, 1×135
- Oil Level: 200–230 mm
- Comp / Reb: click count
- **RSL_040 shim stack**: C101–C106 / R101–R106 → see KB PART 10.2
- **ROUND3 current setting**: DA77 & JA52 both C104 / R104 (mid-hard, 4th of 6 steps)

### Rear Shock
- TTX36: main unit
- S46: alternative (partial use on DA77)
- Spring: 80–104 N/mm
- TOS: 7×100, 8×100, 8×150, 8×188 etc.
- **RSL_019 shim stack**: C1–C9+C21 / R1–R9+R41 → see KB PART 10.3
- **ROUND3 current setting**: DA77 C7/R5 (C very hard, 7th of 9) / JA52 C45/R5 (C45 outside RSL range — team custom)

### Geometry
- Ride Height: 244–253 mm (varies FP→Race)
- Swing Arm: 556–575 mm (varies by setup)
- Offset: 26 / -0.5° as standard (JA52 from CREMONA onwards)
- Front Height TOP/BOTT: 0–4 / 484–492 mm

---

## ZERO CHASSIS — Key Physical Data (see KB PART 11)

### Anti-Squat (by Position)
| Position | JA52 Round3 | DA77 Round2 | Meaning |
|----------|------------|------------|---------|
| **Static (Travel=0)** | **125.7%** | **126.2%** | ⚠️ Abnormally high for both riders |
| **Under braking** | **113.6%** | — | Drops as fork compresses but still >100% |
> → >100% at all positions = rear always tends to LIFT under throttle = chronic push_rear_exit root cause

### Rider Geometry Baseline (Confirmed Values)
| Parameter | JA52 (Round3) | DA77 (Round2) | Notes |
|-----------|--------------|--------------|-------|
| **Frame** | FrameJA5_26 | Frame519_JA01 | ⚠️ Different frames |
| **Rake** | 23.8° | 24.3° | DA77 +0.5° more (stability-biased) |
| **Trail** | 104.7 mm | 103.4 mm | JA52 +1.3 mm more trail |
| **Wheelbase** | 1399 mm | 1411.5 mm | DA77 +12.5 mm longer |
| **Offset** | 26 mm | 30 mm | JA52 less offset |
| **SAL** | 560 mm | 563 mm | JA52 3 mm shorter |
| **Fw rate (static)** | 30.1 N/mm | 26.1 N/mm | JA52 +4 N/mm stiffer |
| Fork travel @Brk | ~114 mm | — | Max stroke under braking |
| Linkage | WSSNG-06 | WSSNG-06 | Same (updated to NG-06 from ROUND3) |

> Sharing Zero Chassis screenshots enables pre-simulation → higher accuracy in setup proposals

---

## RSL SHIM STACK QUICK REFERENCE

| Component | RSL File | Click Range | DA77 Current | JA52 Current | Detail |
|-----------|----------|-------------|--------------|--------------|--------|
| FKR123 COMP | RSL_040 | C101–C106 | **C104** (4/6) | **C104** (4/6) | KB 10.2 |
| FKR123 REB | RSL_040 | R101–R106 | **R104** (4/6) | **R104** (4/6) | KB 10.2 |
| TTX36 COMP | RSL_019 | C1–C9+C21 | **C7** (7/9 ⚠️ high) | **C45** (outside RSL / team custom) | KB 10.3 |
| TTX36 REB | RSL_019 | R1–R9+R41 | **R5** (5/9) | **R5** (5/9) | KB 10.3 |

> ⚠️ DA77 shock C7 is at a very high position — may be related to chattering issues.

---

## CIRCUIT NOTES

| Circuit | Lap | Key Character |
|---------|-----|--------------|
| ESTORIL | ~1:46 | Mix of high-speed and technical sections |
| JEREZ | ~1:42 | Many slow corners, gentle on tyres |
| PORTIMAO | 4.592 km | Heavy elevation changes, rear grip critical |
| PI (Mugello) | ~5.2 km | High-speed, high chattering risk circuit |
| CREMONA | ~4.0 km | Flat, mainly medium-speed corners |
| ASSEN | 4.555 km | Classic circuit, smooth surface. Reference: 1'36.490 (SP 2026). S3=lean angle key, S4=exit push risk |

---

## WORKFLOW FOR NEW SESSION (Mac)

### At track / after returning (Windows PC)
1. Fill in **NEW_EVENT_TEMPLATE** in Excel on the team PC with the day's data and save
2. Transfer the completed Excel file (`YYYYMMDD-[TYPE]-[RIDER].xlsx`) to this Mac via USB or cloud

### On MacBook (home / hotel)
3. Place the transferred Excel file in the **root of `Data TS24 Claude/`** (top level)
4. Run `05_SCRIPTS/run_mac.sh` in Terminal:
   ```bash
   bash ~/Desktop/"Data TS24 Claude"/05_SCRIPTS/run_mac.sh
   ```
   → Automatically sorted into `01_REPORTS/[RIDER]/` and registered in DB_LOG
5. **Request analysis from Claude (Cowork)** → searches past similar cases using this index + DB_LOG
6. **Generate proposals** → combining Motorcycle Dynamics theory with historical data
7. **Update TREND_ANALYSIS** → update tag counts

### Manual DB entry
- Open `02_DATABASE/PUCCETTI_DB_MASTER.xlsx` in Excel for Mac and enter directly into DB_LOG sheet

---

## ⚠️ MANDATORY RULE AFTER DB_LOG UPDATE

**After any change to DB_LOG, always run the following:**

```bash
python3 ~/Desktop/"Data TS24 Claude"/05_SCRIPTS/sync_db_log.py
```

### What this script does
| Target File | Method |
|-------------|--------|
| `02_DATABASE/PUCCETTI_DB_MASTER_BACKUP.xlsx` | Full binary copy via shutil.copy2 |
| `03_TEMPLATES/NEW_EVENT_TEMPLATE_AI.xlsm` | Overwrites DB_LOG values only (preserves formatting) |
| `03_TEMPLATES/NEW_EVENT_TEMPLATE_BackUP.xlsx` | Overwrites DB_LOG values only (preserves formatting) |
| Root-level `*.xlsm / *.xlsx` (event files) | Overwrites DB_LOG values only (auto-scanned) |

### When sync is required
- Adding / deleting / modifying rows
- Entering BEST LAP / RACE RESULT / ENGINEER NOTE
- Adding new event rows (e.g., ROUND3)

> **Claude — Absolute Rules**:
> 1. When a **new report file** (`01_REPORTS/` or root-level `.xlsx/.xlsm`) is detected, read it and auto-generate / update the corresponding DB_LOG row.
> 2. After any change to DB_LOG, always run `sync_db_log.py` to sync all files.
> 3. Do not wait for instructions — act proactively as soon as a report file is detected.

---

## DAILY DELTA WORKFLOW (iPhone → iCloud → Claude)

### Overview
A lightweight report system for sharing daily track session info with Claude during a race weekend via iPhone.
Separate from the team CLAUDE_BRIEFING format — **private quick-report format between the engineer and Claude only**.

### File Structure
| File | Role |
|------|------|
| `06_DELTA/DAILY_DELTA_TEMPLATE.txt` | Entry template (open on iPhone, copy and fill in) |
| `06_DELTA/DELTA_SAMPLE_FP1_DA77.txt` | Sample entry (ASSEN FP1 DA77 example) |
| `06_DELTA/DELTA_YYYYMMDD_SESSION_RIDER.txt` | Actual posted files |
| `05_SCRIPTS/read_delta.py` | Auto-displays new Delta files at session start |

### File Naming Convention
```
DELTA_YYYYMMDD_SESSION_RIDER.txt
e.g.: DELTA_20260417_DAY0_DA77.txt   ← Thursday briefing (weekly target setting)
      DELTA_20260418_FP1_DA77.txt
      DELTA_20260418_FP2_DA77.txt
      DELTA_20260419_QP_JA52.txt
      DELTA_20260420_RACE1_DA77.txt
      DELTA_20260420_RACE2_JA52.txt
```

| SESSION keyword | Meaning |
|---|---|
| DAY0 | Thursday briefing — goal setting with team and riders |
| FP1 / FP2 | Free Practice |
| QP | Qualifying |
| WUP | Warm-Up |
| RACE1 / RACE2 | Race |

### How to Post from iPhone
1. Open the **Files app** on iPhone
2. Navigate to **iCloud Drive → Desktop → Data TS24 Claude → 06_DELTA**
3. Copy `DAILY_DELTA_TEMPLATE.txt` (long-press → Duplicate, or copy text in a text app)
4. Rename the new file using the naming convention (e.g., `DELTA_20260418_FP1_DA77.txt`)
5. **Fill in and save on the spot** → iCloud automatically syncs to Mac
6. Claude auto-detects when MacBook is opened (or at the next consultation)

> **iCloud Sync Note**: `~/Desktop/Data TS24 Claude/` appears as iCloud Drive → Desktop when Desktop sync is enabled. If disabled, place the 06_DELTA folder anywhere in iCloud Drive and create a symlink on Mac.

### read_delta.py Usage
```bash
# Display all unread new Deltas (this is usually enough)
python3 ~/Desktop/"Data TS24 Claude"/05_SCRIPTS/read_delta.py

# Display all Deltas in date order
python3 ~/Desktop/"Data TS24 Claude"/05_SCRIPTS/read_delta.py --all

# Display only the latest 1 entry
python3 ~/Desktop/"Data TS24 Claude"/05_SCRIPTS/read_delta.py --last
```

### Delta Template Structure
| Section | Content |
|---------|---------|
| Header | DATE / SESSION / RIDER / CIRCUIT / CONDITIONS |
| BASELINE | Carry-over setup from previous session |
| CHANGES | Per-run changes and feel (↑ good / ↓ bad / → no change) |
| RESULT | Best lap / total lap count |
| RIDER FEELING | Rider's own words (verbatim) |
| PROBLEMS BY PHASE | Problem tags for PH1–PH5 |
| ? FOR CLAUDE | Questions / hypotheses to discuss with Claude that evening |

### Ideal Race Weekend Cycle
```
Fri FP1 ends  → fill DELTA on iPhone → post to iCloud → consult Claude in evening
Fri FP2 ends  → fill DELTA on iPhone → post to iCloud → confirm direction with Claude at night
Sat QP ends   → fill DELTA on iPhone → post to iCloud → final race setup check with Claude
Sun RACE ends → fill DELTA on iPhone → post to iCloud → integrate learnings for next event
Following week (after returning home) → transfer PC Excel reports to Mac → run run_mac.sh to register in DB
```

---

## MAC ENVIRONMENT

| Item | Detail |
|------|--------|
| OS | macOS (MacBook) |
| Python | 3.10 (`python3`) |
| openpyxl | 3.1.5 ✓ |
| Excel | Excel for Mac ✓ |
| VBA | Some features restricted on Mac Excel (WinHttp, Registry not available) |
| Scripts | bash / Python (PowerShell/BAT archived in `_windows_archive/`) |
| Launcher | `05_SCRIPTS/run_mac.sh` |

---

## NOTES FOR CLAUDE

- Rider comments are typically written in English; Japanese input also accepted
- Engineer notes may contain typos (e.g., comprain=complain, thlottol=throttle) — interpret correctly
- DA77 is very sensitive to corner entry feel (especially in the latter half of braking)
- JA52 struggles with line holding on corner exit (PH4 chronic issue)
- In wet conditions, the front tends to feel overly reactive
- Mixed TOS (Top Out Spring) usage significantly affects dynamic balance on the front
- **ROUND3 (ASSEN 2026-04-17) is the most recently completed event**
- Race 2 grid: JA52 P1 (pole) / DA77 P4 — Race 1 inverted top-9 rule applied
- Official results fully imported: FP/SP/WUP/RACE1 → race_results + sector_results tables
- **Streamlit dashboard**: run `TS24_Dashboard.command` (double-click) → opens at localhost:8501
- **Automated sync**: `TS24_Process_Results.command` (double-click) → Excel + PDFs → SQLite
- **After any DB_LOG change, always run `sync_db_log.py`** (syncs all files + auto-calls db_sync.py)
- **All files in this folder use ENGLISH as the standard language** (except .docx Word documents)
- **iCloud SQLite lock**: All DB scripts use /tmp intermediate file pattern to avoid iCloud mount errors
- **07_RESULTS naming rule**: `ROUND{N}_{CIRCUIT}_{YYYYMMDD}/` → PDFs: `ROUND{N}_{CIRCUIT}_{SESSION}.pdf`

## SQLITE DATABASE STRUCTURE (02_DATABASE/ts24_setup.db)

| Table | Content | Primary Key |
|-------|---------|-------------|
| `sessions` | One row per session — mirrors DB_LOG | session_id |
| `session_tags` | Normalized tags (one row per tag per session) | id |
| `race_results` | Official WorldSSP results per session × rider | round_id + session_type + rider_id |
| `sector_results` | Sector times per session × rider × sector | round_id + session_type + rider_id + sector |

> All write operations use /tmp intermediate file to avoid iCloud mount file-locking (disk I/O error).

## DASHBOARD TABS (dashboard.py)

| Tab | Content |
|-----|---------|
| 問題分析 | Tag frequency by rider, bar chart |
| ヒートマップ | Tag × circuit heatmap |
| シーズントレンド | Tag count per session timeline |
| レース結果 | Official results: positions, gaps, sector analysis |
| セッション詳細 | Full setup detail per session |
