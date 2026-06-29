# Result PDF v2 staging apply 実行結果（Tatsuki GO 受領）— 2026-06-29

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-29「staging write apply 実行ゲート」）。
ブランチ `phase2a-extraction-20260620`。readiness: `reports/pdf_v2_staging_apply_readiness_20260629.md`。

## GO

Tatsuki が本セッションで **「GO の承認します」** と明示 → `python3 apply_pdf_v2_staging.py --apply` を実行。

## apply 直前確認（read-only）

- HEAD `64cc9af`。py_compile（apply_pdf_v2_staging / pdf_v2_scratch_gate / pdf_result_extractor_v2）PASS。
- `pdf_lap_times_v2_staging` 正本DB内 **未作成（=0）** → 新規作成 apply。
- dry-run: 投入予定 **7710 行 / 461 rider-session**・検査全 clean・業務テーブル不変。readiness 期待値と一致。

## apply 実行

- command: `python3 apply_pdf_v2_staging.py --apply`
- **バックアップ**: `02_DATABASE/_backup_pdf_v2_staging_20260629_153524/ts24_unified.db`
- 結果ログ: `apply 完了: 7710 行（業務テーブル不変・バックアップ=...）`

## apply 後検証

| 検証 | 結果 | 判定 |
|---|---:|:--:|
| `pdf_lap_times_v2_staging` 件数 | **7710** | ✅ 期待一致 |
| ROUND7 RACE PASS 行 | **1094** | ✅ 期待一致 |
| 自然キー重複 | 0 | ✅ |
| date / lap_time_s / source_file NULL | 0 | ✅ |
| `runs` | 275 | ✅ 不変 |
| `laps` | 1202 | ✅ 不変 |
| `lap_suspension` | 1202 | ✅ 不変 |
| `race_results` | 866 | ✅ 不変 |
| `pdf_lap_times` | 7613 | ✅ 不変 |
| Gate `--all` 再実行 | PASS489 / WARNING942 / FAIL16 | ✅ 安定 |
| VIEW `race_lap_detail` | 未作成（=0）| ✅ 別承認 |
| Workbench `RaceAnalysisTab` 参照元 | `pdf_lap_times` のまま（11箇所・未変更）| ✅ **表示不変** |

→ **既存業務テーブルは完全に不変**。新規 `pdf_lap_times_v2_staging`（7710行・追加のみ）を作成。
**Workbench / Dashboard の表示は変わらない**（VIEW 作成と参照切替は別承認のため）。

## 反映内容

- `pdf_lap_times_v2_staging`: RACE1/RACE2 かつ Gate `gate_status='PASS'` の v2 lap 明細のみ。
  ROUND1〜6/11/12 + ROUND7 の RACE。MISANO(ROUND7) は seg=NULL（安全）・lap_time/best/speed/is_cancelled/is_pit は有効。
- 来歴列（source_file / extractor_version / generated_at / gate_status）付き。

## rollback（必要時）

- 新規テーブルゆえ `DROP TABLE pdf_lap_times_v2_staging`（既存業務テーブル無影響）。
- または `02_DATABASE/_backup_pdf_v2_staging_20260629_153524/ts24_unified.db` から差し戻し。

## 次に別承認が必要な作業（未実施）

1. VIEW `race_lap_detail` 作成（`reports/pdf_v2_staging_ddl_20260627.sql` (3)）。
2. Workbench `RaceAnalysisTab` 参照切替（`RACE_LAP_SRC` 定数 → view）。
3. Workbench データ品質表示（PASS/WARNING/FAIL・来歴）。
4. DB Master 再生成 / Supabase audit・sync / origin push。

## Multi-agent operating check（apply 実行段階）

| 役割 | 担当 | 状態 |
|---|---|---|
| Codex / Handoff | 実行ゲート発行・GO 条件明示 | ✅ |
| Claude Code / Implementation | apply 直前確認・`--apply` 実行・検証・記録・コミット | ✅ |
| Extraction agent | v2 extractor / scratch Gate 再現 | ✅ |
| Quality Gate agent | apply 前後の重複/NULL/件数/業務不変/gate 再実行 | ✅ 全 clean |
| DB Integration agent | 新規 staging 作成・backup・before==after assert・rollback 手順 | ✅ 実行・合格 |
| Supervisor（止める） | 業務テーブル不変 assert・VIEW/Workbench/DB Master/Supabase/2D/push を別承認に保持 | ✅ |
| Documentation / Handoff | 本レポート・`CLAUDE.md`・Obsidian 更新 | ✅ |
| Tatsuki / Final approval | staging apply GO | ✅ 受領・実行 |
