# 2026-06-05 — Part B オンライン監査 & sync 修正

担当: Claude Code
指示書: `05_SCRIPTS/CODE_INSTRUCTION_db_reconcile_and_pipeline.md` Part B

## B-1（ローカル取り込み）— 再実行不要と判定

背景に「Cowork が 2026-06-05 に build_unified_db.py を実行済み」とあり、ローカルを検証した結果、
受け入れ基準を**既に満たしている**ため 5 系統 import の再実行はスキップ（冗長 + report_importer は人手ゲートあり）。

- `runs` distinct rounds に `ROUND6` 含む全ラウンド存在
- `runs` の UNK / NULL run_id = **0**
- ローカル件数: race_results 742 / pdf_lap_times 7613 / runs 572 / laps 989 / chassis_geometry 230 / ts24_sessions 130

## B-2【最重要】オンライン肥大の根本原因 — 確定

`sync_to_supabase.py` の `upsert()` が `conflict_col="id"` を使用。しかし各 SELECT は `id` を
**取得していない** → payload に id が無い → `on_conflict=id` が機能せず毎回 INSERT
→ 再 sync のたびに全行が重複蓄積。

### オンライン vs ローカル（監査時点）

| テーブル | online | local | 倍率 |
|---|---|---|---|
| race_results | 8,018 | 742 | 10.8x |
| lap_times | 86,751 | 7,613 | 11.4x |
| sessions | 259 | 130 | 2.0x |
| sessions_2d | 3,013 | 276* | 10.9x |
| lap_times_2d | 13,155 | 956* | 13.8x |
| chassis_geometry | 1,162 | 230 | 5.1x |

\* sessions_2d は sync が `runs WHERE fork_type IS NOT NULL`、lap_times_2d は `laps WHERE lap_time_s IS NOT NULL` を投入するため、ローカル全件（572/989）ではなくフィルタ後件数。

### 切り分け（在地デデュープ vs truncate+resync）

- オンラインの round 空間（ROUND1-6,11,12）・rider_num 形式は **local と完全一致**
- ROUND6 のみ online=local=914（1 回だけ sync された最新 → 重複ゼロ）
- ROUND1-5,11,12 が 10,000〜13,000 行/round の純粋累積
- 自然キー一意化後でも online distinct > local（lap_times 16,240 vs 7,613）
  → 旧ビルドの命名ドリフト（`PHILLIP ISLAND` 二重L / `UNK_` / 日付プレフィクス）が
    別キーとして残存。在地デデュープでは収束しない。
- COMPANY スコープ（race_results 588 / sessions 21 等）は **すべて local にも存在**
  （local: race_results COMPANY 294, ts24_sessions COMPANY 21, runs COMPANY 41）
  → truncate+resync で COMPANY 含め全正当データ保全

**結論: TRUNCATE + 自然キー UNIQUE + ローカルから再 sync が最も確実かつ安全。**

## 実施済み

1. **B-2a バックアップ（読み取り専用）**
   `02_DATABASE/_supabase_backup_20260605-185421/`（6 テーブル・112,358 行 + _manifest.json）

2. **B-2b `sync_to_supabase.py` の conflict_col 自然キー化**（コミット対象）

   | テーブル | 新 conflict_col |
   |---|---|
   | race_results | round_no, circuit, session_type, rider_no, position |
   | lap_times | round_id, circuit, session_type, rider_num, lap_no |
   | sessions | session_id（既存） |
   | sessions_2d | round, circuit, session_type, rider, run_no |
   | lap_times_2d | round, circuit, session_type, rider, run_no, lap_no |
   | chassis_geometry | rider, circuit, session, run_no, chassis_label |

   ※ 全自然キーをローカルで一意性検証済み（race_results は +position で 742=742、
     chassis は +chassis_label で 230=230）。オンライン実スキーマにも全列存在を確認。

3. **B-2c デデュープ + 制約 SQL 生成**
   `05_SCRIPTS/reports/supabase_dedup_and_constraints_20260605.sql`
   （TRUNCATE 6 テーブル → 自然キー UNIQUE INDEX NULLS NOT DISTINCT）

## 実行結果（2026-06-05 完了）

1. ✅ **Tatsuki**: `supabase_dedup_and_constraints_20260605.sql` を Supabase Studio で実行（Success）
2. ✅ **Claude Code**: `sync_to_supabase.py` 実行 — 全バッチ OK
3. ✅ **件数検証 — 全テーブル online == local 達成**

| テーブル | Before | After | local | 判定 |
|---|---|---|---|---|
| race_results | 8,018 | 742 | 742 | ✅ |
| lap_times | 86,751 | 7,613 | 7,613 | ✅ |
| sessions | 259 | 130 | 130 | ✅ |
| sessions_2d | 3,013 | 276 | 276 | ✅ |
| lap_times_2d | 13,155 | 956 | 956 | ✅ |
| chassis_geometry | 1,162 | 230 | 230 | ✅ |

合計 **112,358 → 9,917 行**（累積ゴミ 91% を除去）。

4. ✅ **冪等性確認**: 2 回目の sync でも件数増加ゼロ → 自然キー upsert が正しく機能。

## B-3 / B-4

- **Workbench**: `ts24_unified.db` 直読・ローカル無変更 → 起動で自動反映（作業不要）
- **Dashboard**: Supabase ライブ読み込み・コード変更なし → 次回リロードで正データ表示（push 不要）
- **CLAUDE.md**: §1c に sync conflict キーの構造記録を追記済み
- **race_memory.json**: リポジトリ未作成のため記録は本レポート + CLAUDE.md に集約

## 本番影響

- ローカル DB / 原本: 無変更
- sync スクリプト: conflict_col のみ変更（マッピング・抽出ロジックは不変）
- オンライン: SQL 実行までは無変更（バックアップ済み）

## B-3 / B-4（SQL 実行 + 再 sync 完了後）

- Workbench は `ts24_unified.db` 直読のため再ビルド済みで自動反映（追加作業なし）
- `lap_suspension_data.json` 更新（B-1 step5）は必要なら別途
- Dashboard は git push で反映
- race_memory.json は現状リポジトリに未作成 → 作成形式を Cowork と要確認
