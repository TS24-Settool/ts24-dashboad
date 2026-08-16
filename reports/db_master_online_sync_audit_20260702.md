# Local DB Master / Online DB 同期差分確認（Phase A・read-only audit）

- **日付:** 2026-07-02
- **担当:** Claude Code（Fable 5 + 監査エージェント2並列。書込なし）
- **タスク:** `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02）「Local DB Master / Online DB 同期差分確認 + 安全同期ゲート」Phase A
- **結論:** **差分あり（exit 2）**。①Supabase `race_results` に **missing=74（全て ROUND7/MISANO・sync 未実行が原因）**、
  remote_extra=24（前回 2026-06-22 と同一の残骸・cleanup 未実行）。②`TS24 DB Master.xlsx` は **2026-06-22 のまま stale**
  （LAP_SUSPENSION 46列＝22新列 0/22・ROUND7 データなし）。**正本DB自体は健全で記録と完全一致** — 差分は全て「派生物/ミラーが正本に追いついていない」方向であり、正本の劣化ではない。
- **本 Phase A で書き込んだもの:** 本レポート + `supabase_audit.py` の自動生成物（`reports/supabase_audit_20260702.md` / `reports/cleanup_proposal_20260702.sql`）のみ。正本DB・Excel・Supabase は無変更（remote は GET のみ）。

---

## 1. 正本DB `02_DATABASE/ts24_unified.db`（mode=ro・実測）

| テーブル/VIEW | 件数 | 照合 |
|---|---:|---|
| runs | 275 | ✅ 記録一致 |
| laps | 1,202 | ✅ |
| lap_suspension | 1,202（**69列・§44 の22新列 22/22 存在**） | ✅ |
| race_results | 866（**ROUND7=74**・round は TEXT `'ROUND7'`） | ✅ |
| pdf_lap_times | 7,613 | ✅ |
| pdf_lap_times_v2_staging | 7,710 | ✅ |
| race_lap_detail（VIEW） | 12,763（v2 7,710 + legacy 5,053） | ✅ |
| metric_version_log | 32 | ✅ |

全23テーブル + 1 VIEW。CLAUDE.md §38/§40/§44 の記録と完全一致。**正本DBに問題なし。**

## 2. `TS24 DB Master.xlsx` との差分（read_only で開いた・保存なし）

- **mtime 2026-06-22 10:10 / 580,125 bytes** — §29 の safe refresh 以降**一度も再生成されていない**。
- 12シート。`LAP_SUSPENSION` = 1,204行 × **46列**。**22新列は 0/22 で全て未収録**（§44 より前のスナップショット）。
- **RACE_RESULTS 相当シートは存在しない**。ROUND7 の行はどのシートにも無し（RUN_LOG の MISANO 2行は round=NA の旧ラン）。
- バックアップ: `02_DATABASE/backups/TS24_DB_Master.pre_refresh_20260622-101011.xlsx` 1件あり。

### ★重要制約（DB Master 再生成の限界）
1. `build_excel_master.py` の SELECT 対象は **runs / laps / lap_suspension / performance / problem_log / problem_library / run_tags / setup_decision_log のみ**。
   `race_results` / `pdf_lap_times` / `pdf_lap_times_v2_staging` / `race_lap_detail` は**読まない**（grep 0件・§41a 再確認）。
   → **再生成しても ROUND7 race_results / Result PDF v2 / race_lap_detail は反映されない**。反映したければ「race_results 由来の新シート設計」が別タスク（既存フォーマット厳守）。
2. `LAP_SUSPENSION` シートは固定リスト `LS_COLS`（46列定義）で出力される。
   → **再生成しても22新列は自動では載らない**。載せるには `build_excel_master.py` の `LS_COLS` を 46→68列（+meta）へ拡張する軽微なコード変更が必要（§19d で 34→46列拡張の前例あり・追加のみ・既存書式踏襲）。
3. ROUND7 は 2D 不在のため、runs/laps/lap_suspension 由来シートに ROUND7 行が無いのは**正常**（欠陥ではない）。

## 3. Supabase/online との差分（`supabase_audit.py` 実行・GET のみ・exit 2）

| table | local | remote | remote_extra | missing |
|---|---:|---:|---:|---:|
| race_results | 866 | 792 | 0 | **74** |
| lap_times | 7,613 | 7,613 | 0 | 0 |
| sessions_2d | 246 | 259 | **13** | 0 |
| lap_times_2d | 1,202 | 1,213 | **11** | 0 |

- **missing=74 は全て ROUND7/MISANO**（FP/QP/WUP/RACE1/RACE2）＝ §37d（2026-06-29）のローカル apply 後に sync 未実行なだけ。
  **解消手段は `sync_to_supabase.py` の再実行（upsert・追加方向）であり、削除は不要。**
- **remote_extra=24 は 2026-06-22 監査と完全に同一内容**（sessions_2d=JEREZ TEST1 round空/date NULL 13件、lap_times_2d=lap_no=1 アウトラップ等 11件）。
  前回の cleanup 提案が未実行のまま残存。今回 `reports/cleanup_proposal_20260702.sql`（DELETE 24件・**提案のみ**）を再生成済み。
- 詳細: `reports/supabase_audit_20260702.md`。

### 前回監査（2026-06-22）との比較
| 指標 | 06-22 | 07-02 | 変化 |
|---|---:|---:|---|
| missing | 0 | 74 | +74（ROUND7 sync 未実行のみが原因） |
| remote_extra | 24 | 24 | ±0（同一残骸） |

## 4. 「すべてのDB」の定義と同期対象/非対象

| 層 | 実体 | 同期状態 | 扱い |
|---|---|---|---|
| **Canonical（正本）** | `ts24_unified.db` | — | 変更しない（同期の源） |
| **Derived Excel** | `TS24 DB Master.xlsx` | ❌ stale（06-22） | `refresh_db_master_safe.py` で再生成（+LS_COLS 拡張で22新列） |
| **Online mirror** | Supabase 4テーブル | ❌ race_results missing 74 | `sync_to_supabase.py` 再実行 |
| **Workbench read model** | `race_lap_detail` / `lap_suspension` | ✅ 最新（正本直読） | 対応不要 |
| **Git/origin** | code/scripts/reports | ❌ local 16 commits 未push | **別承認**（本タスク外） |
| バックアップDB群 | `_backup_*` | — | 同期対象外（履歴） |
| `Data_Base_TS24_ORIGINAL.xlsx` | 入力ソース | — | **上書き禁止**（参照のみ） |

**Supabase 同期対象は4テーブルのみ**（race_results→race_results / pdf_lap_times→lap_times / runs→sessions_2d / laps+runs→lap_times_2d）。
**`lap_suspension`（69列）・`pdf_lap_times_v2_staging`・`race_lap_detail` は設計上 Supabase 同期対象外**（sync_to_supabase.py が参照しない）。これは欠陥ではなく現行スコープ。online に載せたい場合は新テーブル + 自然キー UNIQUE INDEX の設計が別タスク（§1c ルール）。

## 5. 安全な同期順序（GO 後の実行計画）

1. **事前バックアップ**: 正本DB 検証用コピー（変更はしないが照合用）＋ DB Master は wrapper の自動バックアップ。
2. **Supabase sync**: `python3 sync_to_supabase.py` → missing 74 を upsert で解消（自然キー §1c・追加/更新のみ・DELETE なし）。
3. **Supabase 再audit**: `python3 supabase_audit.py` → race_results missing=0 を確認（remote_extra 24 は残る想定）。
4. **（オプション・別判断）remote_extra 24 cleanup**: `reports/cleanup_proposal_20260702.sql` の DELETE 24件。
   実行前に Tatsuki が SELECT で対象を確認。**sync とは分離して扱う**（削除操作のため。GO に「cleanup も含む」と明示された場合のみ）。
5. **DB Master 再生成**:
   a. （推奨）`build_excel_master.py` の `LS_COLS` を22新列分拡張（追加のみ・既存書式踏襲・§19d 前例と同型）→ `py_compile`。
   b. `python3 refresh_db_master_safe.py`（バックアップ・オープン検出・事後検証つき）。
   c. 検証: LAP_SUSPENSION 68列前後・行数1,204・正本DB件数不変・mtime 更新。
   ※ race_results/ROUND7/v2 系は再生成では載らない（§2 の制約）。新シート設計は別タスクとして分離。
6. **最終検証**: 正本DB before/after 不変・Workbench offscreen smoke（race_lap_detail / lap_suspension 読み）・reports 更新。

## 6. 実行に必要な GO 文言

- **`DB full sync GO`** — 上記 2/3/5/6 を実行（Supabase upsert sync + 再audit + LS_COLS 拡張 + DB Master 安全再生成 + 検証）。
- cleanup（手順4・DELETE 24件）は **GO に「cleanup も含む」と明示された場合のみ**実行。無ければ提案のまま保留。
- origin push / 新2D取込 / ORIGINAL.xlsx 上書き / DB Master 新シート設計は**別承認**。

## 7. rollback / backup 案

| 対象 | backup | rollback |
|---|---|---|
| 正本DB | 検証用コピー（変更なしの前提） | 不要（before==after assert） |
| DB Master | `backups/TS24_DB_Master.pre_refresh_<ts>.xlsx`（wrapper 自動） | バックアップ差戻し |
| Supabase sync | upsert のみ（削除なし）・自然キー冪等 | 誤り時は該当自然キーの手動修正（missing 方向のため実質不可逆リスク低） |
| Supabase cleanup | 実行前 SELECT 記録を report に固定 | 削除は不可逆 → **対象24件を SQL に固定済み・Tatsuki 確認後のみ** |
| LS_COLS 拡張 | git（コード変更は commit 前に diff 確認） | revert |

## 8. Multi-agent operating check

| エージェント | 実施内容 |
|---|---|
| Data Integrity | 正本DB件数・69列・22新列・ROUND7=74 を mode=ro で実測（エージェント1）→ 記録と完全一致 |
| DB Master | xlsx stale 確定・LS_COLS 46列制約・race_results 非対象を特定（エージェント1） |
| Supabase | read-only audit 実行・missing74/remote_extra24・sync対象4本と非対象の分類（エージェント2） |
| Workbench | read model は正本直読で最新＝影響なしを確認 |
| Quality Gate | before/after 照合手順・rollback を §5/§7 に定義。書込ゼロを確認 |
| Documentation/Handoff | 本 report / CLAUDE.md §46 / Obsidian（log・handoff・CURRENT_STATE・Result）更新 |
| Supervisor | sync/cleanup/再生成/push を GO ゲートに保持。**Phase A で停止**（差分ありのため Phase B の確認へ） |

## 9. 成果物

- `reports/db_master_online_sync_audit_20260702.md`（本ファイル）
- `reports/supabase_audit_20260702.md` / `reports/cleanup_proposal_20260702.sql`（audit スクリプト自動生成）
- `CLAUDE.md` §46 / Obsidian 更新
