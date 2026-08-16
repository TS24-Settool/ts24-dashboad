-- =====================================================================
-- Race Weekend Session Extraction Staging — provisional 3テーブル DDL 案
-- 日付: 2026-07-06 / Phase A readiness（レビュー用・★未実行★）
-- 対象DB: 02_DATABASE/ts24_unified.db（正本・実行は `Session staging implementation GO` 後のみ）
-- 設計: reports/race_weekend_session_staging_readiness_20260706.md §3
--
-- 原則:
--  * 業務テーブル(runs/laps/lap_suspension/race_results/pdf_lap_times/
--    pdf_lap_times_v2_staging)は一切変更しない。追加のみ（§34/§38 の
--    pdf_lap_times_v2_staging と同パターン: 正本DB内に住むが業務テーブルではない）。
--  * カラム名/型は正本 PRAGMA table_info（2026-07-06 実測）と同一 + 末尾に provenance 6列。
--  * ID規約: run_id = PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}
--            lap_id = {run_id}_L{lap_no}
--    → 'PROV_' プレフィクスにより final run_id（{date}_{round}_...）と構造的に衝突しない。
--  * CREATE TABLE IF NOT EXISTS のみ（冪等・既存データ無害）。
-- =====================================================================

-- ---------------------------------------------------------------------
-- (1) runs_provisional — 正本 runs 49列ミラー + provenance
--     Original 不在のため setup 33列（weather..tyre_rear）は全て NULL のまま。
--     source は '2D_PROVISIONAL' 固定を想定。comment(Report由来) も NULL。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs_provisional(
  run_id TEXT PRIMARY KEY,            -- PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}
  rider TEXT, circuit TEXT, round TEXT, session TEXT, run_no INTEGER,
  date TEXT, event_id TEXT, source TEXT, has_2d INTEGER, n_laps INTEGER,
  best_lap_s REAL, perf_best_lap REAL, comment TEXT,
  weather TEXT, track_temp TEXT, air_temp TEXT, fork_type TEXT,
  f_set_c TEXT, f_set_r TEXT, f_tos_spring TEXT, f_tos_length TEXT,
  f_spr_l TEXT, f_spr_r TEXT, f_preload TEXT, f_oil_level TEXT,
  f_comp TEXT, f_reb TEXT, f_offset TEXT, f_offset2 TEXT,
  f_hgt_top TEXT, f_hgt_bot TEXT, shock_type TEXT, r_set_c TEXT,
  r_set_r TEXT, r_spr TEXT, r_preload TEXT, r_comp TEXT, r_reb TEXT,
  r_tos_spring TEXT, r_tos_length TEXT, shock_len TEXT, link TEXT,
  ride_hgt TEXT, swing_arm TEXT, tyre_front TEXT, tyre_rear TEXT,
  updated_at TEXT, created_at TEXT,
  -- provenance（provisional 専用・final 化時に削除される行の追跡用）
  data_stage TEXT NOT NULL DEFAULT 'provisional',
  intake_ts TEXT NOT NULL,            -- staging 実行時刻(ISO)
  source_manifest_hash TEXT,          -- source_file_registry.sha256（name|size manifest）
  source_file_path TEXT,              -- 抽出元 .MES ディレクトリの絶対パス
  provisional_event_key TEXT,         -- イベントフォルダ名 例 '20260612-ROUND7-JA52'
  quality_status TEXT                 -- PASS / WARNING（FAIL はINSERTしない=隔離）
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_prov_run_id ON runs_provisional(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_prov_event ON runs_provisional(provisional_event_key);

-- ---------------------------------------------------------------------
-- (2) laps_provisional — 正本 laps 16列ミラー + provenance
--     is_outlap は per-session 再計算（readiness §2e 参照）。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS laps_provisional(
  lap_id TEXT PRIMARY KEY,            -- {PROV_run_id}_L{n}
  run_id TEXT, lap_no INTEGER, lap_time_s REAL,
  susf_mean REAL, susf_max REAL, susr_mean REAL, mes_file TEXT,
  f_dive_spd REAL, f_reb_spd REAL, r_dive_spd REAL, r_reb_spd REAL,
  rear_light_brk REAL,
  is_outlap INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT,
  -- provenance
  data_stage TEXT NOT NULL DEFAULT 'provisional',
  intake_ts TEXT NOT NULL,
  source_manifest_hash TEXT,
  source_file_path TEXT,
  provisional_event_key TEXT,
  quality_status TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_laps_prov_lap_id ON laps_provisional(lap_id);
CREATE INDEX IF NOT EXISTS idx_laps_prov_run ON laps_provisional(run_id);
CREATE INDEX IF NOT EXISTS idx_laps_prov_event ON laps_provisional(provisional_event_key);

-- ---------------------------------------------------------------------
-- (3) lap_suspension_provisional — 正本 lap_suspension 69列ミラー + provenance
--     正本 PRAGMA table_info 実測順（0..68）を厳密維持。
--     provisional で NULL のまま残る列（readiness §3b）:
--       wf_f_apex_n / wf_r_apex_n / wf_f_brk_n / wf_r_brk_n / wf_f_ce_n / wf_r_ce_n
--         （バネレート f_spr_l/f_spr_r/r_spr = Original 由来のため算出不能）
--       lap_susF_min（本番 full rebuild でも常時 NULL の既知仕様）
--     run_no は暫定連番（final と一致する保証なし）。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lap_suspension_provisional(
  lap_id TEXT PRIMARY KEY, run_id TEXT, round TEXT, circuit TEXT, session TEXT,
  rider TEXT, run_no INTEGER, lap_no INTEGER, date TEXT, lap_time_s REAL, lap_time_fmt TEXT,
  apex_count INTEGER, apex_spd_avg REAL, apex_susF_avg REAL, apex_susR_avg REAL,
  wf_f_apex_n REAL, wf_r_apex_n REAL,
  brk_count INTEGER, brk_spd_avg REAL, brk_susF_avg REAL, brk_susR_avg REAL,
  wf_f_brk_n REAL, wf_r_brk_n REAL,
  fullbrk_count INTEGER, fullbrk_susF REAL, fullbrk_susR REAL,
  ce_count INTEGER, ce_spd_avg REAL, ce_susF_avg REAL, ce_susR_avg REAL,
  wf_f_ce_n REAL, wf_r_ce_n REAL,
  f_dive_spd REAL, f_reb_spd REAL, r_dive_spd REAL, r_reb_spd REAL, rear_light_brk REAL,
  lap_susF_mean REAL, lap_susF_min REAL, lap_susF_max REAL, lap_susR_mean REAL,
  updated_at TEXT DEFAULT (datetime('now')),
  brk_f_dive_spd_avg REAL, brk_f_dive_spd_peak REAL,
  ce_r_spd_avg REAL, ce_r_spd_peak REAL, ph12_rear0_s REAL,
  -- §44 22列（PHASE_SPD_NEW_COLS 順）
  brk_f_reb_spd_avg REAL,  brk_f_reb_spd_peak REAL,
  brk_r_dive_spd_avg REAL, brk_r_dive_spd_peak REAL,
  brk_r_reb_spd_avg REAL,  brk_r_reb_spd_peak REAL,
  apex_f_dive_spd_avg REAL, apex_f_dive_spd_peak REAL,
  apex_f_reb_spd_avg REAL,  apex_f_reb_spd_peak REAL,
  apex_r_dive_spd_avg REAL, apex_r_dive_spd_peak REAL,
  apex_r_reb_spd_avg REAL,  apex_r_reb_spd_peak REAL,
  ce_f_dive_spd_avg REAL,  ce_f_dive_spd_peak REAL,
  ce_f_reb_spd_avg REAL,   ce_f_reb_spd_peak REAL,
  ce_r_dive_spd_avg REAL,  ce_r_dive_spd_peak REAL,
  ce_r_reb_spd_avg REAL,   ce_r_reb_spd_peak REAL,
  -- provenance
  data_stage TEXT NOT NULL DEFAULT 'provisional',
  intake_ts TEXT NOT NULL,
  source_manifest_hash TEXT,
  source_file_path TEXT,
  provisional_event_key TEXT,
  quality_status TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_lapsus_prov_lap_id ON lap_suspension_provisional(lap_id);
CREATE INDEX IF NOT EXISTS idx_lapsus_prov_run ON lap_suspension_provisional(run_id);
CREATE INDEX IF NOT EXISTS idx_lapsus_prov_event ON lap_suspension_provisional(provisional_event_key);

-- =====================================================================
-- rollback（参考・コメントのみ / 実行は各GO内）
--
-- (a) 全撤去（テーブルごと・業務テーブル無影響）:
--   -- DROP INDEX IF EXISTS idx_lapsus_prov_lap_id;
--   -- DROP INDEX IF EXISTS idx_lapsus_prov_run;
--   -- DROP INDEX IF EXISTS idx_lapsus_prov_event;
--   -- DROP TABLE IF EXISTS lap_suspension_provisional;
--   -- DROP INDEX IF EXISTS idx_laps_prov_lap_id;
--   -- DROP INDEX IF EXISTS idx_laps_prov_run;
--   -- DROP INDEX IF EXISTS idx_laps_prov_event;
--   -- DROP TABLE IF EXISTS laps_provisional;
--   -- DROP INDEX IF EXISTS idx_runs_prov_run_id;
--   -- DROP INDEX IF EXISTS idx_runs_prov_event;
--   -- DROP TABLE IF EXISTS runs_provisional;
--
-- (b) イベント単位クリア（final 化後の通常運用・§50 Stage 5）:
--   -- DELETE FROM lap_suspension_provisional WHERE provisional_event_key='20260612-ROUND7-JA52';
--   -- DELETE FROM laps_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
--   -- DELETE FROM runs_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
--
-- いずれも業務テーブルには構造上到達しない（別テーブルのため）。
-- =====================================================================
