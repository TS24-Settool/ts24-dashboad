# Result PDF v2 staging apply — 承認前最終チェック（ROUND7 反映後・GO待ち）

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-29）。
ブランチ `phase2a-extraction-20260620` / HEAD `ff643c4`（local・未push）。

> [!warning] **これは承認前パッケージ。`apply_pdf_v2_staging.py --apply` は未実行。**
> ROUND7 `race_results` 反映後の最新状態で、Result PDF v2 lap 明細を正本DB内の新規
> `pdf_lap_times_v2_staging` へ反映してよいかの判断材料。**正本DBへの write apply は GO 受領後のみ。**

関連: `reports/pdf_v2_staging_dry_run_20260627.md` / `reports/pdf_v2_gate_20260629.md` /
`reports/round7_race_results_apply_readiness_20260629.md` / `CLAUDE.md` §32-§37。
スクリプト: `apply_pdf_v2_staging.py`（既定 dry-run・`--apply` で書込）。

---

## 1. 現在地（read-only 再確認・2026-06-29）

- HEAD `ff643c4`。`py_compile`（apply_pdf_v2_staging.py / pdf_v2_scratch_gate.py / pdf_result_extractor_v2.py）PASS。
- 正本DB: `race_results` **866**（ROUND7=**74**・前タスクで反映済）。
- **`pdf_lap_times_v2_staging` は正本DB内に存在しない（=0）** → **新規作成 apply**（既存件数・自然キー衝突・置換対象なし）。
- VIEW `race_lap_detail` も未作成（=0）。
- Gate `--all` 再実行: 全体 PASS **489** / WARNING **942** / FAIL **16**。正本DB業務テーブル **before==after 不変**。

## 2. apply 対象 / 非対象

| 区分 | 内容 |
|---|---|
| **対象（書込）** | 正本DB内 **新規** `pdf_lap_times_v2_staging`。`session_type IN ('RACE1','RACE2')` かつ `gate_status='PASS'` の lap 明細 |
| 規模（dry-run 実測）| **7710 lap 行 / 461 rider-session**（seg 充填 6165）。うち **ROUND7 由来 = 1094 行** |
| **非対象（不変）** | `runs` / `laps` / `lap_suspension` / `race_results` / `pdf_lap_times`、VIEW `race_lap_detail`、Workbench UI/参照切替、DB Master、Supabase、2D derived data |

## 3. 投入前 Quality Gate（dry-run・全 clean）

| 検査 | 結果 | 判定 |
|---|---:|:--:|
| 投入予定 lap 行 | 7710 | – |
| 投入予定 rider-session | 461 | – |
| ROUND7 由来 lap 行 | 1094 | – |
| 自然キー重複（候補内・round,session,rider,lap,date）| 0 | ✅ |
| date NULL | 0 | ✅ |
| lap_time_s NULL | 0 | ✅ |
| 来歴 NULL（source_file/extractor_version/generated_at）| 0 | ✅ |
| 物理レンジ外 valid lap | 0 | ✅ |
| 正本DB業務テーブル（dry-run）| before==after | ✅ |

- 注: seg 充填は 6165/7710（80.0%）。**MISANO(ROUND7) は seg=NULL**（レイアウト不安定のため安全 NULL・§35/§36）。
  ASSEN 系は seg 充填。NULL seg は Workbench セクター分析側で `seg1 IS NOT NULL` により自然に除外され問題なし。

## 4. apply 時 exact command（GO 後のみ）

```bash
python3 apply_pdf_v2_staging.py --apply
```

- 対象 = 既定（`session_type IN ('RACE1','RACE2')` × `gate_status='PASS'`）。
- 動作: 事前フルバックアップ → `CREATE TABLE IF NOT EXISTS pdf_lap_times_v2_staging` + UNIQUE INDEX →
  `INSERT OR REPLACE`（自然キー）→ **runs/laps/lap_suspension/race_results/pdf_lap_times 不変 assert（違反で rollback）** → commit。

## 5. 事前バックアップ

- apply 実行時にスクリプトが正本DB フルコピーを作成:
  `02_DATABASE/_backup_pdf_v2_staging_<YYYYMMDD_HHMMSS>/ts24_unified.db`

## 6. rollback 手順

1. apply は単一トランザクション。**既存業務テーブルが before==after でなければ自動 rollback**（commit しない）。
2. `pdf_lap_times_v2_staging` は **新規テーブル**のため、撤去は `DROP TABLE pdf_lap_times_v2_staging`
   （既存業務テーブルへ影響なし・別途実行）。
3. それでも不足ならバックアップ `_backup_pdf_v2_staging_<TS>/ts24_unified.db` を
   `02_DATABASE/ts24_unified.db` へ戻す（Tatsuki 確認のうえ）。

## 7. apply 後の検証

1. `SELECT COUNT(*) FROM pdf_lap_times_v2_staging` = **7710**。
2. ROUND7 RACE PASS 行 = `SELECT COUNT(*) FROM pdf_lap_times_v2_staging WHERE round='ROUND7' AND session_type IN('RACE1','RACE2')` = **1094**。
3. 自然キー重複 0 / date・lap_time_s・source_file NULL 0。
4. 既存業務テーブル（runs/laps/lap_suspension/race_results/pdf_lap_times）**before==after 不変**。
5. `python3 pdf_v2_scratch_gate.py --all`（read-only）再実行で集計が安定していること。

## 8. 次に別承認が必要な作業（本 apply に含めない）

1. VIEW `race_lap_detail` 作成（`reports/pdf_v2_staging_ddl_20260627.sql` (3)）。
2. Workbench `RaceAnalysisTab` 参照切替（`RACE_LAP_SRC` 定数 → view）。
3. Workbench データ品質表示（PASS/WARNING/FAIL・来歴）。
4. DB Master 再生成（`refresh_db_master_safe.py`）。
5. Supabase audit / sync 判断。
6. origin push。

## 9. Multi-agent operating check（承認前段階）

| 役割 | 承認前チェックでの担当 | 状態 |
|---|---|---|
| Codex / Handoff | Obsidian 最新状態確認・承認前タスク発行・GO 条件明示 | ✅ |
| Claude Code / Implementation | HEAD/py_compile 再確認・gate/staging dry-run 再実行・readiness 作成 | ✅ 本タスク |
| Extraction agent（測る） | `extract_pdf` + `pdf_v2_scratch_gate` 再現（51 PDF・ROUND7 含む） | ✅ |
| Quality Gate agent（疑う） | PASS/WARNING/FAIL・自然キー・NULL・物理レンジ・ROUND7 増分(1094)・既存無回帰 | ✅ 全 clean |
| DB Integration agent（保存） | 新規 staging table・backup・transaction・rollback・before/after assert を明文化（実行は GO 後）| ✅ 設計確定 |
| Supervisor（止める） | **`--apply` 停止**・VIEW/Workbench/DB Master/Supabase/2D を別承認化・既存業務テーブル不変 assert | ✅ 停止中 |
| Documentation / Handoff agent | readiness レポート・`CLAUDE.md` §38・Obsidian 更新 | ✅ 本タスク |
| Tatsuki / Final approval | staging apply の GO | ⏳ **GO 待ち** |

**所見**: 抽出・品質ゲート・統合設計・停止条件・文書化は成果物上で充足。staging は新規テーブルゆえ
既存破壊リスクは構造的に低く（追加のみ・業務テーブル不変 assert・DROP で巻き戻し可）、唯一の未充足は Tatsuki の最終 GO。

## 10. 結論

- **GO 待ち**。技術的準備は完了（dry-run 全 clean・staging 未作成＝新規・業務テーブル不変・backup/rollback/検証手順 確定）。
- Tatsuki の明示GO（このセッション内）を受けてのみ `python3 apply_pdf_v2_staging.py --apply` を実行し、§7 で検証する。
- **注意**: この apply 自体は **Workbench の表示を変えない**（VIEW 作成と参照切替は別承認）。staging テーブルを
  正本DB内に用意するだけで、現行 Workbench/Dashboard の挙動は不変。
