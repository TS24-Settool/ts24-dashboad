# Result PDF v2 — 正本 staging 反映 + Workbench 参照切替 実装計画（read-only 事前確認）

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-27 タスク）
ブランチ: `phase2a-extraction-20260620` / HEAD `54b460b`（local・未push）
位置づけ: **read-only の事前確認と実装計画のみ**。本レポートでは正本DBへの書込・table作成・
Workbench 変更・Supabase・Phase 2B・origin push を**一切行っていない**。実装は各項目とも Tatsuki 承認後。

関連: `CLAUDE.md` §31/§32 / `reports/pdf_v2_gate_20260625.md` /
Obsidian `05_DB_AUDIT/2026-06-25_pdf_v2_integration_design.md`。

---

## 0. 現状（read-only 再確認・2026-06-27）

- `pdf_v2_scratch_gate.py --all`（45 PDF）を再実行。**正本DB業務テーブル before==after 不変**
  （runs275 / laps1202 / lap_suspension1202 / race_results792 / pdf_lap_times7613）。
- Gate 集計（rider×session 単位）: **PASS 425 / WARNING 805 / FAIL 16**。
- PASS のラップ行 = **6756**（うち seg 充填 6286 / 425 rider-session）。現 `pdf_lap_times` = 7613 行。

### 0a. セッション種別での明確な差（採用方針の根拠）

| 区分 | PASS | WARNING | FAIL | 真値(`race_results`)の性質 |
|---|---:|---:|---:|---|
| **RACE**(RACE1/2) | **399** | 69 | 3 | 完全な公式分類 → G1〜G3 が有効 |
| 非RACE(SP/QP/FP/WUP) | 26 | **736** | 0 | **部分的**（予選/練習は全ライダーを網羅しない）|

- **RACE WARNING 69 の内訳**: extra(race_results に無い) 35 / G5 range外(out/in lap 等) 34。
- **非RACE WARNING 736 の内訳**: extra 714 / G5 range外 22。
  → 非RACE の WARNING はほぼ **「race_results に該当行が無い」**。これは v2 の品質劣化ではなく、
  **非RACE では race_results が per-rider 真値として不完全**（＝Gate の真値モデルが非RACEに合っていない）ことが主因。

**結論**: 正本反映は **RACE セッションを先に**進めるのが安全・高価値（Race Analysis の欠落＝#77 等を直接解消）。
非RACE は (a) `is_outlap` 導出 と (b) race_results に依存しない session 内整合ゲート を整えるまで**保留**。

---

## 1. PASS-only 正本 staging 反映 — 実装計画（要承認）

### 1a. 反映先テーブル（正本DB内・**新規**／業務テーブルは不変）

```sql
CREATE TABLE IF NOT EXISTS pdf_lap_times_v2_staging (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round TEXT, circuit TEXT, session_type TEXT, date TEXT,
    position INTEGER, rider_num INTEGER, rider_name TEXT, lap_no INTEGER,
    seg1 REAL, seg2 REAL, seg3 REAL, seg4 REAL,
    lap_time TEXT, lap_time_s REAL, speed REAL, local_time TEXT,
    is_outlap INTEGER DEFAULT 0, is_pit INTEGER DEFAULT 0, is_cancelled INTEGER DEFAULT 0,
    source_file TEXT, extractor_version TEXT, generated_at TEXT,
    gate_status TEXT, data_scope TEXT DEFAULT 'TS24_PRIVATE'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pdf_v2_staging
  ON pdf_lap_times_v2_staging(round, session_type, rider_num, lap_no, date);
```

- **業務テーブル（`pdf_lap_times`/`race_results`/`runs`/`laps`/`lap_suspension`）は触らない。**
  新規 `pdf_lap_times_v2_staging` を**追加するだけ**（§20b の管理テーブル追加と同じ非破壊パターン）。
- 自然キー = `(round, session_type, rider_num, lap_no, date)` で §1c の `lap_times` 系に整合。

### 1b. 投入対象（PASS のみ・段階導入）

| 段階 | 対象 | rider-session | 効果 |
|---|---|---:|---|
| **Step 1（推奨）** | **RACE** セッションの `gate_status='PASS'` | 399 | Race Analysis 欠落を解消（#77 等）|
| Step 2（任意・要再判断）| RACE の WARNING（実ラップだが G5 range/G3 微差）| 69 | in/out lap も実データ。flag 付きで採用可 |
| Step 3（保留）| 非RACE | — | is_outlap 導出 + session 内ゲート整備後 |

- **FAIL（16）は採用しない**（§2 参照）。
- Step 1 だけでも ROUND3/RACE1 の #52/#77 は採用される（=Workbench 空欄解消）。

### 1c. 反映スクリプト案（**新規** `apply_pdf_v2_staging.py` / 要承認後に作成）

- 入力 = `/tmp/ts24_pdf_v2_scratch.db`（Gate 済み）。出力 = 正本DB内 `pdf_lap_times_v2_staging`。
- 手順（冪等）:
  1. **事前バックアップ**: `02_DATABASE/_backup_pdf_v2_staging_<TS>/ts24_unified.db`（§19b/§20b と同方式）。
  2. **before カウント**: 業務テーブル件数を `mode=ro` で記録。
  3. `CREATE TABLE IF NOT EXISTS` + UNIQUE INDEX（業務テーブルに `ALTER` しない）。
  4. `gate_status='PASS'`（Step 1 は **session_type IN ('RACE1','RACE2')** で限定）を
     **`INSERT OR REPLACE`**（自然キー）で投入。**NULL は既存を上書きしない方針**だが、本テーブルは
     v2 専用の新規テーブルゆえ各 round-session 単位の full-replace（DELETE→INSERT）でも安全。
  5. **after カウント**: 業務テーブル件数が **before==after** であることを assert（変化したら中止・ロールバック）。
  6. 反映サマリ（投入 rider-session 数 / lap 行数 / seg 充填率）を `reports/` に出力。
- **冪等性**: 再実行で同一結果（自然キー UNIQUE + REPLACE）。

### 1d. ロールバック方針

- `pdf_lap_times_v2_staging` は**新規テーブル**のため、ロールバック = `DROP TABLE pdf_lap_times_v2_staging`
  （業務テーブルへ一切影響なし）。加えて 1c-1 のフル DB バックアップを保持。
- Workbench 参照切替（§3）を未実施なら、staging を作っても**現行 Workbench の挙動は不変**（誰も読まない）。
  → **staging 反映と Workbench 切替は別承認・別タスクに分離**でき、リスクを段階化できる。

---

## 2. FAIL / results-only / WARNING の扱い案

### 2a. FAIL（16・正本へ採用しない）
| 種別 | 件数 | 扱い |
|---|---:|---|
| **results-only**（原文 Chronological に per-lap 無し。例 #73）| 11 | per-lap は**存在しないので作らない**。Workbench 品質表示に「results-only（PDFに明細なし）」と明示。必要なら `race_results` の pos/best/laps を**summary としてのみ**別表示（捏造しない）。|
| **完全欠落**（ROUND6 RACE2 #63/#87）| 2 | 別途原因調査（results-only か別レイアウトか）。隔離継続。|
| **best差 >0.5s**（#61=8.0s 等）| 2 | 手動レビュー。race_results 側のデータ品質疑い or 特殊レース。解消まで不採用。|
| **lap数差 ≥2**（#32 v2=2/rr=12）| 1 | 部分抽出。原因調査まで不採用。|

### 2b. WARNING の扱い
- **RACE の WARNING(69)**: ラップ自体は実データ。
  - `extra`(35) = v2 にあり race_results に無いライダー → 採用可だが「真値照合なし」を flag。
  - `G5 range外`(34) = RET ライダーの in-lap 等の遅いラップ → 実ラップなので採用可、flag のみ。
  - → **Step 2 として PASS と同じ table に flag(`gate_status='WARNING'`)付きで採用可**（除外すると実ラップを失う）。
- **非RACE の WARNING(736)**: 主因 `extra`(714) = race_results が非RACEを網羅しない（真値モデル不適合）。
  - **race_results 依存 Gate を非RACE に適用しない**。代わりに **session 内整合ゲート**（sum(seg)≈lap_time /
    lap_no 連番 / best が session 内妥当 / is_outlap 導出後に out/in 除外）を設計してから採用判断。
  - 現時点では**非RACE は保留**（現行 `pdf_lap_times` の非RACE データはそのまま温存）。

---

## 3. Workbench `RaceAnalysisTab` 参照切替 — 最小変更案（要承認・UI変更）

### 3a. 現状の参照（`ts24_workbench.py`）
`RaceAnalysisTab` は `pdf_lap_times` を **11 箇所のSQLリテラル**で直接参照:
L4935 / L4937 / L4957 / L4960（round/session メタ・rider 一覧）, L4984（rider 一覧）,
L5132 / L5210 / L5283 / L5378 / L5448 / L5567（trend/table/gap/sector/round_best/statistics）。
使用列: `round, session_type, rider_num, rider_name, lap_no, lap_time_s, seg1..seg4, is_outlap, is_pit, is_cancelled`。
（セクター系は `seg1 IS NOT NULL` で start-lap を自然に除外 → v2 の seg=NULL 設計と整合）。

### 3b. 推奨案 A — 正本 VIEW で overlay（無回帰・最小コード）
- 正本DBに **VIEW** を作る（要承認・新規オブジェクト・業務テーブル不変）:

```sql
CREATE VIEW IF NOT EXISTS race_lap_detail AS
-- v2-PASS（+任意でWARNING）を優先、無い rider-session は旧 pdf_lap_times にフォールバック
SELECT round,circuit,session_type,date,position,rider_num,rider_name,lap_no,
       seg1,seg2,seg3,seg4,lap_time,lap_time_s,speed,local_time,
       is_outlap,is_pit,is_cancelled,
       source_file, extractor_version, gate_status, 'v2' AS source_tag
  FROM pdf_lap_times_v2_staging
 WHERE gate_status IN ('PASS')            -- Step2採用時は ('PASS','WARNING')
UNION ALL
SELECT p.round,p.circuit,p.session_type,p.date,p.position,p.rider_num,p.rider_name,p.lap_no,
       p.seg1,p.seg2,p.seg3,p.seg4,p.lap_time,p.lap_time_s,p.speed,p.local_time,
       p.is_outlap,p.is_pit,p.is_cancelled,
       p.source_file, NULL AS extractor_version, NULL AS gate_status, 'legacy' AS source_tag
  FROM pdf_lap_times p
 WHERE NOT EXISTS (                        -- v2 が採用済みの (round,session,rider) は旧を出さない
   SELECT 1 FROM pdf_lap_times_v2_staging s
    WHERE s.round=p.round AND s.session_type=p.session_type
      AND s.rider_num=p.rider_num AND s.gate_status IN ('PASS'));
```

- **Workbench 側の最小変更**: クラス定数 `RACE_LAP_SRC = "pdf_lap_times"` を 1 つ追加し、11 箇所の
  リテラル `pdf_lap_times` を `{self.RACE_LAP_SRC}`（f-string）に置換 → 切替は定数 1 行（`"race_lap_detail"`）。
- 利点: **非RACE は旧データのまま無回帰**、RACE は v2-PASS に自動切替。rider 一覧（L4984）も view 経由で
  #77 が出るようになる。`source_tag`/`gate_status` を品質表示に使える。

### 3c. 代替案 B — staging を直接参照（RACE限定・非推奨）
- `RACE_LAP_SRC="pdf_lap_times_v2_staging"`。実装は更に小さいが、**非RACE が空になり回帰**するため、
  view（案A）の方が安全。B を採るなら RACE タブ限定運用を別途明示する必要あり。

### 3d. データ品質表示（UI 追加案・最小）
- フィルタ中の (round, session) に対し、ヘッダ近傍に 1 行ステータス:
  `PDF lap source: v2 (PASS n / WARNING m) ・ legacy fallback k riders ・ missing/FAIL: #73(results-only) …`
- 併せて `source_file` / `extractor_version` / `generated_at` をツールチップ表示（来歴の可視化）。
- データ源 = view の `source_tag`/`gate_status` + `race_results` とのカバレッジ差分（FAIL/results-only 一覧）。
- **欠落を 0 で埋めない / 推測で補完しない**（§12 監査ルール遵守）。

---

## 4. 実行前に Tatsuki 承認が必要な操作（明示リスト）

1. 正本DB内 **`pdf_lap_times_v2_staging` テーブル作成 + PASS 行 INSERT**（§1c）＝**正本DBへの書込**。
2. 正本DB内 **VIEW `race_lap_detail` 作成**（§3b）＝**正本DBへの書込**。
3. **Workbench `ts24_workbench.py` の参照切替**（§3b 定数 + 11 箇所置換）＝コード変更・UI 挙動変更。
4. （Step2 を採る場合）WARNING 行の採用範囲拡大。
5. 上記反映後の **Supabase 反映／Excel・dashboard 再生成**の要否判断（今回スコープ外）。
6. origin push（全コミットは承認後に CLI で）。

---

## 5. 本作業（事前確認）での検証と遵守

- `pdf_v2_scratch_gate.py --all` を `mode=ro` で再実行 → **業務テーブル before==after 不変**を確認。
- `/tmp/ts24_pdf_v2_scratch.db` のみ生成。正本DB内 table/insert/update/delete は**一切なし**。
- Workbench コードは**未変更**（参照箇所の読み取りのみ）。Supabase/Phase 2B/MarkItDown/push は**なし**。
- 成果物: 本計画書 `reports/pdf_v2_canonical_staging_plan_20260627.md`。

## 6. 推奨する次の最小ステップ（承認時）
1. `apply_pdf_v2_staging.py` を作成し、**RACE PASS のみ**を正本 `pdf_lap_times_v2_staging` へ反映（業務テーブル不変を assert）。
2. VIEW `race_lap_detail`（PASS overlay）を作成。
3. Workbench を `RACE_LAP_SRC` 定数化し view 参照へ切替 + 品質表示を追加（GUI スモークテストは Tatsuki がローカル実施）。
4. 問題なければ Step2(RACE WARNING) と 非RACE 向け is_outlap 導出 + session 内ゲートを別タスクで検討。
