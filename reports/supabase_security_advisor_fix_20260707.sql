-- Supabase Security Advisor fix proposal — 2026-07-07
-- Scope:
--   1) company_* views: set security_invoker=on
--   2) base tables: ensure COMPANY rows are selectable by anon/authenticated
--   3) chassis_geometry: enable RLS with no public policies (deny-all)
--
-- Execution policy:
--   Paste into Supabase SQL Editor only after Tatsuki review.
--   Run PRE-FLIGHT first. Run FIX only after explicit GO.

-- ================================================================
-- PRE-FLIGHT: read-only inspection
-- ================================================================

SELECT
  n.nspname AS schema_name,
  c.relname AS object_name,
  c.relkind AS relkind,
  c.relrowsecurity AS rls_enabled,
  c.relforcerowsecurity AS rls_forced,
  c.reloptions
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
    'sessions',
    'sessions_2d',
    'race_results',
    'lap_times',
    'lap_times_2d',
    'company_sessions',
    'company_sessions_2d',
    'company_race_results',
    'company_lap_times',
    'company_lap_times_2d',
    'chassis_geometry'
  )
ORDER BY c.relkind, c.relname;

SELECT
  table_schema,
  table_name,
  column_name,
  data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('sessions', 'sessions_2d', 'race_results', 'lap_times', 'lap_times_2d')
  AND column_name = 'data_scope'
ORDER BY table_name;

SELECT
  schemaname,
  tablename,
  policyname,
  permissive,
  roles,
  cmd,
  qual,
  with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('sessions', 'sessions_2d', 'race_results', 'lap_times', 'lap_times_2d', 'chassis_geometry')
ORDER BY tablename, policyname;

SELECT 'company_sessions' AS view_name, count(*) AS rows FROM public.company_sessions
UNION ALL SELECT 'company_sessions_2d', count(*) FROM public.company_sessions_2d
UNION ALL SELECT 'company_race_results', count(*) FROM public.company_race_results
UNION ALL SELECT 'company_lap_times', count(*) FROM public.company_lap_times
UNION ALL SELECT 'company_lap_times_2d', count(*) FROM public.company_lap_times_2d;

-- ================================================================
-- FIX: run only after explicit GO
-- ================================================================

BEGIN;

-- Hard stop if a required base table/column is missing. The view change is
-- only safe when invoker RLS has a COMPANY policy path on every base table.
DO $$
DECLARE
  missing_count integer;
BEGIN
  SELECT count(*) INTO missing_count
  FROM (
    VALUES
      ('sessions'),
      ('sessions_2d'),
      ('race_results'),
      ('lap_times'),
      ('lap_times_2d')
  ) AS required(table_name)
  WHERE NOT EXISTS (
    SELECT 1
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = required.table_name
      AND c.column_name = 'data_scope'
  );

  IF missing_count > 0 THEN
    RAISE EXCEPTION 'Missing data_scope on one or more required base tables. Stop and inspect PRE-FLIGHT output.';
  END IF;
END $$;

-- Keep Company Dashboard readable after switching views to invoker security.
-- Existing broader read policies are preserved. These policies only add a
-- narrow COMPANY read path if one is missing.
DO $$
BEGIN
  IF to_regclass('public.sessions') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'sessions' AND column_name = 'data_scope'
     )
     AND NOT EXISTS (
       SELECT 1 FROM pg_policies
       WHERE schemaname = 'public' AND tablename = 'sessions' AND policyname = 'ts24_company_select_sessions'
     ) THEN
    CREATE POLICY ts24_company_select_sessions
      ON public.sessions
      FOR SELECT
      TO anon, authenticated
      USING (data_scope = 'COMPANY');
  END IF;

  IF to_regclass('public.sessions_2d') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'sessions_2d' AND column_name = 'data_scope'
     )
     AND NOT EXISTS (
       SELECT 1 FROM pg_policies
       WHERE schemaname = 'public' AND tablename = 'sessions_2d' AND policyname = 'ts24_company_select_sessions_2d'
     ) THEN
    CREATE POLICY ts24_company_select_sessions_2d
      ON public.sessions_2d
      FOR SELECT
      TO anon, authenticated
      USING (data_scope = 'COMPANY');
  END IF;

  IF to_regclass('public.race_results') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'race_results' AND column_name = 'data_scope'
     )
     AND NOT EXISTS (
       SELECT 1 FROM pg_policies
       WHERE schemaname = 'public' AND tablename = 'race_results' AND policyname = 'ts24_company_select_race_results'
     ) THEN
    CREATE POLICY ts24_company_select_race_results
      ON public.race_results
      FOR SELECT
      TO anon, authenticated
      USING (data_scope = 'COMPANY');
  END IF;

  IF to_regclass('public.lap_times') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'lap_times' AND column_name = 'data_scope'
     )
     AND NOT EXISTS (
       SELECT 1 FROM pg_policies
       WHERE schemaname = 'public' AND tablename = 'lap_times' AND policyname = 'ts24_company_select_lap_times'
     ) THEN
    CREATE POLICY ts24_company_select_lap_times
      ON public.lap_times
      FOR SELECT
      TO anon, authenticated
      USING (data_scope = 'COMPANY');
  END IF;

  IF to_regclass('public.lap_times_2d') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'lap_times_2d' AND column_name = 'data_scope'
     )
     AND NOT EXISTS (
       SELECT 1 FROM pg_policies
       WHERE schemaname = 'public' AND tablename = 'lap_times_2d' AND policyname = 'ts24_company_select_lap_times_2d'
     ) THEN
    CREATE POLICY ts24_company_select_lap_times_2d
      ON public.lap_times_2d
      FOR SELECT
      TO anon, authenticated
      USING (data_scope = 'COMPANY');
  END IF;
END $$;

ALTER VIEW IF EXISTS public.company_sessions SET (security_invoker = on);
ALTER VIEW IF EXISTS public.company_sessions_2d SET (security_invoker = on);
ALTER VIEW IF EXISTS public.company_race_results SET (security_invoker = on);
ALTER VIEW IF EXISTS public.company_lap_times SET (security_invoker = on);
ALTER VIEW IF EXISTS public.company_lap_times_2d SET (security_invoker = on);

ALTER TABLE IF EXISTS public.chassis_geometry ENABLE ROW LEVEL SECURITY;

COMMIT;

-- ================================================================
-- POST-FLIGHT: verification
-- ================================================================

SELECT
  c.relname AS view_name,
  c.reloptions
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
    'company_sessions',
    'company_sessions_2d',
    'company_race_results',
    'company_lap_times',
    'company_lap_times_2d'
  )
ORDER BY c.relname;

SELECT
  schemaname,
  tablename,
  policyname,
  roles,
  cmd,
  qual
FROM pg_policies
WHERE schemaname = 'public'
  AND policyname IN (
    'ts24_company_select_sessions',
    'ts24_company_select_sessions_2d',
    'ts24_company_select_race_results',
    'ts24_company_select_lap_times',
    'ts24_company_select_lap_times_2d'
  )
ORDER BY tablename, policyname;

SELECT
  n.nspname AS schema_name,
  c.relname AS table_name,
  c.relrowsecurity AS rls_enabled,
  c.relforcerowsecurity AS rls_forced
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname = 'chassis_geometry';

SELECT 'company_sessions' AS view_name, count(*) AS rows FROM public.company_sessions
UNION ALL SELECT 'company_sessions_2d', count(*) FROM public.company_sessions_2d
UNION ALL SELECT 'company_race_results', count(*) FROM public.company_race_results
UNION ALL SELECT 'company_lap_times', count(*) FROM public.company_lap_times
UNION ALL SELECT 'company_lap_times_2d', count(*) FROM public.company_lap_times_2d;

-- ================================================================
-- ROLLBACK: run only if dashboard behavior regresses
-- ================================================================

-- BEGIN;
-- ALTER VIEW IF EXISTS public.company_sessions RESET (security_invoker);
-- ALTER VIEW IF EXISTS public.company_sessions_2d RESET (security_invoker);
-- ALTER VIEW IF EXISTS public.company_race_results RESET (security_invoker);
-- ALTER VIEW IF EXISTS public.company_lap_times RESET (security_invoker);
-- ALTER VIEW IF EXISTS public.company_lap_times_2d RESET (security_invoker);
-- DROP POLICY IF EXISTS ts24_company_select_sessions ON public.sessions;
-- DROP POLICY IF EXISTS ts24_company_select_sessions_2d ON public.sessions_2d;
-- DROP POLICY IF EXISTS ts24_company_select_race_results ON public.race_results;
-- DROP POLICY IF EXISTS ts24_company_select_lap_times ON public.lap_times;
-- DROP POLICY IF EXISTS ts24_company_select_lap_times_2d ON public.lap_times_2d;
-- ALTER TABLE IF EXISTS public.chassis_geometry DISABLE ROW LEVEL SECURITY;
-- COMMIT;

-- ================================================================
-- OPTIONAL CLEANUP: not part of this fix
-- ================================================================

-- If Tatsuki separately approves destructive cleanup after confirming no
-- dashboard/repo dependency, chassis_geometry can be dropped later:
--
-- DROP TABLE IF EXISTS public.chassis_geometry;
