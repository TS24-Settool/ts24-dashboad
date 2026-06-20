# TS24 Part B コンテキスト (複数エージェント診断用)
目的: 残9シートへの正データ反映 / 生データ抽出システム / 全DB結合 / TS24 Workbench反映 の現状把握。

## ts24_unified.db スキーマ

### best_worst_pairs (10行)
```
CREATE TABLE best_worst_pairs(
  pair_id TEXT,
  round INT,
  circuit TEXT,
  rider TEXT,
  analysis_type TEXT,
  run_id_best TEXT,
  session_best TEXT,
  run_no_best INT,
  apex_spd_best REAL,
  dyn_sr_best REAL,
  apex_sus_f_best REAL,
  apex_sus_r_best REAL,
  f_comp_best REAL,
  f_reb_best REAL,
  f_pre_best REAL,
  f_spr_l_best REAL,
  f_spr_r_best REAL,
  r_comp_best REAL,
  r_reb_best REAL,
  r_pre_best REAL,
  sa_best REAL,
  comment_best TEXT,
  run_id_worst TEXT,
  session_worst TEXT,
  run_no_worst INT,
  apex_spd_worst REAL,
  dyn_sr_worst REAL,
  apex_sus_f_worst REAL,
  apex_sus_r_worst REAL,
  f_comp_worst REAL,
  f_reb_worst REAL,
  f_pre_worst REAL,
  f_spr_l_worst REAL,
  f_spr_r_worst REAL,
  r_comp_worst REAL,
  r_reb_worst REAL,
  r_pre_worst REAL,
  sa_worst REAL,
  comment_worst TEXT,
  setup_changes TEXT,
  apex_spd_delta REAL,
  dyn_sr_delta REAL,
  apex_sus_f_delta REAL,
  apex_sus_r_delta REAL,
  obs_apex_sus_f_best TEXT,
  obs_apex_sus_r_best TEXT,
  obs_apex_sus_f_worst TEXT,
  obs_apex_sus_r_worst TEXT,
  obs_pit_sus_f_best TEXT,
  obs_pit_sus_r_best TEXT,
  obs_pit_sus_f_worst TEXT,
  obs_pit_sus_r_worst TEXT,
  obs_brk_sus_f_best TEXT,
  obs_brk_sus_r_best TEXT,
  obs_brk_sus_f_worst TEXT,
  obs_brk_sus_r_worst TEXT,
  rake_delta REAL,
  trail_delta REAL,
  wb_delta REAL,
  cog_x_best TEXT,
  cog_y_best TEXT,
  cog_x_worst TEXT,
  cog_y_worst TEXT,
  cause_analysis TEXT,
  next_race_suggest TEXT,
  screenshot_path TEXT,
  created_at TEXT
)
```

### events (25行)
```
CREATE TABLE events(
  event_id TEXT PRIMARY KEY, date TEXT, round TEXT, rider TEXT, circuit TEXT, report_file TEXT,
  weekend_summary TEXT, start_setup TEXT, end_setup TEXT)
```

### lap_metrics (3606行)
```
CREATE TABLE lap_metrics(
  lap_id TEXT, area TEXT, n INTEGER, susf REAL, susr REAL, speed REAL, brake REAL, thr REAL,
  PRIMARY KEY(lap_id, area))
```

### lap_observation_log (3行)
```
CREATE TABLE lap_observation_log(
  obs_id INT,
  run_id TEXT,
  lap_id TEXT,
  lap_no INT,
  rider TEXT,
  circuit TEXT,
  session TEXT,
  round TEXT,
  lap_time_s REAL,
  pitch REAL,
  heave REAL,
  apex_susf_avg REAL,
  apex_susr_avg REAL,
  observation_type TEXT,
  observation_tag TEXT,
  comment TEXT,
  confidence TEXT,
  created_at TEXT,
  updated_at TEXT
)
```

### lap_suspension (1202行)
```
CREATE TABLE lap_suspension(
  lap_id TEXT PRIMARY KEY, run_id TEXT, round TEXT, circuit TEXT, session TEXT,
  rider TEXT, run_no INTEGER, lap_no INTEGER, date TEXT, lap_time_s REAL, lap_time_fmt TEXT,
  apex_count INTEGER, apex_spd_avg REAL, apex_susF_avg REAL, apex_susR_avg REAL,
  wf_f_apex_n REAL, wf_r_apex_n REAL,
  brk_count INTEGER, brk_spd_avg REAL, brk_susF_avg REAL, brk_susR_avg REAL,
  wf_f_brk_n REAL, wf_r_brk_n REAL,
  fullbrk_count INTEGER, fullbrk_susF REAL, fullbrk_susR REAL,
  lap_susF_mean REAL, lap_susF_min REAL, lap_susF_max REAL, lap_susR_mean REAL,
  updated_at TEXT DEFAULT (datetime('now')))
```

### laps (1202行)
```
CREATE TABLE laps(
  lap_id TEXT PRIMARY KEY, run_id TEXT, lap_no INTEGER, lap_time_s REAL,
  susf_mean REAL, susf_max REAL, susr_mean REAL, mes_file TEXT,
  is_outlap INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)
```

### pdf_lap_times (7613行)
```
CREATE TABLE pdf_lap_times(
  id INT,
  round TEXT,
  circuit TEXT,
  session_type TEXT,
  date TEXT,
  position INT,
  rider_num INT,
  rider_name TEXT,
  lap_no INT,
  seg1 REAL,
  seg2 REAL,
  seg3 REAL,
  seg4 REAL,
  lap_time TEXT,
  lap_time_s REAL,
  speed REAL,
  local_time TEXT,
  is_outlap INT,
  is_pit INT,
  is_cancelled INT,
  source_file TEXT,
  imported_at TEXT,
  data_scope TEXT
)
```

### performance (275行)
```
CREATE TABLE performance(
  run_id TEXT PRIMARY KEY, rider TEXT, circuit TEXT, round TEXT, session TEXT, run_no INTEGER,
  best_lap_s REAL, run_avg_lap_s REAL, session_position INTEGER, n_laps INTEGER)
```

### problem_library (50行)
```
CREATE TABLE problem_library(
  id INT,
  phase_code TEXT,
  phase_name TEXT,
  fase_it TEXT,
  complaint_it TEXT,
  complaint_en TEXT,
  tags TEXT
)
```

### problem_log (4行)
```
CREATE TABLE problem_log(
  problem_id INT,
  run_id TEXT,
  round TEXT,
  circuit TEXT,
  session TEXT,
  rider TEXT,
  run_no INT,
  lap_no INT,
  corner TEXT,
  phase TEXT,
  problem_tag TEXT,
  description TEXT,
  severity TEXT,
  source TEXT,
  export_status TEXT,
  created_at TEXT,
  updated_at TEXT,
  distance_start_m REAL,
  distance_end_m REAL,
  time_start_s REAL,
  time_end_s REAL,
  data_source_file TEXT,
  analysis_note TEXT
)
```

### race_results (792行)
```
CREATE TABLE race_results(
  result_id INT,
  round TEXT,
  circuit TEXT,
  session_type TEXT,
  date TEXT,
  position INT,
  rider_num INT,
  rider_name TEXT,
  nationality TEXT,
  team TEXT,
  bike TEXT,
  laps INT,
  race_time TEXT,
  gap TEXT,
  best_lap TEXT,
  best_lap_s REAL,
  sector1 TEXT,
  sector2 TEXT,
  sector3 TEXT,
  source_file TEXT,
  imported_at TEXT,
  data_scope TEXT
)
```

### round_brief (7行)
```
CREATE TABLE round_brief(
  brief_id TEXT,
  rider TEXT,
  target_round TEXT,
  target_circuit TEXT,
  created_at TEXT,
  brief_type TEXT,
  f_oil_from REAL,
  f_oil_to REAL,
  f_spr_from REAL,
  f_spr_to REAL,
  f_pre_from REAL,
  f_pre_to REAL,
  f_note TEXT,
  r_shl_from REAL,
  r_shl_to REAL,
  r_spr_from REAL,
  r_spr_to REAL,
  r_pre_from REAL,
  r_pre_to REAL,
  r_note TEXT,
  planb_shl REAL,
  planb_spr REAL,
  planb_pre REAL,
  planb_tos TEXT,
  planb_note TEXT,
  memo TEXT
)
```

### run_tags (61行)
```
CREATE TABLE run_tags(run_id TEXT, tag TEXT, source TEXT, PRIMARY KEY(run_id, tag))
```

### runs (275行)
```
CREATE TABLE runs(
  run_id TEXT PRIMARY KEY, rider TEXT, circuit TEXT, round TEXT, session TEXT, run_no INTEGER,
  date TEXT, event_id TEXT, source TEXT, has_2d INTEGER, n_laps INTEGER, best_lap_s REAL, perf_best_lap REAL, comment TEXT,
  weather TEXT, track_temp TEXT, air_temp TEXT, fork_type TEXT, f_set_c TEXT, f_set_r TEXT, f_tos_spring TEXT, f_tos_length TEXT, f_spr_l TEXT, f_spr_r TEXT, f_preload TEXT, f_oil_level TEXT, f_comp TEXT, f_reb TEXT, f_offset TEXT, f_offset2 TEXT, f_hgt_top TEXT, f_hgt_bot TEXT, shock_type TEXT, r_set_c TEXT, r_set_r TEXT, r_spr TEXT, r_preload TEXT, r_comp TEXT, r_reb TEXT, r_tos_spring TEXT, r_tos_length TEXT, shock_len TEXT, link TEXT, ride_hgt TEXT, swing_arm TEXT, tyre_front TEXT, tyre_rear TEXT, updated_at TEXT, created_at TEXT)
```

### setup_decision_log (7行)
```
CREATE TABLE setup_decision_log(
  decision_id INT,
  run_id_from TEXT,
  run_id_to TEXT,
  round TEXT,
  circuit TEXT,
  session TEXT,
  rider TEXT,
  change_type TEXT,
  component TEXT,
  from_value TEXT,
  to_value TEXT,
  rationale TEXT,
  expected_effect TEXT,
  actual_effect TEXT,
  result_eval TEXT,
  export_status TEXT,
  created_at TEXT,
  updated_at TEXT
)
```

### tags (10行)
```
CREATE TABLE tags(tag TEXT PRIMARY KEY, category TEXT, complaint_en TEXT)
```

## comment取りこぼし(要診断)
- runs総数 275 / comment付き 80
- 旧TREND_ANALYSIS: 238run/178comment。新は80。DAYシート row48 の各session列にコメント(c6=FP1,c8=FP2,c10=QP1,...)。
  parse_report は (sess,run_no)キーで run に紐付けるが取りこぼしの疑い(マッチング or 抽出)。

## 残9シートの現状(DB Master)
- 再生成(DB由来・正): RUN_LOG, LAP_TIMES, PERFORMANCE_CORRELATION, DYNAMICS_ANALYSIS, PROBLEM_LIBRARY, LAP_SUSPENSION
- 保持/未再生成(旧内容・要再生成): DB_LOG(セッション台帳+PH1-5), TREND_ANALYSIS(コメント/問題トレンド+COMMENT LOG), SOLUTION_SEARCH(問題→過去事例 手順)

## 生データソース
- DATA 2D/ : .MES(238ch/lean 2形式)
- 01_REPORTS/DA77/ : *.xlsx(DAY1/DAY2/REPORT/CLAUDE_BRIEFING)
- 01_REPORTS/JA52/ : *.xlsx
- 07_RESULTS/ : *.pdf
- 04_REFERENCE/ : Data_Base_TS24_ORIGINAL.xlsx

## 主要スクリプト
- 05_SCRIPTS/build_master_db.py (44KB)
- 05_SCRIPTS/cutover_db.py (5KB)
- 05_SCRIPTS/build_excel_master.py (12KB)
- 05_SCRIPTS/parse_2d_channels.py (62KB)
- 05_SCRIPTS/pdf_result_extractor_v2.py (25KB)
- 05_SCRIPTS/report_importer.py (9KB)
- 05_SCRIPTS/excel_parser.py (9KB)
- 05_SCRIPTS/sync_to_supabase.py (8KB)
- 05_SCRIPTS/ts24_workbench.py (241KB)
- 05_SCRIPTS/dashboard.py (247KB)
- 05_SCRIPTS/lap_suspension_stats.py (40KB)
- 05_SCRIPTS/corner_phase_analysis.py (28KB)
- 05_SCRIPTS/lap_overlay_extractor.py (15KB)

## dashboard/Streamlit が読むJSON
- 05_SCRIPTS/lap_suspension_data.json (2KB)
- 05_SCRIPTS/runs_data.json (424KB)
- 05_SCRIPTS/ts24_config.json (0KB)
- 05_SCRIPTS/turn_templates.json (28KB)

## 他DB
- 02_DATABASE/ts24_master.db (1932KB)
- 02_DATABASE/ts24_setup.db (0KB)
- 02_DATABASE/ts24_unified.db (3572KB)
- 02_DATABASE/ts24_unified.old.db (3572KB)