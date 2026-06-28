-- Result PDF v2 staging DDL（レビュー用・apply_pdf_v2_staging.py が dry-run 出力）
-- 1) staging テーブル + UNIQUE INDEX（apply 時に実行）
CREATE TABLE IF NOT EXISTS pdf_lap_times_v2_staging (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round TEXT, circuit TEXT, session_type TEXT, date TEXT,
    position INTEGER, rider_num INTEGER, rider_name TEXT, lap_no INTEGER,
    seg1 REAL, seg2 REAL, seg3 REAL, seg4 REAL,
    lap_time TEXT, lap_time_s REAL, speed REAL, local_time TEXT,
    is_outlap INTEGER DEFAULT 0, is_pit INTEGER DEFAULT 0, is_cancelled INTEGER DEFAULT 0,
    source_file TEXT, extractor_version TEXT, generated_at TEXT,
    gate_status TEXT, data_scope TEXT DEFAULT 'TS24_PRIVATE'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pdf_v2_staging
  ON pdf_lap_times_v2_staging(round, session_type, rider_num, lap_no, date);

-- 2) INSERT 文テンプレート（apply 時に PASS 行を bind 実行）
INSERT OR REPLACE INTO pdf_lap_times_v2_staging (round, circuit, session_type, date, position, rider_num, rider_name, lap_no, seg1, seg2, seg3, seg4, lap_time, lap_time_s, speed, local_time, is_outlap, is_pit, is_cancelled, source_file, extractor_version, generated_at, gate_status, data_scope) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);

-- 3) Workbench 切替用 VIEW（★別タスク・別承認。apply_pdf_v2_staging では実行しない）
-- 別タスク・別承認で作成（apply_pdf_v2_staging は VIEW を作らない）
CREATE VIEW IF NOT EXISTS race_lap_detail AS
SELECT round,circuit,session_type,date,position,rider_num,rider_name,lap_no,
       seg1,seg2,seg3,seg4,lap_time,lap_time_s,speed,local_time,
       is_outlap,is_pit,is_cancelled,
       source_file, extractor_version, gate_status, 'v2' AS source_tag
  FROM pdf_lap_times_v2_staging
 WHERE gate_status IN ('PASS')
UNION ALL
SELECT p.round,p.circuit,p.session_type,p.date,p.position,p.rider_num,p.rider_name,p.lap_no,
       p.seg1,p.seg2,p.seg3,p.seg4,p.lap_time,p.lap_time_s,p.speed,p.local_time,
       p.is_outlap,p.is_pit,p.is_cancelled,
       p.source_file, NULL AS extractor_version, NULL AS gate_status, 'legacy' AS source_tag
  FROM pdf_lap_times p
 WHERE NOT EXISTS (
   SELECT 1 FROM pdf_lap_times_v2_staging s
    WHERE s.round=p.round AND s.session_type=p.session_type
      AND s.rider_num=p.rider_num AND s.gate_status IN ('PASS'));
