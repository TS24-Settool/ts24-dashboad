-- ================================================================
-- TS24 — Supabase UNIQUE キーに date を追加（DB再構築 2026-06-18）
-- 生成: 2026-06-18 / Claude Code
--
-- 背景:
--   DB再構築で run_id が {date}_{round}_{circuit}_{session}_{rider}_R{run}
--   となり、同一 round 番号がシーズンを跨いで再利用される
--   (例: ROUND1 PHILLIP ISLAND が 2025-02-21 と 2026-02-20 の両方に存在)。
--   旧 natural key (date 無し) では sessions_2d / lap_times_2d で衝突し、
--   sync 時に PostgREST が 21000 "ON CONFLICT cannot affect row a second
--   time" を返す（同一バッチ内に同一キーの2行が含まれるため）。
--
-- 方針:
--   sessions_2d / lap_times_2d の UNIQUE インデックスに date を追加して
--   シーズンを区別する。両テーブルを TRUNCATE してクリーンに再 sync し、
--   online==local に確実収束させる。他テーブル(race_results/lap_times)は
--   2025 ラウンドが ROUND11/12 で 2026 と重複しないため変更不要。
--
-- ⚠️ 破壊的操作(対象2テーブルのみ)。前提: sessions_2d / lap_times_2d に
--    date 列が存在すること(既存 sync が date を送っているため通常存在)。
--
-- 実行手順:
--   1. このファイルを Supabase Studio → SQL Editor に貼り付けて Run
--   2. 成功後 Claude Code が `python3 05_SCRIPTS/sync_to_supabase.py` を実行
--   3. online件数が下記のローカル値と一致することを確認
--        sessions_2d   246
--        lap_times_2d  1134
-- ================================================================

BEGIN;

-- ── 1. 対象2テーブルを空にする ──────────────────────────────
TRUNCATE TABLE public.sessions_2d  RESTART IDENTITY;
TRUNCATE TABLE public.lap_times_2d RESTART IDENTITY;

-- ── 2. 旧 UNIQUE インデックスを破棄 ─────────────────────────
DROP INDEX IF EXISTS public.sessions_2d_natkey;
DROP INDEX IF EXISTS public.lap_times_2d_natkey;

-- ── 3. date を含む新 UNIQUE インデックスを作成 ──────────────
-- NULLS NOT DISTINCT (PG15+) で NULL を含むキーも重複扱い。
CREATE UNIQUE INDEX sessions_2d_natkey
  ON public.sessions_2d (round, circuit, session_type, rider, run_no, date)
  NULLS NOT DISTINCT;

CREATE UNIQUE INDEX lap_times_2d_natkey
  ON public.lap_times_2d (round, circuit, session_type, rider, run_no, lap_no, date)
  NULLS NOT DISTINCT;

COMMIT;

-- ── 4. 確認用クエリ（任意・実行後は 0 行のはず） ────────────
--   SELECT 'sessions_2d' t, count(*) FROM public.sessions_2d
--   UNION ALL SELECT 'lap_times_2d', count(*) FROM public.lap_times_2d;
