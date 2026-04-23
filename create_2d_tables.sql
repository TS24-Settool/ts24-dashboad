-- ================================================================
-- TS24 Puccetti Racing — 2D Data Tables for Supabase
-- ================================================================
-- Supabase SQL Editor に貼り付けて RUN してください
-- https://supabase.com/dashboard → your project → SQL Editor
-- ================================================================

-- ── 1. セッション情報テーブル (2Dデータ) ────────────────────────
CREATE TABLE IF NOT EXISTS sessions_2d (
    id              BIGSERIAL PRIMARY KEY,
    round           TEXT        NOT NULL,   -- e.g. ROUND1, TEST2
    circuit         TEXT,                   -- e.g. PHILLIP ISLAND
    date            DATE,                   -- 走行日
    session_type    TEXT        NOT NULL,   -- FP / QP / WUP1 / WUP2 / RACE1 / RACE2
    rider           TEXT        NOT NULL,   -- JA52 / DA77
    run_no          INTEGER     NOT NULL DEFAULT 1,
    -- Results
    total_laps      INTEGER,
    best_lap        TEXT,                   -- M:SS.mmm
    best_lap_s      REAL,                   -- seconds
    avg_lap_s       REAL,
    -- Conditions
    condition       TEXT,                   -- DRY / WET
    air_temp        TEXT,
    track_temp      TEXT,
    -- Fork setup
    fork            TEXT,
    fork_spec       TEXT,
    fork_comp       INTEGER,
    fork_reb        INTEGER,
    -- Shock setup
    shock           TEXT,
    shock_spec      TEXT,
    offset          TEXT,
    -- Tyres
    tyre_f          TEXT,
    tyre_r          TEXT,
    tyre_f_press    TEXT,
    tyre_r_press    TEXT,
    tyre_f_laps     TEXT,
    tyre_r_laps     TEXT,
    tyre_f_temp     TEXT,
    tyre_r_temp     TEXT,
    -- Metadata
    imported_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(round, date, circuit, session_type, rider, run_no)
);

-- ── 2. ラップタイムテーブル (2Dデータ) ──────────────────────────
CREATE TABLE IF NOT EXISTS lap_times_2d (
    id              BIGSERIAL PRIMARY KEY,
    round           TEXT        NOT NULL,
    circuit         TEXT,
    date            DATE,
    session_type    TEXT        NOT NULL,
    rider           TEXT        NOT NULL,
    run_no          INTEGER     NOT NULL DEFAULT 1,
    lap_no          INTEGER     NOT NULL,
    lap_time        TEXT,                   -- M:SS.mmm
    lap_time_s      REAL,                   -- seconds
    is_outlap       BOOLEAN     DEFAULT FALSE,
    -- Conditions (denormalized for query convenience)
    condition       TEXT,
    tyre_f          TEXT,
    tyre_r          TEXT,
    UNIQUE(round, date, session_type, rider, run_no, lap_no)
);

-- ── 3. Row Level Security ────────────────────────────────────────
ALTER TABLE sessions_2d  ENABLE ROW LEVEL SECURITY;
ALTER TABLE lap_times_2d ENABLE ROW LEVEL SECURITY;

-- service_role はRLSをバイパスするので同期スクリプトはservice_keyで実行

-- ── 4. インデックス ──────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_sessions_2d_round   ON sessions_2d(round);
CREATE INDEX IF NOT EXISTS idx_sessions_2d_rider   ON sessions_2d(rider);
CREATE INDEX IF NOT EXISTS idx_sessions_2d_date    ON sessions_2d(date);
CREATE INDEX IF NOT EXISTS idx_lap_times_2d_round  ON lap_times_2d(round);
CREATE INDEX IF NOT EXISTS idx_lap_times_2d_rider  ON lap_times_2d(rider);
CREATE INDEX IF NOT EXISTS idx_lap_times_2d_time   ON lap_times_2d(lap_time_s);

-- ── 完了メッセージ ───────────────────────────────────────────────
DO $$ BEGIN
  RAISE NOTICE '✅ sessions_2d and lap_times_2d tables created successfully!';
END $$;
