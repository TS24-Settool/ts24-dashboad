# VIEW race_lap_detail + Workbench 参照切替 — 承認前最終チェック（write/UI変更なし・GO待ち）

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-29）。
ブランチ `phase2a-extraction-20260620` / HEAD `258c141`（local・未push）。

> [!warning] **承認前チェックのみ。正本DBへの VIEW 作成・`ts24_workbench.py` 編集・UI 変更は未実施。**
> scratch コピー（`/tmp/ts24_view_test.db`）上で VIEW overlay を検証しただけで、正本DB（`02_DATABASE/ts24_unified.db`）は不変。

関連: `reports/pdf_v2_staging_apply_20260629.md` / `reports/pdf_v2_staging_ddl_20260627.sql` /
`reports/pdf_v2_canonical_staging_plan_20260627.md`（§3b 案A）/ `CLAUDE.md` §33c/§38e。

---

## 1. 現状（read-only 確認）

- HEAD `258c141`。`race_results`=866 / `pdf_lap_times`=7613（旧・不変）/ `pdf_lap_times_v2_staging`=**7710**（ROUND7=1094）。
- VIEW `race_lap_detail` は正本DBに **未作成（=0）**。`RaceAnalysisTab` は `pdf_lap_times` を直接参照（11 箇所）・`ts24_workbench.py` 未変更。

## 2. 対象 / 非対象

| 区分 | 内容 |
|---|---|
| **VIEW 作成対象（GO後）** | 正本DB内 **新規 VIEW `race_lap_detail`**（`pdf_v2_staging_ddl_20260627.sql` (3) の overlay 案）|
| **Workbench 変更対象（GO後）** | `ts24_workbench.py` `RaceAnalysisTab`: クラス定数 `RACE_LAP_SRC` 追加 + `pdf_lap_times` リテラル 11 箇所を `{self.RACE_LAP_SRC}` 化 + 品質表示の最小追加 |
| **非対象（不変）** | `pdf_lap_times` / `pdf_lap_times_v2_staging` / `race_results` / `runs` / `laps` / `lap_suspension`、DB Master、Supabase、2D、origin push |

## 3. scratch 検証結果（`/tmp/ts24_view_test.db`＝正本DBのコピー）

VIEW 定義: `pdf_v2_staging_ddl_20260627.sql` (3) をそのまま採用可能（scratch で作成・全クエリ成功）。

| 指標 | 値 |
|---|---:|
| `pdf_lap_times`（旧・直接）| 7613 行 |
| `race_lap_detail`（VIEW）| **12763 行** = v2 7710 + legacy 5053 |
| VIEW source_tag = v2 | 7710 行 / 461 rider-session |
| VIEW source_tag = legacy | 5053 行 / 723 rider-session（v2 PASS に置換されなかった旧行）|
| 自然キー(round,session,rider,lap,date) 重複 | **0** |

### 3a. RACE は v2 優先（欠落・切断の解消）
| session/rider | 旧 `pdf_lap_times` | VIEW | source |
|---|---:|---:|---|
| ROUND3/RACE1 #52 | 8（切断）| **18** | v2 |
| ROUND3/RACE1 #77 | 0（欠落）| **18** | v2 |

### 3b. 非RACE は legacy フォールバック（無回帰・空にならない）
| session | 旧 | VIEW | 判定 |
|---|---:|---:|:--:|
| ROUND3/SP | 235 | 235 | ✅ 不変（legacy）|
| ROUND5/QP | 0 | 0 | ✅ 旧も0（v2非対象・追加せず）|

### 3c. ROUND7 RACE #77/#52 表示（v2）
| round/session | rider | VIEW laps | source |
|---|---:|---:|---|
| ROUND7/RACE1 | #77 | 18 | v2 |
| ROUND7/RACE1 | #52 | 18 | v2 |
| ROUND7/RACE2 | #77 | 18 | v2 |
| ROUND7/RACE2 | #52 | 18 | v2 |

### 3d. 列互換
VIEW は `RaceAnalysisTab` が使う列を全て提供: `round, session_type, rider_num, rider_name, lap_no,
lap_time_s, seg1..seg4, is_outlap, is_pit, is_cancelled`（＋ `speed, local_time, source_file,
extractor_version, gate_status, source_tag`）。MISANO(ROUND7) は seg=NULL（セクター分析は `seg1 IS NOT NULL` で自然除外）。

## 4. 旧 `pdf_lap_times` と VIEW の差分（要点）

- VIEW は **RACE の v2 PASS rider を完全ラップで上書き**（旧の切断/欠落を解消）し、それ以外（非RACE 全部 + RACE の
  非PASS rider）は **旧行をそのまま温存**（NOT EXISTS フォールバック）。
- 行数増（7613→12763）は ① RACE v2 が旧より長いラップ列（切断解消）② ROUND7 RACE が新規。**重複・欠落は無し**。
- 旧で見えていた行が消えるケースは無い（v2 PASS で置換された rider のみ旧行が隠れ、より完全な v2 行に入れ替わる）。

## 5. Workbench 変更案（最小差分・GO後・今回未編集）

- `RaceAnalysisTab` クラスに定数追加:
  ```python
  RACE_LAP_SRC = "race_lap_detail"   # 旧: "pdf_lap_times"。rollback 時は "pdf_lap_times" に戻す
  ```
- `pdf_lap_times` リテラル **11 箇所**（L4935/4937/4957/4960/4984/5132/5210/5283/5378/5448/5567）を
  f-string `{self.RACE_LAP_SRC}` に置換（クエリ論理は不変・テーブル名のみ差し替え）。
- **品質表示（最小案）**: フィルタ中 (round,session) のヘッダ近傍に 1 行:
  `lap source: v2 PASS n件 / legacy m件 ・ rider欠落/FAIL: …`。
  行詳細・ツールチップに `source_tag`(v2/legacy) / `gate_status` / `source_file` / `extractor_version` を表示。
  → 既存レイアウトに 1 ラベル追加程度の小改修に留める（過剰改修しない）。

## 6. 想定 exact commands / files（GO後）

```sql
-- 1) 正本DB に VIEW 作成（reports/pdf_v2_staging_ddl_20260627.sql (3) と同一）
CREATE VIEW IF NOT EXISTS race_lap_detail AS ... ;  -- overlay: v2 PASS UNION ALL legacy(NOT EXISTS)
```
- 2) `ts24_workbench.py`: `RACE_LAP_SRC` 定数追加 + 11 リテラル置換 + 品質表示。
- 3) GUI スモークテスト（ヘッドレス不可・Tatsuki ローカル実施）。

## 7. rollback 手順

- VIEW: `DROP VIEW race_lap_detail`（テーブルではないのでデータ無影響）。
- Workbench: `RACE_LAP_SRC` を `"pdf_lap_times"` に戻す（1 行）／コミットを revert。
- 正本DBフルバックアップは staging apply 時の `02_DATABASE/_backup_pdf_v2_staging_20260629_153524/` が直近に存在。

## 8. apply後 / UI変更後の検証手順

1. `SELECT COUNT(*) FROM race_lap_detail`（=12763 目安）/ source_tag 内訳（v2 7710 / legacy 5053）。
2. 自然キー重複 0 / 既存業務テーブル不変（runs/laps/lap_suspension/race_results/pdf_lap_times）。
3. Workbench 起動 → Race Analysis で ROUND3/RACE1 #77、ROUND7/RACE1 #77/#52 が表示されること。
4. 非RACE（例 ROUND3/SP）が空にならないこと。
5. セクター分析が MISANO(seg NULL) で例外を出さないこと。

## 9. 次に Tatsuki 承認が必要な操作

1. VIEW `race_lap_detail` 作成（正本DB書込）。
2. Workbench `RaceAnalysisTab` 参照切替（`RACE_LAP_SRC`）。
3. Workbench 品質表示追加。
4. DB Master 再生成。
5. Supabase audit / sync 判断。
6. origin push。

## 10. Multi-agent operating check（承認前段階）

| 役割 | 担当 | 状態 |
|---|---|---|
| Codex / Handoff | 承認前タスク発行・GO 条件明示 | ✅ |
| Claude Code / Implementation | scratch 検証・差分設計・readiness 作成 | ✅ 本タスク |
| Extraction agent | v2 staging 現状確認（7710/ROUND7 1094）| ✅ |
| Quality Gate agent | VIEW 差分・非RACE 無回帰・ROUND7 表示・列互換・重複0 | ✅ 全 clean |
| DB Integration agent | VIEW 作成計画・rollback(DROP VIEW)・正本業務テーブル不変 | ✅ 設計確定（実行は GO 後）|
| Workbench / UI agent | `RaceAnalysisTab` 最小差分（RACE_LAP_SRC）・品質表示案 | ✅ 設計のみ（未編集）|
| Supervisor（止める） | VIEW 作成・Workbench 編集を承認前に停止 | ✅ 停止中 |
| Documentation / Handoff | readiness レポート・`CLAUDE.md` §39・Obsidian 更新 | ✅ 本タスク |
| Tatsuki / Final approval | VIEW 作成 + Workbench 切替の GO | ⏳ **GO 待ち** |

## 11. 結論

- **GO 待ち**。scratch 検証で overlay VIEW は意図どおり動作（RACE=v2優先・非RACE=legacy無回帰・ROUND7表示・重複0・列互換）。
- 正本DBへの VIEW 作成と Workbench 切替は **2段階**で分離可能（VIEW 作成だけでは表示不変、`RACE_LAP_SRC` 切替で初めて反映）。
- GO 受領時のみ、VIEW 作成 → Workbench 最小差分編集 → GUI スモークテスト（Tatsuki ローカル）→ 記録。
