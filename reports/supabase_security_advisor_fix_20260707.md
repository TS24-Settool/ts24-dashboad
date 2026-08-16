# Supabase Security Advisor Fix Plan — 2026-07-07

## 結論

対象は Supabase 側の静的 lint 6件で、DBeaver や local SQLite とは無関係。

推奨対応は以下。

1. `company_*` 5 View は `security_invoker = on` に変更する。
2. その前提として、base 5テーブルに COMPANY 行を読める SELECT policy を冪等追加する。
3. `chassis_geometry` は DROP ではなく、まず RLS 有効化 + policy なしの deny-all にする。
4. 修正は Tatsuki が Supabase SQL Editor で実行する。本環境から本番 DDL は実行しない。

## 背景

Obsidian `07_SUPABASE/2026-07-07_security_advisor_findings.md` に記録された Error 6件:

| issue | entity | 対応 |
|---|---|---|
| Security Definer View | `company_sessions` | `security_invoker=on` |
| Security Definer View | `company_sessions_2d` | `security_invoker=on` |
| Security Definer View | `company_race_results` | `security_invoker=on` |
| Security Definer View | `company_lap_times` | `security_invoker=on` |
| Security Definer View | `company_lap_times_2d` | `security_invoker=on` |
| RLS Disabled in Public | `chassis_geometry` | RLS enable / deny-all |

`company_*` View は 2026-05-20 Company Data Integration で作成された Dashboard 用 view。`data_scope='COMPANY'` のみを返す設計だが、View 作成時に `security_invoker` が未指定だったため、Supabase linter が Security Definer View として検出している。

`chassis_geometry` は 2026-06-18 以降 `sync_to_supabase.py` v3 の対象外。現行 local 正本からも外れており、Supabase 側に残った孤児テーブル。

## 方針判断

### company_* View

`security_invoker=on` を採用する。これにより View は呼び出し元ロールの RLS/policy を尊重する。

リスクは、base table の RLS policy が不足している場合に Company Dashboard が空になること。これを避けるため、修正SQLでは `anon` / `authenticated` に対して `data_scope = 'COMPANY'` の SELECT policy を追加する。既存の read-all policy がある場合も壊さない。

### chassis_geometry

推奨は DROP ではなく RLS enable deny-all。

理由:
- Advisor Error は解消できる。
- 破壊的でない。
- 現行 pipeline からは未使用だが、古いDashboardや確認SQLが残っていた場合も即時破壊しない。
- service_role は通常 RLS を bypass するため、管理者確認は可能。

DROP は二段階目の任意cleanupとして扱う。実行する場合は、Supabase上で件数確認と dashboard / repo grep 確認後に別GOで行う。

## SQL成果物

実行候補:

- `05_SCRIPTS/reports/supabase_security_advisor_fix_20260707.sql`

構成:

1. preflight inspection query
2. fix transaction
3. postflight verification query
4. optional DROP block（コメントアウト）

## 実行前確認

Supabase SQL Editor で SQL の `PRE-FLIGHT` セクションだけ先に実行し、以下を確認する。

- base 5テーブルが存在する。
- `data_scope` 列が base 5テーブルに存在する。
- `company_*` 5 View が存在する。
- `chassis_geometry` が存在する場合、RLS が disabled である。
- 既存 policy に Dashboard を壊すような deny-only 構成がない。

## 実行後確認

1. Supabase Security Advisor の `Rerun linter` で Error 6件が消えること。
2. SQL の `POST-FLIGHT` セクションで以下を確認する。
   - `company_*` View の `security_invoker` が `on`
   - base 5テーブルに `ts24_company_select_*` policy が存在
   - `chassis_geometry` の `relrowsecurity` が `true`
3. Company Dashboard で主要画面がエラーなく開くこと。
4. `company_*` が0件の場合は空表示が正常。エラーや権限エラーはNG。

## Rollback

View側:

```sql
ALTER VIEW public.company_sessions RESET (security_invoker);
ALTER VIEW public.company_sessions_2d RESET (security_invoker);
ALTER VIEW public.company_race_results RESET (security_invoker);
ALTER VIEW public.company_lap_times RESET (security_invoker);
ALTER VIEW public.company_lap_times_2d RESET (security_invoker);
```

追加policy側:

```sql
DROP POLICY IF EXISTS ts24_company_select_sessions ON public.sessions;
DROP POLICY IF EXISTS ts24_company_select_sessions_2d ON public.sessions_2d;
DROP POLICY IF EXISTS ts24_company_select_race_results ON public.race_results;
DROP POLICY IF EXISTS ts24_company_select_lap_times ON public.lap_times;
DROP POLICY IF EXISTS ts24_company_select_lap_times_2d ON public.lap_times_2d;
```

`chassis_geometry` 側:

```sql
ALTER TABLE IF EXISTS public.chassis_geometry DISABLE ROW LEVEL SECURITY;
```

ただし `chassis_geometry` の rollback は Advisor Error を再発させるため、Dashboardに影響が出た場合のみ使用する。

## Codeへの実施指示

Code は本番SupabaseへDDL実行しない。やることは以下に限定する。

1. 本レポートとSQLをレビューする。
2. `PRE-FLIGHT` の結果をTatsukiが貼り付けた場合、結果を読んで `FIX` 実行可否を判定する。
3. 実行可の場合、Tatsukiに `supabase security advisor fix GO` で SQL Editor 実行してよいか確認する。
4. 実行後、`POST-FLIGHT` と Security Advisor rerun の結果を確認し、Obsidianへ記録する。
5. `chassis_geometry DROP` は別タスク・別GO。今回の標準修正では実行しない。
