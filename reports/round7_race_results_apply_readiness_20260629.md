# ROUND7 race_results apply — 承認前最終チェック（GO待ち）

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-29）。
ブランチ `phase2a-extraction-20260620` / HEAD `e30dd08`（local・未push）。

> [!warning] **これは承認前パッケージ。`--apply` は未実行。**
> Tatsuki が稼働中の Claude Code セッションで明示的に「ROUND7 race_results を apply してよい」と
> GO を出すまで、正本DB（`race_results`）への書込は実行しない。本レポートは GO 判断のための材料。

関連: dry-run レポート `reports/round7_race_results_apply_dry_run_20260629.md` / `CLAUDE.md` §35/§36 /
スクリプト `apply_round7_race_results.py`（既定 dry-run・`--apply` で書込）。

---

## 1. apply 対象 / 非対象

| 区分 | 内容 |
|---|---|
| **対象（書込）** | `race_results` のみ。ROUND7 6 PDF 由来の **74 行**（RACE1 33 / RACE2 33 / FP 2 / QP 2 / WUP1 2 / WUP2 2）。data_scope=`TS24_PRIVATE` |
| **非対象（不変）** | `runs` / `laps` / `lap_suspension` / `pdf_lap_times`（apply 中に before==after を assert・違反で rollback） |
| 反映方式 | 自然キー (round, session_type, rider_num) で UPSERT。既存あれば COALESCE 更新、無ければ INSERT |
| 慣行 | RACE=フルフィールド、FP/QP/WUP=TS24 チーム(#77/#52)のみ（既存 race_results 分布に一致） |

## 2. apply 前 正本DB件数（2026-06-29 実測・`mode=ro`）

| table | before |
|---|---:|
| runs | 275 |
| laps | 1202 |
| lap_suspension | 1202 |
| race_results | 792 |
| pdf_lap_times | 7613 |
| race_results（ROUND7・非COMPANY）| **0** |

## 3. 期待される差分

- ROUND7 既存 `race_results` = **0 行** → dry-run の 74 候補は **全て新規 INSERT** 見込み。
- 期待: **`race_results` 792 → 866（+74）**。他の業務テーブルは不変。
- **apply 直前に実数で再検証**（既存 0 を再確認 → UPSERT の INSERT/UPDATE 内訳をログ出力）。
- Quality Gate（dry-run・再実行済み）: 自然キー重複0 / 既存衝突0 / 必須NULL0 / best_lap_s NULL0 / 物理レンジ外0 /
  型不正0 / RACE best↔lap明細 整合 mismatch0。

## 4. exact command（GO 後のみ）

```bash
python3 apply_round7_race_results.py --apply
```

## 5. 事前バックアップ

- apply 実行時にスクリプトが自動で **正本DB フルコピー**を作成:
  `02_DATABASE/_backup_round7_rr_<YYYYMMDD_HHMMSS>/ts24_unified.db`

## 6. rollback 手順

1. apply は単一トランザクション。**非対象業務テーブル（runs/laps/lap_suspension/pdf_lap_times）が
   before==after でなければ自動 rollback**（コミットしない）。
2. コミット後に問題が判明した場合: バックアップ `_backup_round7_rr_<TS>/ts24_unified.db` を
   `02_DATABASE/ts24_unified.db` へ戻す（手動・Tatsuki 確認のうえ）。
3. INSERT のみ（UPDATE は COALESCE で既存良データを潰さない）ため、ROUND7 行を
   `DELETE FROM race_results WHERE round='ROUND7' AND data_scope='TS24_PRIVATE'` で個別撤去も可能
   （DELETE は別途承認）。

## 7. apply 後の検証手順

1. 正本DB件数 before/after（runs/laps/lap_suspension/pdf_lap_times 不変・race_results +74）。
2. `SELECT COUNT(*) FROM race_results WHERE round='ROUND7'` = 74。
3. `python3 pdf_v2_scratch_gate.py --all`（read-only）→ ROUND7 RACE が真値を得て PASS/WARNING/FAIL 判定に変わるか。
4. `python3 apply_pdf_v2_staging.py`（dry-run）→ ROUND7 RACE PASS が staging 候補に入るか。
5. 結果を `reports/` / `CLAUDE.md` / Obsidian log・handoff・current_state に記録。

## 8. 次に別承認が必要な作業（本 apply には含めない）

1. ROUND7 lap 明細 staging apply（`apply_pdf_v2_staging.py --apply`）。
2. DB Master 再生成（`refresh_db_master_safe.py`）。
3. Supabase audit / sync 判断。
4. Workbench 参照切替（VIEW `race_lap_detail` + `RACE_LAP_SRC`）。
5. origin push。

## 9. Multi-agent operating check（承認前チェック段階）

§20 の 6 エージェント + §1 役割境界に照らした、本 readiness 段階での自己点検。

| 役割 | 承認前チェックでの担当 | 状態 |
|---|---|---|
| Codex / Handoff | Obsidian 最新状態確認・承認前タスク発行・GO 条件（明示承認）の明示 | ✅ |
| Claude Code / Implementation | git/HEAD 再確認・py_compile・dry-run 再実行・readiness パッケージ作成 | ✅ 本タスク |
| Extraction agent（測る） | ROUND7 6 PDF → race_results 候補 74 行（再現確認） | ✅ |
| Quality Gate agent（疑う） | 重複/衝突/NULL/型/物理レンジ/RACE 整合 = 全0、apply 前再検証手順を定義 | ✅ |
| DB Integration agent（保存） | UPSERT・バックアップ・before/after assert・rollback・期待差分 +74 を明文化 | ✅ 設計確定（実行は GO 後） |
| Documentation / Handoff agent | readiness レポート・`CLAUDE.md` §37・Obsidian 更新 | ✅ 本タスク |
| Supervisor（止める） | **明示GOなしの `--apply` を停止**・非対象テーブル不変 assert・2D 不在値作成禁止 | ✅ 停止中 |
| Tatsuki / Final approval | ROUND7 race_results write apply の GO | ⏳ **GO 待ち** |

**所見**: 抽出・品質ゲート・統合設計・文書化・停止条件は成果物上で満たされている。
唯一の未充足は Tatsuki の最終 GO（設計どおり）。GO 受領後に §4 コマンドを実行し §7 で検証する。

## 10. 結論

- **GO 待ち**。技術的準備は完了（dry-run 全 clean・正本DB 現状不変・バックアップ/rollback/検証手順 確定）。
- Tatsuki の明示GO（このセッション内）を受けてのみ `python3 apply_round7_race_results.py --apply` を実行する。

---

## 11. 実行結果（2026-06-29・Tatsuki GO 受領 → apply 済み）

**GO**: Tatsuki が本セッションで「apply してください」と明示 → `python3 apply_round7_race_results.py --apply` を実行。

- **apply**: insert=**74** / update=0。バックアップ `02_DATABASE/_backup_round7_rr_20260629_150354/ts24_unified.db`。
- **正本DB件数 before→after**:
  | table | before | after | 判定 |
  |---|---:|---:|:--:|
  | race_results | 792 | **866**（+74）| ✅ 期待どおり |
  | runs | 275 | 275 | ✅ 不変 |
  | laps | 1202 | 1202 | ✅ 不変 |
  | lap_suspension | 1202 | 1202 | ✅ 不変 |
  | pdf_lap_times | 7613 | 7613 | ✅ 不変 |
- **ROUND7 race_results = 74**（RACE1 33 / RACE2 33 / FP 2 / QP 2 / WUP1 2 / WUP2 2）。best_lap_s NULL=0。
- **Gate 再実行（`--all`）**: 全体 PASS **425→489** / WARNING **1006→942** / FAIL **16（不変）**。
  ROUND7 が真値を獲得し **RACE1=30 PASS/3 WARNING/0 FAIL・RACE2=32 PASS/1 WARNING/0 FAIL**。
  **#77/#52 の RACE1/RACE2 は PASS**（WUP1 も PASS、FP/QP/WUP2 は WARNING＝非RACE 既知ギャップ）。
- **staging dry-run（`apply_pdf_v2_staging.py`）**: 投入予定 **6616→7710 行 / 461 rider-session**。
  **ROUND7 RACE PASS = 1094 行**が staging 候補入り。検証全 clean・業務テーブル不変。
- **次の別承認**: ① ROUND7 lap 明細 staging apply（`apply_pdf_v2_staging.py --apply`）② DB Master 再生成
  ③ Supabase audit/sync ④ Workbench 参照切替 ⑤ origin push。いずれも未実施。
