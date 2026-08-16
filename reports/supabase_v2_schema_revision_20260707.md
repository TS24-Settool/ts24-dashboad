# Supabase v2 Core Schema 改訂版 DDL 作成レポート

- **日付:** 2026-07-07
- **担当:** Claude Code（DDL 改訂エージェント・ローカル作業のみ）
- **入力:** `reports/supabase_v2_migration_readiness_20260707.md`（7点の要修正＝仕様）/
  `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707.sql`（原本・無変更）/
  `reports/supabase_v2_architecture_design_20260707.md`（設計意図）/
  正本DB `ts24_unified.db`（`mode=ro` PRAGMA のみ・metric_version_log 列確認）
- **出力（新規2ファイルのみ）:**
  1. `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707_revised.sql`
  2. 本レポート
- **実行状態: どこでも未実行。** 本 DDL の実行は G1 ゲート `Supabase v2 schema GO` の
  Tatsuki 明示承認後のみ（§61b / readiness §6）。

---

## 1. 7点の修正内容（before → after）

### 修正1【BLOCKING】`v_sync_runs` の `rs.*` 列重複

- **before:**
  ```sql
  r.data_stage,
  r.quality_status,
  rs.*
  FROM ts24_v2.runs r ... LEFT JOIN ts24_v2.run_setup rs ...
  ```
  → `r.run_id` と `run_setup.run_id` が二重に出力され、Postgres は CREATE VIEW 時点で
  `column "run_id" specified more than once` エラー → 単一トランザクションのため **COMMIT 全体が失敗**。
- **after:** `rs.*` を廃止し、run_setup の **30列を明示列挙（run_id 除外）**
  `rs.fork_type, rs.f_set_c, ... rs.tyre_rear` + `rs.updated_at AS setup_updated_at`。
  機械チェックで view 出力 50列・**重複ゼロ**を確認（§3）。

### 修正2【設計】track_temp / air_temp / weather を per-run へ

- **before:** `sessions` のみに `track_temp REAL, air_temp REAL, weather TEXT`（同一 session 内の
  run 間温度差を表現できない＝local 正本と不一致）。
- **after:** **`ts24_v2.runs` に3列を追加（正本の置き場所）**。sessions 側の3列は削除せず
  **「代表値（任意・NULL可）」として保持**し、`COMMENT ON COLUMN` で
  「Session-level REPRESENTATIVE value only. Authoritative per-run value = ts24_v2.runs.*」と明文化。
  `v_sync_runs` にも `r.weather/r.track_temp/r.air_temp`（+ `r.comment`）を出力（mapping §3.1 整合）。

### 修正3【設計】`lap_phase_metrics.statistic` の 'peak' 廃止

- **before:** `statistic TEXT NOT NULL`（CHECK なし・コメントに `avg / peak / min / max / count / duration`）。
- **after:**
  ```sql
  statistic TEXT NOT NULL CHECK (statistic IN ('avg','mean','min','max','p95','count','duration'))
  ```
  'peak' という語は**使用禁止**。reducer 対応表を DDL コメント + `COMMENT ON COLUMN` に固定:
  - 新22 directional zone-speed 列（§44 `*_spd_peak`）→ **'p95'**
  - 凍結列 `brk_f_dive_spd_peak`・abs 別名 `ce_r_spd_peak`・full-lap `f/r_dive/reb_spd`（§18）→ **'max'**
  - `*_avg` → 'avg' / `lap_susF/R_mean` → 'mean' / min/max → 'min'/'max' / zone count → 'count' /
    `ph12_rear0_s` → 'duration'
  metric_versions.guard_rule と一致させる旨も明記。

### 修正4【設計】phase CHECK に 'ph12' 追加

- **before:** `CHECK (phase IN ('braking','apex','exit','full_lap','full_brake'))`
- **after:** `CHECK (phase IN ('braking','apex','exit','full_lap','full_brake','ph12'))`
  + コメントで ph12 = PH1-2 代理マスク（BRAKE_FRONT≥0.3bar 進入相・`ph12_rear0_s`、
  statistic='duration'・unit='s'）と定義差を明記。

### 修正5【設計】`source_files.sha256` → `manifest_hash` 改名

- **before:** `sha256 TEXT` + `source_files_sha256_uniq` partial UNIQUE index。
- **after:**
  ```sql
  manifest_hash  TEXT,   -- §24a stat manifest (name|size)。full-content sha256 ではない
  content_sha256 TEXT,   -- --deep-hash 実行時のみ充填（nullable）
  ```
  + `COMMENT ON COLUMN` で「NOT a full-content sha256 / do not treat as cryptographic content identity」を明記。
  partial UNIQUE index は **manifest_hash 側**（`source_files_manifest_hash_uniq`）+
  content_sha256 側（`source_files_content_sha256_uniq`）の両方を作成。
  ※原設計に content hash 列は無かったが、readiness 5「真 sha256 は --deep-hash 時のみ充填」を
  受け皿にするため nullable 別列として追加。

### 修正6【小】`runs.source` 列追加

- **before:** v2 runs に無し（source_file_id のみ）。
- **after:** `source TEXT`（例 `ORIGINAL+2D` / `2D_ONLY` / `2D_PROVISIONAL`）。
  backfill 初期は registry 突合が不完全なため保持、と `COMMENT ON COLUMN` に明記。`v_sync_runs` にも出力。

### 修正7 `ts24_v2.metric_versions` テーブル追加

- **before:** local `metric_version_log`（32行）の受け皿が v2 に無し。
- **after:** 新テーブル `ts24_v2.metric_versions`。列は **local PRAGMA 実測を踏襲**:
  `metric_name, version, table_name, definition, units, guard_rule, source_script,
  effective_from, superseded_at, superseded_by, notes` + `UNIQUE (metric_name, version)` +
  BIGSERIAL PK + created_at。`lap_phase_metrics.metric_version` の参照先である旨と
  guard_rule に n<5 / n<10 ルールを記録する旨を `COMMENT ON TABLE` に明記。
- **補足（readiness 2.3-7・status enum）:** タスク指定の7点には含まれないが、readiness 原文の
  7点目（source_files.status の enum 不一致）は「**あえて自由 TEXT + ドキュメント化**」の選択肢で対応
  （COMMENT に local 実値集合 discovered/queued/incomplete/gated/unknown を記載、揺れは
  quality_events で検出）。CHECK は付けない＝local 値の進化に追従可能。

---

## 2. 追加確認3点の反映

1. **result_laps の単一供給源:** `COMMENT ON TABLE ts24_v2.result_laps` に
  「SINGLE SUPPLY SOURCE = local VIEW `race_lap_detail`（12763行）。生2テーブル
  （pdf_lap_times_v2_staging / pdf_lap_times）を別々に sync してはいけない（同一自然キーで
  upsert し合う）。sync_to_supabase_v2.py の規約として固定」を明記。
  + **非キー列 `source_table TEXT`**（'v2_staging'/'legacy'）を result_laps に追加。
2. **n<5 / n<10 の no-row ルール:** `COMMENT ON TABLE ts24_v2.lap_phase_metrics` に
  「avg: n<5 / p95: n<10（および構造的欠測）のとき**行を作らない**。行なし=NULL、
  value_num=0=実測ゼロ。0埋め・NULL行挿入は禁止 → **0 と NULL は決して混同されない**（§19a）」を明記。
3. **互換ビューは final-only 既定 + provisional は明示 opt-in:**
  `v_sync_runs` / `v_lap_phase_metrics_dashboard` に `WHERE data_stage='final'` を組み込み
  （PROV_ run は規約上 data_stage='provisional' のため同条件で除外）。provisional を見たい場合のみ
  **`v_sync_runs_with_provisional` / `v_lap_phase_metrics_dashboard_with_provisional`** を使用
  （フィルタなし・data_stage 列で段階を明示）。

その他: 単一トランザクション（BEGIN〜COMMIT 各1）構造は原本どおり維持。
RLS は原本方針を維持しつつ「backfill GO 前に RLS + service-key ポリシー必須（readiness §5）」を末尾コメントに追記。
readiness §3.4 の race_results sector1-3 追加は**7点/追加3点のいずれにも含まれないため今回は見送り**（G1 前の別判断事項として残置）。

---

## 3. 検証方法と限界

| 検証 | 結果 |
|---|---|
| ビュー出力列の重複（原本の致命傷） | Python 機械チェックで 4ビュー全て**重複ゼロ**（v_sync_runs 50列 / dashboard 22列 ×各2） |
| 括弧バランス / 文数 / BEGIN・COMMIT | 括弧 104対 バランス一致・47文・BEGIN 1 / COMMIT 1 |
| statistic CHECK に 'peak' が無い / phase に 'ph12' が有る | 確認済み |
| sha256 列の残存なし / manifest_hash・content_sha256・metric_versions・runs.source 存在 | 確認済み |
| PostgreSQL 構文（NULLS NOT DISTINCT=PG15+、COMMENT ON、partial index、BIGSERIAL、JSONB、TEXT[]） | 目視パスのみ。使用構文は全て既存 Supabase 実績（`supabase_dedup_and_constraints_*.sql` で NULLS NOT DISTINCT 使用済）または標準構文 |
| **限界:** ローカルに `psql` / `sqlglot` とも無し（新規 install は禁止事項につき実施せず） | **実 SQL パース検証は未実施。** 正式な構文検証は **G1 時に Supabase staging プロジェクト（または一時 schema 名）/ SQL Editor の dry コンテキストで実施**すること（readiness §5「DDL 自体の失敗」対策と同一手順） |

---

## 4. G1 以降のゲート（再掲・readiness §6）

| Gate | 内容 | 事前条件 |
|---|---|---|
| **G1 `Supabase v2 schema GO`** | 本改訂版 DDL を ts24_v2 に実行（テーブル/インデックス/ビュー存在確認のみ・データ投入なし） | 本改訂の反映（済）+ Phase B projection サンプル（POST なし）で列マッピング確定 + staging dry 実行 |
| **G2 `Supabase v2 backfill GO`** | `sync_to_supabase_v2.py`（新規）で final のみ upsert → `supabase_v2_audit.py` 照合 | G1 完了・RLS 最低限設定・provisional 除外既定の確認 |
| **G3 `Compatibility view 切替 GO`** | `v_compat_*` 4本の行レベル一致証明 → dashboard 参照切替 | G2 完了・並行 sync 差分ゼロ実績 |
| **G4 旧テーブル整理 GO** | 旧 public 4テーブル sync 停止・remote_extra 24 cleanup 判断と統合 | G3 後の安定運用・Tatsuki 最終判断 |

rollback は従来どおり `DROP SCHEMA ts24_v2 CASCADE` 一発（正本・旧4テーブル・dashboard 無影響）。

---

## 5. Multi-agent operating check

| 役割 | 本タスクでの実施 |
|---|---|
| Architecture | readiness 7点 + 追加確認3点を DDL に反映、原本との差分を §1-§2 で対応付け |
| DB Integrity | 正本DB は `file:...?mode=ro` の PRAGMA/SELECT のみ（metric_version_log 列・32行確認）。書込ゼロ |
| Supabase | remote アクセス一切なし（GET すら不実行）。DDL はローカルファイルとして作成のみ |
| Quality Gate | 機械チェック（ビュー列重複/括弧/CHECK 内容）を実施、psql 不在の限界を §3 に明記 |
| Documentation | 本レポート + 改訂版 SQL の2ファイルのみ新規作成 |
| Supervisor | DDL 実行・sync・POST/PATCH/DELETE・既存ファイル編集・install・commit を全て停止（G1 以降は Tatsuki GO 待ち） |
| Tatsuki | G1 `Supabase v2 schema GO` の判断待ち |

## 6. 禁止事項遵守宣言

- Supabase への接続・SQL 実行・sync・POST/PATCH/DELETE: **一切なし**（GET も不実行）。
- 正本DB: read-only URI（`mode=ro`）での PRAGMA/SELECT のみ・書込ゼロ。
- Workbench / Report / DB Master / いかなる `.py` も**無編集**。原本 SQL
  `supabase_v2_core_schema_20260707.sql` も**無変更**。
- パッケージ install なし（sqlglot 等の不在を確認したのみ）。
- 書込は指定の新規2ファイルのみ:
  `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707_revised.sql` / 本レポート。
