-- ================================================================
-- TS24 — Supabase オンライン肥大の是正（Part B-2）
-- 生成: 2026-06-05 / Claude Code
--
-- 背景:
--   sync_to_supabase.py が conflict_col="id"（payload に id 無し）で
--   upsert していたため、再 sync のたびに全行が INSERT され、オンラインが
--   local の 5〜13 倍に肥大した。round 空間・rider 形式は local と一致して
--   おり、オンライン固有の正当データは無い（COMPANY スコープ含め全て local
--   にも存在）。余剰は旧命名（UNK_ / PHILLIPISLAND 二重L / 日付プレフィクス）
--   の残骸。
--
-- 方針:
--   各テーブルを TRUNCATE し、自然キーに UNIQUE インデックスを張ってから
--   local（ts24_unified.db）を権威源として再 sync する。これで online==local
--   に確実収束し、以降の sync は idempotent になる。
--
-- ⚠️ 破壊的操作。実行前にバックアップ取得済み:
--   02_DATABASE/_supabase_backup_20260605-185421/  (112,358 行)
--
-- 実行手順:
--   1. このファイルを Supabase Studio → SQL Editor に貼り付けて Run
--   2. 成功後 Claude Code が `python3 05_SCRIPTS/sync_to_supabase.py` を実行
--   3. online件数が下表のローカル値と一致することを確認
--
--   テーブル            再sync後の期待件数(=local)
--   race_results        742
--   lap_times           7613
--   sessions            130
--   sessions_2d         276
--   lap_times_2d        956
--   chassis_geometry    230
-- ================================================================

BEGIN;

-- ── 1. 肥大テーブルを空にする ────────────────────────────────
-- RESTART IDENTITY で id シーケンスもリセット。
-- FK 参照エラーが出る場合のみ各行を CASCADE 検討（通常これらは leaf）。
TRUNCATE TABLE public.race_results     RESTART IDENTITY;
TRUNCATE TABLE public.lap_times        RESTART IDENTITY;
TRUNCATE TABLE public.sessions         RESTART IDENTITY;
TRUNCATE TABLE public.sessions_2d      RESTART IDENTITY;
TRUNCATE TABLE public.lap_times_2d     RESTART IDENTITY;
TRUNCATE TABLE public.chassis_geometry RESTART IDENTITY;

-- ── 2. 自然キーに UNIQUE インデックスを作成 ──────────────────
-- NULLS NOT DISTINCT (PG15+) で NULL を含むキーも重複扱いにし、
-- 将来の sync で position=NULL 等が二重登録されないようにする。

-- race_results : 1レース1ライダー1結果
CREATE UNIQUE INDEX IF NOT EXISTS race_results_natkey
  ON public.race_results (round_no, circuit, session_type, rider_no, position)
  NULLS NOT DISTINCT;

-- lap_times : ラップ単位（PDF 由来）
CREATE UNIQUE INDEX IF NOT EXISTS lap_times_natkey
  ON public.lap_times (round_id, circuit, session_type, rider_num, lap_no)
  NULLS NOT DISTINCT;

-- sessions : 既に session_id が自然キー。明示的に張り直す（存在すれば無視）
CREATE UNIQUE INDEX IF NOT EXISTS sessions_natkey
  ON public.sessions (session_id);

-- sessions_2d : 2D/MES のラン単位
CREATE UNIQUE INDEX IF NOT EXISTS sessions_2d_natkey
  ON public.sessions_2d (round, circuit, session_type, rider, run_no)
  NULLS NOT DISTINCT;

-- lap_times_2d : 2D/MES のラップ単位
CREATE UNIQUE INDEX IF NOT EXISTS lap_times_2d_natkey
  ON public.lap_times_2d (round, circuit, session_type, rider, run_no, lap_no)
  NULLS NOT DISTINCT;

-- chassis_geometry : ラン+シャーシラベル単位
CREATE UNIQUE INDEX IF NOT EXISTS chassis_geometry_natkey
  ON public.chassis_geometry (rider, circuit, session, run_no, chassis_label)
  NULLS NOT DISTINCT;

COMMIT;

-- ── 3. 確認用クエリ（任意） ──────────────────────────────────
-- 実行後すべて 0 行のはず（再 sync 前）:
--   SELECT 'race_results' t, count(*) FROM public.race_results
--   UNION ALL SELECT 'lap_times', count(*) FROM public.lap_times
--   UNION ALL SELECT 'sessions', count(*) FROM public.sessions
--   UNION ALL SELECT 'sessions_2d', count(*) FROM public.sessions_2d
--   UNION ALL SELECT 'lap_times_2d', count(*) FROM public.lap_times_2d
--   UNION ALL SELECT 'chassis_geometry', count(*) FROM public.chassis_geometry;
