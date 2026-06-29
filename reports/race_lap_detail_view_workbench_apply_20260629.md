# VIEW race_lap_detail 作成 + Workbench 参照切替 実行結果（Tatsuki GO 受領）— 2026-06-29

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-29「VIEW 作成 + Workbench切替 実行ゲート」）。
readiness: `reports/race_lap_detail_view_workbench_readiness_20260629.md`。

## GO

Tatsuki が本セッションで **「GO認証します」** と明示（= `VIEW + Workbench switch GO`）→ 実行。

## 実行直前確認（read-only）
- HEAD `1e0c58b`。`py_compile ts24_workbench.py` PASS。
- `pdf_lap_times_v2_staging`=7710 / VIEW `race_lap_detail` 未作成 / `pdf_lap_times`=7613 / `race_results`=866。readiness 期待値と一致。

## Step 1: 正本DB に VIEW `race_lap_detail` 作成
- 事前バックアップ `02_DATABASE/_backup_view_workbench_20260629_155958/ts24_unified.db`。
- SQL = `reports/pdf_v2_staging_ddl_20260627.sql` (3)（v2 PASS を UNION ALL legacy(NOT EXISTS) で overlay）。
- **検証**:
  | 指標 | 値 | 判定 |
  |---|---:|:--:|
  | `race_lap_detail` total | 12763 | ✅ |
  | source_tag v2 | 7710 | ✅ |
  | source_tag legacy | 5053 | ✅ |
  | 自然キー重複 | 0 | ✅ |
  | ROUND7/RACE1 #77 / #52 | 18 / 18 | ✅ |
  | 非RACE ROUND3/SP | 235（空でない）| ✅ |
  | runs/laps/lap_suspension/race_results/pdf_lap_times | 不変 | ✅ |

## Step 2: Workbench `RaceAnalysisTab` 最小差分（`ts24_workbench.py`）
- クラス定数 **`RACE_LAP_SRC = "race_lap_detail"`** 追加（rollback 時は `"pdf_lap_times"`）。
- `pdf_lap_times` 直接参照 **11 箇所**（メタ4 + rider一覧1 + チャート6）を `{self.RACE_LAP_SRC}` へ置換
  （クエリ論理は不変・参照先のみ切替）。SQL 上の `FROM pdf_lap_times` 残存 = **0**。
- **最小品質表示**: bar2 に `_lbl_quality` を追加し、`_refresh_charts` から `_update_quality()` を呼ぶ。
  現フィルタの (round,session) について `source_tag`(v2/legacy)・件数・rider数・`extractor_version` を 1 行表示
  （ツールチップに v2/legacy の意味）。欠落を 0 埋めしない。

## Step 3: 検証
- `py_compile ts24_workbench.py` PASS。SQL `FROM pdf_lap_times` 残存 0 / `RACE_LAP_SRC` 参照 12（定数1+SQL11）。
- **offscreen スモークテスト（`QT_QPA_PLATFORM=offscreen`）**:
  - `RaceAnalysisTab` 構築 OK（`RACE_LAP_SRC=race_lap_detail`）。
  - ROUND7/RACE1 選択 → `_refresh_charts()`（`_update_quality` 含む）例外なし。
    品質表示 = `lap source: v2 528行/30名  [pdf_result_extractor_v2]`。
  - **ROUND3/RACE1 #77** = VIEW 18 laps（旧 `pdf_lap_times`=0 の欠落解消）/ セクター分析 seg(NOT NULL)=17。
  - **ROUND7/RACE1 #77** = 18 laps（valid 17）/ MISANO は seg=NULL → セクター分析は `seg1 IS NOT NULL` で自然除外・例外なし。
  - 非RACE（ROUND3/SP）は legacy で空にならない。
- 注: #77/#52 は team rider で `JA52`/`DA77` チェックボックス管理（field combo の `_rider_checks` には入らない＝既存仕様）。データは VIEW から取得しチャート描画。
- **GUI 目視（最終）は Tatsuki がローカルで実施**（ヘッドレス不可）: `python3 ts24_workbench.py` →
  Race Analysis で ① ROUND3/RACE1 で DA77(#77) のラップ推移が表示される ② ROUND7/RACE1/RACE2 で #77/#52 が表示される
  ③ 非RACE が空でない ④ 品質表示 `lap source: v2 … / legacy …` が出る、を確認。

## rollback 手順
- VIEW: `DROP VIEW race_lap_detail`（データ無影響）。
- Workbench: `RACE_LAP_SRC` を `"pdf_lap_times"` に戻す、または当該コミットを revert。
- staging table は触らない。フル DB バックアップ `02_DATABASE/_backup_view_workbench_20260629_155958/`。

## 次に別承認が必要な作業（未実施）
1. DB Master 再生成（`refresh_db_master_safe.py`）。
2. Supabase audit / sync 判断。
3. origin push。

## Multi-agent operating check（apply 実行段階）
| 役割 | 担当 | 状態 |
|---|---|---|
| Quality Gate agent | VIEW 件数/重複/非RACE無回帰/ROUND7表示/列互換 | ✅ 全 clean |
| DB Integration agent | VIEW 作成・backup・業務テーブル不変・rollback(DROP VIEW) | ✅ 実行・合格 |
| Workbench / UI agent | `RACE_LAP_SRC` 切替・品質表示・py_compile・offscreen smoke | ✅ |
| Supervisor（止める） | GO 確認・業務テーブル不変・DB Master/Supabase/2D/push を別承認に保持 | ✅ |
| Documentation / Handoff | 本レポート・`CLAUDE.md` §40・Obsidian 更新 | ✅ |
| Tatsuki / Final approval | VIEW + Workbench switch GO | ✅ 受領・実行 |

## 結論
- VIEW 作成 + Workbench 参照切替 + 最小品質表示を実施。正本業務テーブルは不変、staging も不変、VIEW 追加のみ。
- これにより Workbench Race Analysis は **RACE で v2 の完全ラップ明細**（#77 欠落・切断の解消、ROUND7 表示）を参照し、
  非RACE は旧 `pdf_lap_times` にフォールバック（無回帰）。最終 GUI 目視のみ Tatsuki ローカルで残る。
