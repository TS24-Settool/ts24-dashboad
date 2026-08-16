# Post-Round7 Downstream Sync Readiness

- Date: 2026-07-09
- Author: Claude Code
- Scope: **read-only readiness のみ**（DB Master refresh / Supabase sync / origin push / import_queue cleanup の順序と GO 条件を固定する前段調査）
- 実行禁止（本タスクで一切未実施）: canonical DB 書込 / DB Master refresh・Excel 書込 / Supabase sync・upsert・delete・DDL / `sync_to_supabase.py` 実行 / `refresh_db_master_safe.py` 実行 / commit・origin push / import_queue 更新 / metric・extraction・Report v2 変更
- 元指示: `08_OBSIDIAN/.../00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-09 節）/ `reports/post_round7_downstream_sync_code_instruction_20260709.md`（7点）
- 参照: CLAUDE.md §65（Round7 finalization）/ §46・§28（Supabase audit）/ §29・§41（DB Master 制約）/ §1c（Supabase 自然キー）/ §62・§68（import_queue / Round8 guard）/ §63・§61（Supabase v2）

本 readiness は canonical DB を `file:...?mode=ro` URI（SELECT only）で開いて実測し、周辺スクリプトは **読むだけ**で確認した。全ての数値は「今回観測した ACTUAL 値」であり、期待値との突合結果を各節に明記する。

---

## 1. Canonical DB current state（read-only 実測）

接続 = `sqlite3.connect("file:02_DATABASE/ts24_unified.db?mode=ro", uri=True)`（SELECT のみ）。

### 1.1 業務テーブル総計

| table | 期待値 | **観測値（ACTUAL）** | 判定 |
|---|---:|---:|:--:|
| `runs` | 286 | **286** | ✅ 一致 |
| `laps` | 1279 | **1279** | ✅ 一致 |
| `lap_suspension` | 1279 | **1279** | ✅ 一致 |
| `race_results` | 866 | **866** | ✅ 一致 |

`lap_suspension` の列数 = **69 列**（§44 の 22 方向別サス速度列を含む・§46a と一致）。

### 1.2 Round7（MISANO）final

| table | 期待値 | **観測値** | 判定 |
|---|---:|---:|:--:|
| `runs` WHERE round='ROUND7' | 13 | **13** | ✅ |
| `laps`（`laps l JOIN runs r ON l.run_id=r.run_id WHERE r.round='ROUND7'`）| 77 | **77** | ✅ |
| `lap_suspension` WHERE round='ROUND7' | 77 | **77** | ✅ |
| `race_results` WHERE round='ROUND7' | (74) | **74** | ✅（§37d 反映済） |

補足: `laps` テーブルには `round` 列が無い（run_id 経由）。Round7 laps は `runs` JOIN で 77 を確認した。§65c の final 反映（13 runs / 77 laps / 77 lap_suspension）と完全一致。

### 1.3 provisional テーブル（Round7 finalization 後にクリア済み）

| table | 期待値 | **観測値** | 判定 |
|---|---:|---:|:--:|
| `runs_provisional` | 0 | **0**（存在・空） | ✅ |
| `laps_provisional` | 0 | **0**（存在・空） | ✅ |
| `lap_suspension_provisional` | 0 | **0**（存在・空） | ✅ |

3 テーブルとも DROP されておらず存在し、行数 0（§65d の provisional clear と一致）。Workbench overlay は provisional 0 行のため二重表示なし（§65e）。

### 1.4 protected tables / views（残存確認 + 件数）

| object | type | **観測件数** | 期待・出典 |
|---|---|---:|---|
| `pdf_lap_times` | table | **7613** | 7613（§38a/§46a）✅ |
| `pdf_lap_times_v2_staging` | table | **7710** | 7710（§38e/§46a）✅ |
| `source_file_registry` | table | **405** | Phase 2A registry（§51a→405・§64a）✅ |
| `import_queue` | table | **397**（内訳 §6） | 管理キュー（§62/§64a）✅ |
| `data_quality_log` | table | **1340** | 1340（§65c）✅ |
| `analysis_run_log` | table | **11** | 11（§65c）✅ |
| `metric_version_log` | table | **32** | 32（§44b/§46a）✅ |
| `race_lap_detail` | **view** | **12763** | 12763（§40a/§46a）✅ |

**判定: §1 は期待値と ACTUAL がすべて一致。canonical DB は健全。不一致・欠落・DROP は 0 件。** protected な staging/registry/queue/quality/version テーブルおよび VIEW は全て残存し、§64d で懸念された cutover 方式 data-loss は発生していない（§65 の targeted-insert 方式で全 protected テーブル保全済み）。

---

## 2. DB Master refresh readiness（`refresh_db_master_safe.py` を読むだけ・未実行）

### 2.1 ラッパーの構造（read-only 確認）

`05_SCRIPTS/refresh_db_master_safe.py` は `build_excel_master.py` を subprocess 実行する安全ラッパー（§29）。

- **target workbook**: `02_DATABASE/TS24 DB Master.xlsx`（定数 `XLSX`）。テンプレート = `02_DATABASE/TS24 DB Master Back UP.xlsx`（`TEMPLATE`）。
- **backup location**: `02_DATABASE/backups/TS24_DB_Master.pre_refresh_<ts>.xlsx`（`shutil.copy2` で mtime 保持コピー・再生成前に必ず退避）。
- **Excel-lock detection**: `~$TS24 DB Master.xlsx` ロックファイルの存在チェック + `lsof -- <xlsx>`。掴まれていれば **exit 2 で中止**。`lsof` 不在環境は検出スキップ（保存失敗時に build の exit code で判別）。
- **rollback**: 事後検証（`ok=False`）時に `backups/TS24_DB_Master.pre_refresh_<ts>.xlsx` を戻す（手動）。ログ = `reports/db_master_refresh_<ts>.log`。
- **canonical への影響**: `build_excel_master.py` は正本DBを **SELECT のみ**。ラッパーは before/after を `mode=ro` で件数照合し、`runs/laps/lap_suspension/race_results` の不変を assert（変化したら exit 3）。
- **exit code**: 0=成功 / 1=事前チェック失敗 / 2=Excel使用中 / 3=事後検証失敗 / それ以外=build の exit code 伝播。
- **事後検証の主要 6 シート**: `WEEKEND_SUMMARY_HELPER` / `SIMILAR_CASES` / `SETUP_EFFECTS` / `RUN_LOG` / `DYNAMICS_ANALYSIS` / `LAP_SUSPENSION`。

### 2.2 EXPECTED diff（構造的制約の検証 — 最重要）

指示どおり `build_excel_master.py` が **どのテーブルを読むか** を grep で検証した（§41a/§46b の再確認）:

```
build_excel_master.py が FROM/JOIN するテーブル:
  runs / laps / lap_suspension / performance / run_tags / problem_log / setup_decision_log
参照ゼロ（grep 一致 0 件）:
  race_results = 0 / pdf_lap_times = 0 / race_lap_detail = 0 / pdf_lap_times_v2_staging = 0
```

→ **確定事実**: `build_excel_master.py` は `race_results` / `pdf_lap_times` / `race_lap_detail` / `pdf_lap_times_v2_staging` を **一切読まない**。DB Master の実ソースは 2D 由来の `runs`/`laps`/`lap_suspension`/`performance` + Workbench の `run_tags`/`problem_log`/`setup_decision_log`。

**§65e の重要な帰結**: Round7 は §65 の finalization で **2D 由来テーブル（`runs`/`laps`/`lap_suspension`）に本データ化された**（13/77/77）。したがって §41a 執筆時点（Round7 が 2D 由来テーブルに 0 行だった）とは状況が変わり、**今 refresh すれば Round7 (MISANO) は RUN_LOG / LAP_TIMES / DYNAMICS_ANALYSIS / LAP_SUSPENSION の各シートに反映される**。

- 現行 DB Master.xlsx は §46e（2026-07-02）再生成が最後 = **Round7 finalization（§65・2026-07-08）より前 → stale**。当時 `RUN_LOG 278 / LAP_TIMES 1204 / LAP_SUSPENSION 68列1204行`。
- refresh 後の期待差分（概算・2D 由来テーブル基準）: RUN_LOG に Round7 の 13 runs、LAP_TIMES / LAP_SUSPENSION に Round7 の 77 laps、DYNAMICS_ANALYSIS に MISANO の per-run 集計行が加わる。`LS_COLS` は §46e で 68 列化済のため列構造は不変（新規 22 速度列は既に反映済）。
- 反映されないもの（設計どおり）: `race_results`（ROUND7=74）/ v2 lap 明細 / `race_lap_detail` / Workbench Race Analysis 改善。これらを Excel に載せたい場合は **race_results 由来シート新設の別タスク**が必要（§41a/§46b）。

### 2.3 GO 判定

canonical DB 健全（§1）・ラッパーの安全策（backup / lock 検知 / rollback / 件数不変 assert）確認済み・構造的制約も把握済み。**readiness 上の障害なし。**

```text
DB Master refresh GO
```

precondition: Excel（TS24 DB Master.xlsx）を閉じておくこと（lock 検知で exit 2 中止するが未然に閉じる）。実行コマンド（GO 後）= `python3 refresh_db_master_safe.py`。

---

## 3. Supabase current v3 sync readiness（`sync_to_supabase.py` / `supabase_audit.py` を読むだけ・未実行）

### 3.1 同期 4 テーブルと自然キー（§1c）

`sync_to_supabase.py` は v3（4 テーブルのみ・自然キー upsert・`Prefer: resolution=merge-duplicates`）。DELETE を一切持たない。

| Supabase table | local source | 自然キー（on_conflict / UNIQUE INDEX） |
|---|---|---|
| `race_results` | `race_results` | round_no, circuit, session_type, rider_no, position |
| `lap_times` | `pdf_lap_times` | round_id, circuit, session_type, rider_num, lap_no |
| `sessions_2d` | `runs` WHERE fork_type IS NOT NULL | round, circuit, session_type, rider, run_no, **date** |
| `lap_times_2d` | `laps` JOIN `runs` WHERE lap_time_s IS NOT NULL | round, circuit, session_type, rider, run_no, lap_no, **date** |

`supabase_audit.py` は同一投影ロジックを `AUDIT_SPECS` に複製した **read-only 監査**（local=SELECT `mode=ro` / remote=HTTP GET のみ）。POST/PUT/PATCH/DELETE を持たず、`cleanup_proposal_<date>.sql`（remote_extra の DELETE 案）を出力するだけ。exit 0=差分なし / 2=差分あり / 1=エラー。**本 readiness では project rule に従い audit も未実行。**

### 3.2 EXPECTED diff（分析・監査未実行のため推定）

最終 sync = §46e（2026-07-02・`DB full sync GO`）。以降の canonical 変化 = **§65 Round7 finalization（2026-07-08）**。この時系列から各テーブルの想定差分:

| Supabase table | §46e sync 時 | 現 local | 想定 missing（remote に無い local 行） |
|---|---:|---:|---|
| `race_results` | 866 | 866 | **0**（§46e で ROUND7=74 含め 866 全て sync 済・以降不変） |
| `lap_times`（pdf_lap_times） | 7613 | 7613 | **0**（§46e 以降 pdf_lap_times 不変） |
| `sessions_2d`（runs fork_type≠NULL） | 246 | ~ | **>0**（Round7 の 13 runs は setup 充填済 §65c → fork_type≠NULL で projection に加わるが §46e 後の sync 未実施 → 未反映見込み） |
| `lap_times_2d`（laps JOIN runs） | 1202 | ~1279 | **~77**（Round7 の 77 laps が §46e 後に本データ化・remote 未反映見込み） |

→ **想定**: `race_results` / `lap_times` は missing=0（既に current）。**Round7 の 2D 由来デルタ（sessions_2d + lap_times_2d）が §46e 以降 sync されていないため missing に出る見込み。** 正確な数は GO 前に `supabase_audit.py`（read-only GET）を1回走らせて確定するのが安全（本 readiness では未実行）。

- **DELETE は不要かつ禁止**: missing は upsert（追加/更新）で解消。sync_to_supabase.py に DELETE 経路は無い。
- **remote_extra 24 は既知残渣**: §28c/§46a と同一（sessions_2d 13 + lap_times_2d 11・online のみに存在する round 空/date NULL 等の残骸）。cleanup は `cleanup_proposal_<date>.sql` 提案のみで、**GO に cleanup を明示した時だけ** Tatsuki が SELECT 確認後に手動実行（§46c）。current v3 sync 自体は remote_extra を触らない。

### 3.3 GO 判定

canonical 健全・sync は自然キー upsert（idempotent・肥大化しない §1c）・DELETE なし。**readiness 上の障害なし。**

```text
Supabase current v3 sync GO
```

precondition: （推奨）GO 直前に `supabase_audit.py` を read-only 実行して missing/remote_extra を確定 → `sync_to_supabase.py` upsert → 再 audit で missing=0 確認（§46c の手順①〜③）。cleanup（remote_extra 24 DELETE）は **含めない**のが default（別判断）。

---

## 4. Supabase v2 G1 ordering（別ゲート）

default 方針（§61b / §63・指示 §4）:

1. **先に current v3 mirror を健全化**（§3 の `Supabase current v3 sync GO` で Round7 デルタを upsert → missing=0）。
2. **その後で v2 G1 を別ゲートとして進める**。v2 は新スキーマ `ts24_v2`（別 schema・既存 v3 は不変・rollback=`DROP SCHEMA ts24_v2 CASCADE`）。

- v2 改訂 DDL = `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707_revised.sql`（§63 で readiness 7 findings を反映済・BLOCKING の `v_sync_runs` rs.* 重複列は修正済）。
- v2 ゲート順: **G1 `Supabase v2 schema GO`（DDL 実行）** → G2 初回 v2 sync（新規 `sync_to_supabase_v2.py`・既存 v3 不変）→ G3 compat view 切替 → G4 旧テーブル整理。
- v2 は current v3 と独立した schema のため、v3 sync の健全化を待たずとも技術的には実行可能だが、**運用上は v3 mirror を先に current にしてから v2 に進む**のを推奨（mirror 不整合を持ち込まない）。

→ **v2 は current v3 sync とは分離した別 GO（`Supabase v2 schema GO`）として据え置く。**

---

## 5. git / origin push readiness（read-only git commands・commit/push しない）

git root = `05_SCRIPTS`（`02_DATABASE` は git root 外 = commit 対象外。DB / xlsx / backups は追跡されない）。remote `origin` = `https://github.com/TS24-Settool/ts24-dashboad.git`。

### 5.1 branch / 位置

- **current branch = `phase2a-extraction-20260620`**（HEAD = `5651d97`）。
- upstream tracking = **未設定**（`@{u}` なし）。
- `main` = `626abdf`（PR#1 merge）。current branch は **main より 21 commits 先行**（§32〜§44 の PDF v2 / Round7 race_results / staging / VIEW / phase suspension speed apply 群）。

### 5.2 tracked diff（uncommitted・6 ファイル）

```
 M CLAUDE.md
 M build_excel_master.py                              ← §46e LS_COLS 46→68 拡張（未コミット）
 M build_master_db.py                                 ← §65a event filter (--round) 追加
 M reports/round7_race_results_apply_dry_run_20260629.md
 M requirements_workbench.txt                         ← §48 python-pptx/matplotlib 追記
 M ts24_workbench.py                                  ← §48/§55/§57/§60/§62/§68 の一連 UI 変更
```

### 5.3 untracked（operational code + reports + 作業メモ）

- **operational code（add 候補）**: `apply_round7_targeted_insert.py`（§65）/ `session_extract_staging.py`（§53）/ `suspension_report.py`（§48）。
- **reports/*.md**（多数・§30〜§68 の readiness/apply 記録・本レポート含む）。
- **draft/未成熟**: `parse_chrono_pdf_DRAFT.py` / `parse_race_pdf.py`。
- **commit すべきでない作業メモ**: `CLAUDE_CODE_INSTRUCTIONS_*.md` / `CODE_INSTRUCTION_*.md` / `CODEX_INSTRUCTIONS_*.md` / `TRN_*.md` / `DB_REBUILD_SPEC_v1.0.md`（§21e で「未 commit（意図的）」分類）。
- **backup ディレクトリ**: `_backup_susp_speed_20260620-071355/`（実行時アーティファクト・commit 非対象）。

### 5.4 commit 除外される生成物（.gitignore 実測）

`.gitignore` が除外: `ts24_config.json`・secrets 各種 / `*.db *.sqlite*`（正本DB）/ `*.xlsx *.csv *.xls *.xlsm`（DB Master・原本）/ `*.log`（`reports/*.log`）/ `__pycache__` / `.DS_Store` `._*` / `*.skill` / `lap_comparison_latest.json`。

- **注意（.gitignore の穴）**: `reports/pptx/` の `.pptx` / `.pdf` は **`.gitignore に列挙されていない**（除外は xls 系のみ）→ `git add .` すると **pptx/pdf サンプルまで追跡される**。push 対象を絞る際は `reports/pptx/` を明示的に除外するか add を選別すること。
- `02_DATABASE/`（DB・xlsx・backups）は git root 外なので、そもそも 05_SCRIPTS の commit に混入しない。

### 5.5 GO 判定

push 自体は本 readiness の禁止事項。ただし「push できる状態か」の整理は完了。**push は「21 commits 先行 + 6 tracked 変更 + 選別が必要な untracked 群」を含む大規模差分**であり、push 前に (a) 作業メモ/draft/pptx の commit 選別、(b) branch の push 先（main への PR か feature branch push か）の決定、(c) upstream 未設定のため初回 push は `-u` が要る、を Tatsuki が確定する必要がある。

```text
origin push readiness GO
```

precondition: commit 分割方針（operational code + reports を含める / 作業メモ・draft・pptx を除外）を Tatsuki が承認し、push 先 branch を決めること。**commit / push は本タスクで未実施。**

---

## 6. import_queue historical cleanup ordering（queue に触らない）

### 6.1 現状（read-only 実測）

`import_queue` = **397 行**。status 内訳:

| status | 件数 |
|---|---:|
| pending | **364** |
| awaiting_gate | 12（Round7 セッション・§57） |
| failed | 7（Round7 FAIL outing・§57） |
| skipped | 14（Round7 EngineWarmup 等・§57） |

pending 364 の ROUND トークン内訳（file_path 解析）: NO_ROUND_TOKEN 113（Result PDF/report 系）/ ROUND1 48 / ROUND2 57 / ROUND3 30 / ROUND4 28 / ROUND5 35 / ROUND6 29 / ROUND7 7 / ROUND10 3 / ROUND11 7 / ROUND12 7。**ROUND8 pending = 0**（Round8 folder は未 Session Scan・§68c）。

### 6.2 問題と順序

- **歴史的 pending 問題（§62）**: pending の大半は **Round8 以前の historical outing**（既に final 取込済イベント）。§62 の未フィルタ dry-run で ~160 の非 Round8 outing/1249 laps が候補化した既知問題。これらを誤って apply すると final 済データの **provisional 重複投入**になる。
- **fail-closed guard（§68）**: `session_extract_staging.py --required-round` + Workbench `ImportQualityTab.REQUIRED_ROUND="ROUND8"` の 2 層ガードで、**Round8 以外は Apply 不可**（exit 4 / UI 拒否・DB 無変更）。したがって歴史的 pending が残っていても**誤投入は物理的に防止済み**。
- よって cleanup は **緊急ではない**が、queue の見通しを良くするため次 race weekend 前に historical pending を `skipped` 化する整理が推奨（§62 §4）。

→ **`queue cleanup GO` は独立した別ゲートのまま。本 readiness では import_queue を一切触らない。** cleanup は Supabase sync / DB Master refresh とは順序依存が無い（独立作業）。

---

## 7. GO menu（分離した GO 候補・推奨順序・precondition）

canonical DB は健全（§1 全一致）。以下を **分離した GO 候補**として提示する（inbox 記載どおり）。各 GO は独立で、それぞれ別途 Tatsuki の明示 GO を要する。

| # | GO 文言 | 内容 | precondition | 推奨順序 |
|---|---|---|---|:--:|
| 1 | `DB Master refresh GO` | `refresh_db_master_safe.py` で TS24 DB Master.xlsx を再生成（Round7 が 2D 由来シートに反映される） | Excel を閉じる | **1st**（canonical 由来・独立・低リスク） |
| 2 | `Supabase current v3 sync GO` | `sync_to_supabase.py` upsert（Round7 の sessions_2d/lap_times_2d デルタ）+ 再 audit で missing=0 | GO 直前に `supabase_audit.py`（GET）で差分確定。cleanup は含めない | **2nd**（current mirror 健全化） |
| 3 | `origin push readiness GO` | commit 分割 → origin push | commit 選別（作業メモ/draft/pptx 除外）+ push 先 branch 決定 + 初回 `-u` | **3rd**（1・2 の変更を確定後に push） |
| 4 | `queue cleanup GO` | historical pending（非 Round8）を skipped 化 | §68 guard で誤投入は既に防止済 → 緊急でない。次 race weekend 前でよい | **独立**（順序依存なし・任意） |
| 5 | `Supabase v2 schema GO` | v2 `ts24_v2` schema DDL 実行（G1） | current v3 mirror 健全化（#2）後に別ゲートで | **last**（#2 の後・別系統） |

### 推奨実行順序（要約）

1. **`DB Master refresh GO`** — canonical 由来・最も独立・Round7 を Excel へ。
2. **`Supabase current v3 sync GO`** — Round7 の 2D デルタで current mirror を最新化（DELETE なし・cleanup 含めない）。
3. **`origin push readiness GO`** — 1・2 の未コミット変更（`build_excel_master.py` 等）を含め commit 選別後 push。
4. **`queue cleanup GO`** — 独立。次 race weekend 前に整理（§68 guard により先送り可）。
5. **`Supabase v2 schema GO`** — current v3 健全化後に別ゲート（v2 G1）。

### No-Go 条件

- canonical DB 件数が §1 と乖離した場合（今回は全一致 → No-Go 事由なし）。
- DB Master refresh 時に Excel が開いている（lock 検知で exit 2 → Excel を閉じて再実行）。
- Supabase audit で想定外の large missing/extra が出た場合は sync 前に原因調査。

### 各 write step の rollback

- DB Master refresh: `02_DATABASE/backups/TS24_DB_Master.pre_refresh_<ts>.xlsx` を戻す（canonical 無影響）。
- Supabase v3 sync: 追加方向（upsert）のみ・DELETE なし → 論理的 rollback 不要。誤 upsert 時は正しい値で再 upsert。
- origin push: push 前は branch reset で戻せる。push 後は revert commit。
- queue cleanup: 実行前に queue backup（cleanup スクリプト側の責務・本 readiness 対象外）。
- Supabase v2 DDL: `DROP SCHEMA ts24_v2 CASCADE`（既存 v3 / canonical 無影響）。

### Tatsuki への open questions

1. `Supabase current v3 sync GO` に **remote_extra 24 の cleanup を含めるか**（default = 含めない）。
2. `origin push readiness GO` の **push 先**（main への PR / feature branch push）と commit 選別範囲（作業メモ・draft・`reports/pptx/` を除外してよいか）。
3. `Supabase v2 schema GO` の実施タイミング（current v3 健全化の直後か、後日別ゲートか）。

---

## 付録: 期待値 vs ACTUAL 突合結論

**全ての期待値が観測値と一致した（discrepancy 0 件）。** runs 286 / laps 1279 / lap_suspension 1279 / race_results 866、Round7 final 13/77/77、provisional 0/0/0、protected tables/views（pdf_lap_times 7613 / pdf_lap_times_v2_staging 7710 / source_file_registry 405 / import_queue 397 / data_quality_log 1340 / analysis_run_log 11 / metric_version_log 32 / VIEW race_lap_detail 12763）すべて残存・件数整合。canonical DB は downstream sync を開始できる健全状態。
</content>
</invoke>
