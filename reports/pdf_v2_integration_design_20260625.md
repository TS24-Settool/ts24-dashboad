# Result PDF v2 ラップ明細 統合設計（P0 / 設計 + read-only 試験）— 2026-06-25

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-25 タスク）
ブランチ: `phase2a-extraction-20260620` / HEAD `f232e33`
位置づけ: **設計と read-only 試験のみ**。正本DB（業務テーブル）への書込・Workbench 参照先変更・
Phase 2B・origin push は本作業では一切行わない。

関連: §30 Result PDF 抽出精度監査 / `reports/pdf_lap_extraction_audit_20260623.md` /
Obsidian `05_DB_AUDIT/2026-06-23_pdf_lap_extraction_audit.md`

---

## 1. 解決したい問題（確定済み）

Workbench `RaceAnalysisTab` が参照する **`pdf_lap_times`（旧抽出）が不完全**で、Race Analysis に欠落が出る。

- `RaceAnalysisTab` は `pdf_lap_times` のみ参照（ライダー一覧も `SELECT DISTINCT rider_num FROM pdf_lap_times`）。
  → 行が無いライダーは選択肢に出ず空欄（例: ROUND3/RACE1/#77）。
- `pdf_result_extractor_v2.write_to_db()` はラップ明細を `pdf_lap_times_v2` に書く設計だが、
  正本DBに `pdf_lap_times_v2` は **存在しない**（v2 の `--laps --write` は正本へ未実行）。
- `apply_pdf_positions_v2.py` は `race_results` の position/best_lap のみ UPSERT（明細は触らない）。
  → `race_results`=v2反映済 / `pdf_lap_times`=旧抽出（ページ境界切断で不完全）の不一致。

---

## 2. read-only 試験結果（2026-06-25・新規証拠）

対象: `07_RESULTS/ROUND3_ASSEN_20260417/ROUND3_ASSEN_RACE1.pdf`（v2 `--dry-run`・`--write` 不使用）。

### 2a. 旧 `pdf_lap_times` の不完全さ（このセッション）

`pdf_lap_times` の ROUND3/RACE1 は、ほぼ全ライダーが **8 / 10 / 14 laps しか無い**（実際は18周レース）。
ページ境界切断（v2 が修正対象とした既知バグ）そのもの。

| 事象 | 旧 `pdf_lap_times` | `race_results`（正） | v2 再パース |
|---|---|---|---|
| #77 D.AEGERTER | **0 行（欠落）** | 18 laps / best 97.350 | 18 laps / valid17 / best 97.350 ✓ |
| #52 J.ALCOBA | **8 laps / best 97.823** | 18 laps / best 97.457 | 18 laps / valid17 / best 97.457 ✓ |
| 多数の field rider | 8〜14 laps に切断 | 18 laps | 18 laps ✓ |

→ 旧テーブルは欠落だけでなく **best_lap も誤り**（切断で真のベストを取りこぼす。#52 で 97.823 vs 正 97.457）。

### 2b. v2 vs `race_results` の整合（`--all-riders --dry-run`・全フィールド）

ROUND3/RACE1 の v2 抽出（33 riders）を `race_results`（34 riders）と突合:

- **lap_count 一致**: 完走勢は全員 18=18、途中棄権も一致（#37 v2=4 / rr=4、#64 v2=17 / rr=17、#19 v2=16 / rr=16）。
- **best_lap_s 一致**: フィールド全域で完全一致（#5 97.151 / #75 97.085 / #43 97.335 …）。
- **唯一の不一致 = カバレッジ**: `race_results` に存在する **#73（18 laps / best 99.252）を v2 が抽出できていない**
  （v2 出力に #73 が無い）。 chronological ヘッダ正規表現に乗らない等の取りこぼしと推定。

→ **結論**: v2 のラップ明細は高精度だが、**「v2 が race_results のライダーを取りこぼす」ケースが現に存在**する。
よって「v2 を無条件採用」ではなく、**`race_results` を真値基準にした Gate（特にカバレッジ照合）が必須**。

---

## 3. スキーマ・ギャップ分析（設計上の最重要ポイント）

`RaceAnalysisTab` が `pdf_lap_times` から実際に使う列と、v2 が出せる列にギャップがある。

### 3a. Workbench が必要とする `pdf_lap_times` 列（コード実測）

| 用途 | 使う列 | 箇所 |
|---|---|---|
| 行フィルタ | `is_outlap=0 AND is_cancelled=0 [AND is_pit=0]` | L5079-5080, 5134, 5212, 5285, 5380, 5450, 5569 |
| セクター分析チャート | `seg1, seg2, seg3, seg4`（`AND seg1 IS NOT NULL AND seg2 IS NOT NULL`） | L5282-5301 |
| ラップ/ベスト | `lap_time_s, lap_no, rider_num, position, round, session_type` | 各所 |

`pdf_lap_times` の全列: `id, round, circuit, session_type, date, position, rider_num, rider_name,
lap_no, seg1..seg4, lap_time, lap_time_s, speed, local_time, is_outlap, is_pit, is_cancelled,
source_file, imported_at, data_scope`。

### 3b. v2 が現状出せる列（`extract_pdf()` の lap dict）

`lap_no, lap_time, lap_time_s, is_cancelled` のみ。
**`seg1..seg4` / `speed` / `local_time` / `is_outlap` / `is_pit` は出さない。**

### 3c. ギャップの影響

| 列 | v2 | Workbench 影響 |
|---|---|---|
| `seg1..seg4` | ✗ | セクター分析チャート（L5282）が空になる（`seg1 IS NOT NULL` で全除外） |
| `is_outlap` | ✗ | 既定 0 扱い → **RACE は影響軽微**（周回全部が有効）だが、**FP/QP はアウト/インラップが混入** |
| `is_pit` | ✗ | ピット除外チェックが効かない（既定 0 → 全周採用） |
| `speed` / `local_time` | ✗ | 現 Race Analysis では未使用（情報損失のみ） |

→ **設計判断（Tatsuki 承認事項）**: 下記いずれか。
- **(A) v2 を拡張**して `seg1..seg4` / `speed` / `local_time` も収集し、`is_outlap`/`is_pit` を導出
  （v2 は seg/speed/localtime 行を読んでいるが現在は捨てている。収集は実装で可能）。**完全互換・推奨**。
- **(B) staging は NULL 許容**でローンチし、不足列は NULL。Workbench は `seg1 IS NOT NULL` 等で安全に degrade。
  実装は軽いが、**セクター分析が使えない**ため Race Analysis の機能後退になる。

---

## 4. scratch / staging table 設計案

### 4a. 命名・隔離
- staging 名: **`pdf_lap_times_v2_staging`**（正本の業務テーブル名 `pdf_lap_times` とは別。Workbench は当面参照しない）。
- まず **`/tmp/ts24_pdf_v2_scratch.db`** に生成し read-only で検証（正本DBには触れない）。
  Gate PASS かつ Tatsuki 承認後にのみ、正本DB内へ `*_staging` として移す（別タスク）。

### 4b. スキーマ（`pdf_lap_times` 互換 + 来歴列）

```sql
CREATE TABLE pdf_lap_times_v2_staging (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round         TEXT,
    circuit       TEXT,
    session_type  TEXT,
    date          TEXT,
    position      INTEGER,
    rider_num     INTEGER,
    rider_name    TEXT,
    lap_no        INTEGER,
    seg1 REAL, seg2 REAL, seg3 REAL, seg4 REAL,   -- 案(A)で充填 / 案(B)では NULL
    lap_time      TEXT,
    lap_time_s    REAL,
    speed         REAL,                            -- 案(A)で充填 / 案(B)では NULL
    local_time    TEXT,                            -- 案(A)で充填 / 案(B)では NULL
    is_outlap     INTEGER DEFAULT 0,               -- 案(A)で導出 / 案(B)では 0 既定
    is_pit        INTEGER DEFAULT 0,
    is_cancelled  INTEGER DEFAULT 0,
    source_file   TEXT,                            -- 来歴: 元PDFパス
    extractor_version TEXT,                        -- 来歴: 例 'pdf_result_extractor_v2'
    generated_at  TEXT,                            -- 来歴: 抽出時刻
    gate_status   TEXT,                            -- 'PASS' / 'WARNING' / 'FAIL'（Gate結果を行に保持）
    data_scope    TEXT DEFAULT 'TS24_PRIVATE'
);
-- 自然キー（重複防止 / 冪等 UPSERT 用）
CREATE UNIQUE INDEX IF NOT EXISTS ux_pdf_v2_staging
  ON pdf_lap_times_v2_staging(round, session_type, rider_num, lap_no, date);
```

自然キーは §1c の `lap_times` 系（round, session_type, rider, lap_no, +date）に整合させる。

---

## 5. Gate 条件（PASS / WARNING / FAIL 判定案）

判定単位 = **(session, rider)**。真値基準 = `race_results`（v2 の順位反映済み・§18a）。

| # | チェック | 条件 | 違反時 |
|---|---|---|---|
| G1 | **カバレッジ** | `race_results` に居る rider が v2 にも居る | FAIL（例: #73 欠落を検出）|
| G2 | **lap_count 整合** | `count(v2 valid laps)` と `race_results.laps` の差 ≤ 1 | 差=1→WARNING / 差≥2→FAIL |
| G3 | **best_lap 整合** | `min(v2 valid lap_time_s)` と `race_results.best_lap_s` の差 ≤ 0.05s | 0.05〜0.5→WARNING / >0.5→FAIL |
| G4 | **lap_no 重複なし** | 同 (session,rider) で lap_no 一意 | FAIL |
| G5 | **物理レンジ** | valid lap_time_s が circuit 妥当域内（例: best×0.97 〜 best×1.6） | 範囲外→WARNING（is_outlap 疑い）|
| G6 | **来歴必須** | source_file / extractor_version / generated_at が非NULL | FAIL |

- **FAIL は正本に絶対採用しない**（§20c の鉄則）。WARNING は採用可だが `data_quality_log` に `gate_*` で記録し可視化。
- `valid` = `is_cancelled=0 AND is_outlap=0`（案B では is_outlap 不在のため is_cancelled のみ。RACE では実質同等）。
- Gate 結果は ① 行の `gate_status` 列、② `data_quality_log`（check_name=`gate_pdf_v2_coverage` 等）の二重で残す。

### 5a. ROUND3/RACE1 への適用シミュレーション（read-only 実測ベース）
- G1: **#73 が FAIL**（v2 欠落）。他 33 riders PASS。
- G2/G3: 完走勢は lap_count・best ともに 0 差 → PASS。途中棄権（#37/#64/#19）も一致 → PASS。
- → このセッションは「#73 を FAIL 隔離 + 残りを採用候補」に分類される。**#73 は別途、原因調査（正規表現取りこぼし）対象**。

---

## 6. MarkItDown 利用可否

- **現状: ローカル未インストール**（`python3 -c "import markitdown"` → `ModuleNotFoundError` / `which markitdown` → なし）。
- **PyMuPDF (fitz) 1.26.5 は利用可能**（v2 抽出器が依存・稼働確認済み）。
- 方針: **network install は Tatsuki 承認が必要**（INBOX 禁止事項）。本作業では導入せず。
- 監査補助としての位置づけ（承認後の検討案）:
  - MarkItDown で Result PDF を Markdown 化し、v2 parser の**取りこぼし検出の二次テキストソース**として使う
    （例: G1 で FAIL した #73 が MarkItDown 出力に現れるかを照合）。
  - **MarkItDown 出力を正本抽出器にはしない**（TS24 専用 parser + Gate を主とする）。LLM 推測補完も禁止。
  - 当面は **fitz だけで G1 のカバレッジ照合は可能**（PDF 全文に rider_num/name が出るかを grep 照合）なので、
    MarkItDown 無しでも #73 取りこぼし原因の一次切り分けは進められる。

---

## 7. 実装手順（Tatsuki 承認後・本作業では未実施）

1. **v2 拡張（案A採用時）**: `extract_pdf()` の lap dict に `seg1..seg4`/`speed`/`local_time` 収集と
   `is_outlap`/`is_pit` 導出を追加（既に読んでいる seg/speed/localtime 行を捨てずに保持）。`--dry-run` で回帰確認。
2. **scratch 生成**: `/tmp/ts24_pdf_v2_scratch.db` に `pdf_lap_times_v2_staging` を作り、
   全 RACE/QP/SP 等を `--all-riders --laps` で投入（正本DBは読み取りのみ）。
3. **Gate 実行**: G1〜G6 を回し、各行 `gate_status` 設定 + `data_quality_log` へ `gate_*` 記録。
   サマリレポート（PASS/WARNING/FAIL 件数・FAIL 一覧）を `reports/` に出力。
4. **#73 等 FAIL の原因調査**: 取りこぼしライダーの chronological ヘッダ正規表現を補修（必要なら MarkItDown 照合）。
5. **承認待ち**: ここまで正本DB未反映。Tatsuki が Gate サマリを確認し、正本へ `*_staging` 配置を承認。
6. **正本反映（別タスク・要承認）**: PASS 行のみ正本DB内 `pdf_lap_times_v2_staging` へ UPSERT（NULL 上書き禁止）。
7. **Workbench 参照切替（さらに別タスク・要承認・UI変更）**: `RaceAnalysisTab` を検証済みテーブル参照に変更
   （旧 `pdf_lap_times` 直接修正は非推奨）。データ品質ステータス表示（欠落rider/Gate結果）も併せて設計。

---

## 8. 本作業での遵守（禁止事項）

- `pdf_lap_times` / `race_results` の書込・削除なし。
- v2 の正本DB流し込みなし（`--write` 不使用・`--dry-run` のみ）。staging テーブルも正本には未作成。
- Workbench 参照先変更なし。Supabase cleanup/sync なし。Phase 2B 未着手。origin push なし。
- MarkItDown の network install なし（要承認）。LLM 推測でのラップ補完なし。NULL/欠落の 0 化なし。

## 9. 成果物
- 本設計レポート（`reports/pdf_v2_integration_design_20260625.md`）。
- Obsidian: `05_DB_AUDIT/2026-06-25_pdf_v2_integration_design.md`（要約 + 判断事項）。
- `CLAUDE.md` §31。`AI_HANDOFF_LATEST` / `CURRENT_STATE` / `log` / INBOX Result 更新。

## 10. Tatsuki への判断事項
1. **スキーマ方針 (A) v2拡張（完全互換・推奨）か (B) NULL許容ローンチ（軽量・セクター後退）か。**
2. **Gate 閾値**（G2 lap差 ≤1 / G3 best ≤0.05s）の妥当性。
3. MarkItDown 導入可否（承認すれば二次照合に使用、否なら fitz のみで進行）。
4. #73 のような v2 取りこぼしの扱い（FAIL 隔離のまま保留 / 正規表現補修を優先実装）。
