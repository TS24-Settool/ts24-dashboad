# DB Master 再生成 — 承認前最終チェック（race_lap_detail 反映後・write なし・GO待ち）

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-29）。
ブランチ `phase2a-extraction-20260620` / HEAD `0728fb7`（local・未push）。

> [!warning] **承認前チェックのみ。DB Master 再生成・Excel 書込・置換は未実施。**
> `refresh_db_master_safe.py` に dry-run モードは無く、実行＝実再生成のため、本タスクでは **read-only 確認のみ**で実行しない。

関連: `refresh_db_master_safe.py` / `build_excel_master.py` / `CLAUDE.md` §29 / [[06_WORKBENCH/DB_Master_Refresh]] /
直近 apply: `reports/round7_race_results_apply_readiness_20260629.md` / `pdf_v2_staging_apply_20260629.md` /
`race_lap_detail_view_workbench_apply_20260629.md`。

---

## 1. 現在状態（read-only）

- HEAD `0728fb7`。`ts24_workbench.py` `RaceAnalysisTab` = `RACE_LAP_SRC="race_lap_detail"`。
- 正本DB: `race_results`=866 / `pdf_lap_times_v2_staging`=7710 / VIEW `race_lap_detail`=12763（v2 7710 + legacy 5053・重複0）。
- DB Master: `02_DATABASE/TS24 DB Master.xlsx`（mtime 2026-06-22 10:10・580KB）。テンプレ `TS24 DB Master Back UP.xlsx`。

## 2. ★影響分析（最重要・結論）

`build_excel_master.py` が読むテーブルを確認したところ、**race_results / pdf_lap_times / race_lap_detail /
pdf_lap_times_v2_staging はいずれも参照していない**（grep 各 0 件）。

| DB Master の実ソース | 件数 | 区分 |
|---|---:|---|
| `runs` | 275 | 2D 由来 |
| `laps` | 1202 | 2D 由来 |
| `lap_suspension` | 1202 | 2D 由来 |
| `performance` | 275 | 2D 由来（session_position 含む）|
| `run_tags` | 86 | Workbench |
| `problem_log` | 4 | Workbench |
| `setup_decision_log` | 7 | Workbench |

- **ROUND7 は 2D 由来テーブルに 0 行**（`runs`/`performance` とも ROUND7=0。2D data 未入手）。
- したがって **DB Master を今再生成しても、ROUND7 race_results（+74）や Result PDF v2 lap 明細 / `race_lap_detail` /
  Workbench 表示改善（#77 欠落解消・ROUND7 表示）は DB Master に反映されない**。
- → **本 Result PDF v2 / ROUND7 ラインの作業に DB Master 再生成は不要**。
  - DB Master を再生成すると、現 canonical の **2D 由来 + Workbench 由来シートを最新化**するだけ
    （2D 由来件数は前回ビルド〔Jun 22〕から不変。`run_tags`/`problem_log`/`setup_decision_log` に
    その後の Workbench 追記があればそれが反映される）。
  - ROUND7 race results を Excel にも載せたい場合は、**`build_excel_master.py` に race_results 由来シートを
    新設する別タスク**が必要（本タスク・本承認の範囲外）。

## 3. 実行予定コマンド（GO 後・参考）

```bash
python3 refresh_db_master_safe.py
```

- dry-run 無し。実行すると `build_excel_master.py` を subprocess 起動し `TS24 DB Master.xlsx` を再生成する。

## 4. 対象 workbook / backup / Excel オープン検出（refresh_db_master_safe.py の挙動）

- 対象 workbook: `02_DATABASE/TS24 DB Master.xlsx`（テンプレ `TS24 DB Master Back UP.xlsx`）。
- 事前バックアップ: 既存 xlsx を `02_DATABASE/backups/` へ退避（§29）。
- **Excel オープン検出**: `~$TS24 DB Master.xlsx` ロックファイル + `lsof`。掴まれていれば **exit 2 で中止**
  （`lsof` 不在環境は検出スキップ→保存失敗時に build の exit code で判別）。
- ログ: `05_SCRIPTS/reports/db_master_refresh_<ts>.log`。
- **正本DB は SELECT のみ**（`build_excel_master.py` は DB を読むだけ・業務テーブル書込なし）。

## 5. 更新対象 / 非対象シート

- **更新対象**（9シート構成・DB 由来再生成）: `RUN_LOG` / `LAP_TIMES` / `PERFORMANCE_CORRELATION` /
  `DYNAMICS_ANALYSIS`（DAMPING 10列）/ `LAP_SUSPENSION`(46列) / `PROBLEM_LIBRARY` /
  helper: `WEEKEND_SUMMARY_HELPER` / `SIMILAR_CASES` / `SETUP_EFFECTS`。
- **非対象**（DB Master が読まない＝再生成しても変化なし）: ROUND7 race_results、`pdf_lap_times_v2_staging`、
  VIEW `race_lap_detail`、2D raw / 2D derived / suspension の **ROUND7 分**（2D 不在）。
- Supabase / origin push は本タスク外。

## 6. 実行後検証項目（GO 後）

- 生成物 mtime 更新・サイズ>0・主要6シート存在（`WEEKEND_SUMMARY_HELPER` `SIMILAR_CASES` `SETUP_EFFECTS`
  `RUN_LOG` `DYNAMICS_ANALYSIS` `LAP_SUSPENSION`）。
- **正本DB業務テーブル件数の不変**（`refresh_db_master_safe.py` が `mode=ro` で before/after 照合）。
- バックアップ＋ログ生成を確認。
- （期待）ROUND7 は Excel に現れない（2D 不在のため・上記 §2 のとおり正常）。

## 7. 失敗時の中断条件 / rollback

- Excel オープン中（`~$` or `lsof`）→ exit 2 中止（再生成しない）。
- `build_excel_master.py` 失敗 → その exit code を伝播・xlsx は途中状態にしない。
- 事後検証で主要シート欠落 / 正本DB件数変化 → 失敗扱い。
- rollback: `02_DATABASE/backups/TS24_DB_Master.pre_refresh_<ts>.xlsx` を `TS24 DB Master.xlsx` へ戻す。

## 8. Multi-agent operating check（承認前段階）

| 役割 | 担当 | 状態 |
|---|---|---|
| DB Integration agent | DB Master の実ソーステーブル特定・ROUND7/v2 非反映の確認・件数 | ✅ 確定 |
| Workbench / Excel agent | workbook path・Excel オープン検出・更新対象シート・rollback | ✅ 確認 |
| Quality Gate agent | `race_lap_detail`=12763・重複0・ROUND7/ROUND3 確認・2D 不在確認 | ✅ clean |
| Documentation / Handoff | readiness レポート・`CLAUDE.md` §41・Obsidian 更新 | ✅ 本タスク |
| Supervisor（止める） | DB Master 再生成は GO まで実行しない・dry-run 無しのため未実行・Supabase/push/2D を別承認に保持 | ✅ 停止中 |
| Tatsuki / Final approval | DB Master refresh GO | ⏳ **GO 待ち** |

## 9. 推奨 / 結論

- **技術的には再生成は安全**（DB read-only・backup・Excel オープン検出・事後検証・業務テーブル不変 assert）。
- ただし **本 Result PDF v2 / ROUND7 作業のためには DB Master 再生成は不要**（DB Master はそれらのテーブルを読まない）。
  再生成は「Workbench `setup_decision_log` 等の最新化を Excel に反映したい」場合に意味がある。
- **ROUND7 race results を Excel に載せたい**なら `build_excel_master.py` に race_results 由来シート新設の別タスクが必要。
- 次の GO 文言（再生成を行う場合）: **`DB Master refresh GO`**。

## 10. 次に Tatsuki 明示GOが必要な操作
1. `python3 refresh_db_master_safe.py`（DB Master 再生成）。
2. （任意・別タスク）`build_excel_master.py` に race_results 由来シート新設。
3. Supabase audit / sync 判断。
4. origin push。
