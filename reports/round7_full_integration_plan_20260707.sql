-- =====================================================================
-- Round7 full integration — provisional clear + reference DDL/checks
-- 生成: 2026-07-07  Phase A（readiness）／※このSQLは未実行・レビュー用
-- 正本: 02_DATABASE/ts24_unified.db
-- 実行は「Round7 final integration GO」受領後・§下記手順のクリア段のみ
-- provisional_event_key = '20260612-ROUND7-JA52'（runs/laps/lap_suspension_provisional 共通・実測）
-- =====================================================================

-- ---------------------------------------------------------------------
-- [0] 事前確認（mode=ro 想定・DELETE前に必ず件数一致を確認）
--   期待: 12 / 79 / 79
-- ---------------------------------------------------------------------
SELECT 'runs_prov'  AS t, count(*) FROM runs_provisional            WHERE provisional_event_key='20260612-ROUND7-JA52';
SELECT 'laps_prov'  AS t, count(*) FROM laps_provisional            WHERE provisional_event_key='20260612-ROUND7-JA52';
SELECT 'susp_prov'  AS t, count(*) FROM lap_suspension_provisional  WHERE provisional_event_key='20260612-ROUND7-JA52';

-- ---------------------------------------------------------------------
-- [1] provisional クリア（cutover 後・Workbench final 確認の後に実行）
--   子 → 親 の順（FK 無しでも論理順を厳守）。event_key 単位で限定。
--   ※ FP 分も含め ROUND7 MISANO の provisional 12/79/79 を一括削除。
--     final（正本 runs/laps/lap_suspension）へ昇格済であることを [pre] で確認済のこと。
-- ---------------------------------------------------------------------
DELETE FROM lap_suspension_provisional WHERE provisional_event_key='20260612-ROUND7-JA52';
DELETE FROM laps_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
DELETE FROM runs_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';

-- ---------------------------------------------------------------------
-- [2] クリア後確認（期待: すべて 0）
-- ---------------------------------------------------------------------
SELECT 'runs_prov_after' AS t, count(*) FROM runs_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
SELECT 'laps_prov_after' AS t, count(*) FROM laps_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
SELECT 'susp_prov_after' AS t, count(*) FROM lap_suspension_provisional WHERE provisional_event_key='20260612-ROUND7-JA52';

-- ---------------------------------------------------------------------
-- [3] cutover 後の正本 検証クエリ（DELETE ではない・参照）
--   期待（scratch と一致）:
--     runs   ROUND7 = 13 / laps ROUND7 = 77 / lap_suspension ROUND7 = 77
--     runs   全体   = 286 / laps 全体 = 1279（既存 1202 不変 + ROUND7 77）
--     NA_MISANO_RACE1_JA52_R1 / NA_MISANO_RACE2_JA52_R1 は消滅（ROUND7 R2 へ再割当）
-- ---------------------------------------------------------------------
SELECT 'runs_R7'  AS t, count(*) FROM runs           WHERE round='ROUND7';
SELECT 'laps_R7'  AS t, count(*) FROM laps l JOIN runs r ON l.run_id=r.run_id WHERE r.round='ROUND7';
SELECT 'susp_R7'  AS t, count(*) FROM lap_suspension WHERE round='ROUND7';
SELECT 'runs_all' AS t, count(*) FROM runs;
SELECT 'laps_all' AS t, count(*) FROM laps;
SELECT 'NA_MISANO_残存(期待0)' AS t, count(*) FROM runs
  WHERE run_id IN ('NA_MISANO_RACE1_JA52_R1','NA_MISANO_RACE2_JA52_R1');

-- ---------------------------------------------------------------------
-- [4] Rollback（provisional 復元が必要な場合）
--   最終手段 = cutover 直前フルバックアップ（_backup_* / backups/）からDB丸ごと復元。
--   provisional のみ復元する場合はバックアップDBの該当3テーブル行を event_key 限定で
--   INSERT ... SELECT で戻す（DDLは既存・CREATE不要）。手動レビュー必須のため雛形のみ:
--   ATTACH '（バックアップ）ts24_unified.db' AS bk;
--   INSERT INTO runs_provisional           SELECT * FROM bk.runs_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
--   INSERT INTO laps_provisional           SELECT * FROM bk.laps_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
--   INSERT INTO lap_suspension_provisional SELECT * FROM bk.lap_suspension_provisional WHERE provisional_event_key='20260612-ROUND7-JA52';
--   DETACH bk;

-- =====================================================================
-- 注意: DDL 変更は不要（provisional 3テーブルは §57 で固定済・正本 runs/laps/
--       lap_suspension は build_master_db.py が SCHEMA から再生成）。本SQLに CREATE/ALTER は含めない。
-- =====================================================================
