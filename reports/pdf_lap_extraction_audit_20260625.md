# Result PDF Lap Extraction Audit — 20260625

read-only 監査（SQLite `mode=ro` / DB 書込なし）。scope = **round=ROUND3 session=RACE1**、対象 1 セッション。

## 0. 結論（コード監査・確定事項）

- Workbench `RaceAnalysisTab` は **`pdf_lap_times` のみ参照**（`ts24_workbench.py` L4518 ほか）。
  ライダー一覧も `SELECT DISTINCT rider_num FROM pdf_lap_times`（L4983-4987）のため、
  `pdf_lap_times` に行が無いライダー（例 #77 ROUND3/RACE1）は **選択肢に出ず空欄に見える**。
- `pdf_result_extractor_v2.write_to_db()` はラップ明細を **`pdf_lap_times_v2`** に書く設計（L461/L504）。
  だが正本DBに `pdf_lap_times_v2` は **存在しない**（v2 の `--laps --write` は正本へ未実行）。
- `apply_pdf_positions_v2.py` は `race_results` の position/best_lap を自然キー UPSERT するのみ。
  **ラップ明細（pdf_lap_times）は更新しない** → race_results=v2反映済 / pdf_lap_times=旧抽出 の不一致。
- 旧 `pdf_result_extractor.py` は `race_results` のみINSERT（pdf_lap_times を作らない）。
  現行 `pdf_lap_times` は別ビルド経路由来で、ライダー網羅・lap数ともに不完全。

## 1. Coverage summary（race_results vs pdf_lap_times）

| round | session | rr riders | pl riders | missing(rr→pl) | #77 | #52 |
|---|---|---:|---:|---:|---|---|
| ROUND3 | RACE1 | 34 | 19 | 15 | rr only | rr+pl |

- race_results にあって pdf_lap_times に無いライダー（全 field 合計）: **15**

## 2. Team riders（#77 / #52）が pdf_lap_times に欠落しているセッション

| round | session | rider | name |
|---|---|---:|---|
| ROUND3 | RACE1 | 77 | D.AEGERTER |

## 3. Lap-count 不一致（pdf valid != race_results.laps / 共通ライダー）

対象 19 件。pdf valid = is_outlap=0 かつ is_cancelled=0 の行数。

| round | session | rider | name | rr.laps | pl.valid | pl.total |
|---|---|---:|---|---:|---:|---:|
| ROUND3 | RACE1 | 3 | R.DE | 18 | 7 | 8 |
| ROUND3 | RACE1 | 7 | F.FARIOLI | 18 | 7 | 8 |
| ROUND3 | RACE1 | 10 | L.TACCINI | 18 | 7 | 8 |
| ROUND3 | RACE1 | 22 | A.CARRASCO | 18 | 7 | 8 |
| ROUND3 | RACE1 | 32 | O.BAYLISS | 18 | 7 | 8 |
| ROUND3 | RACE1 | 52 | J.ALCOBA | 18 | 7 | 8 |
| ROUND3 | RACE1 | 57 | A.MAHENDRA | 18 | 7 | 8 |
| ROUND3 | RACE1 | 5 | J.MASIA | 18 | 10 | 10 |
| ROUND3 | RACE1 | 53 | V.DEBISE | 18 | 10 | 10 |
| ROUND3 | RACE1 | 75 | A.ARENAS | 18 | 11 | 14 |
| ROUND3 | RACE1 | 31 | Y.OKAMOTO | 18 | 12 | 14 |
| ROUND3 | RACE1 | 50 | O.VOSTATEK | 18 | 12 | 14 |
| ROUND3 | RACE1 | 54 | R.ROSSI | 18 | 12 | 14 |
| ROUND3 | RACE1 | 4 | J.KENNEDY | 18 | 13 | 14 |
| ROUND3 | RACE1 | 40 | M.CASADEI | 18 | 13 | 14 |
| ROUND3 | RACE1 | 61 | C.ONCU | 18 | 13 | 14 |
| ROUND3 | RACE1 | 65 | P.OETTL | 18 | 13 | 14 |
| ROUND3 | RACE1 | 94 | L.MAHIAS | 18 | 13 | 14 |
| ROUND3 | RACE1 | 88 | A.GIOMBINI | 18 | 14 | 17 |

## 4. best_lap_s 乖離（|race_results.best - pdf valid MIN| > 0.5s）

対象 2 件。

| round | session | rider | name | rr.best_s | pl.best_s | diff_s |
|---|---|---:|---|---:|---:|---:|
| ROUND3 | RACE1 | 88 | A.GIOMBINI | 100.469 | 98.039 | 2.430 |
| ROUND3 | RACE1 | 22 | A.CARRASCO | 99.614 | 100.196 | 0.582 |

## 5. 具体例: ROUND3 / RACE1 / #77

- race_results: [(77, 'D.AEGERTER', 6, 18, 97.35, 'ROUND3_ASSEN_RACE1.pdf')]
- pdf_lap_times の #77 行数: **0**

## 6. v2 再パース比較（extract_pdf のみ・書込なし）

再パース対象: 1 PDF（上限 6）。
※ runtime 抑制のため一部スキップ（silent cap 回避のため明記）。全 scope=1 セッション。

| round | session | rider | v2.laps | v2.valid | v2.best_s | pl rows(DB) |
|---|---|---:|---:|---:|---:|---:|
| ROUND3 | RACE1 | 77 | 18 | 17 | 97.350 | 0 |
| ROUND3 | RACE1 | 52 | 18 | 17 | 97.457 | 8 |

## 7. is_outlap / is_pit / is_cancelled の扱い（pdf_lap_times・共通ライダー集計）

- is_outlap=1 行: 0 / is_pit=1 行: 0 / is_cancelled=1 行: 24
- Workbench のライダー一覧は `SELECT DISTINCT rider_num FROM pdf_lap_times`（フラグ無関係）。
  → 欠落の主因はフラグ除外ではなく **行自体の不在/不足**（§1-§3）。

## 8. 推奨する次作業（いずれも要 Tatsuki 承認・本監査では未実施）

1. **v2 を scratch table 化 + Gate**（推奨・最も安全）: `pdf_result_extractor_v2` で全 RACE/QP 等を
   `--all-riders --laps` 抽出し、`/tmp` か scratch DB の `pdf_lap_times_v2` に投入。
   `race_results.laps`/`best_lap_s` と突合する Gate（lap数一致・best乖離<閾値）を PASS した分のみ採用。
2. **Workbench を v2/scratch 参照可能にする**: Gate 通過後、`RaceAnalysisTab` の参照を
   `pdf_lap_times`（旧）→ 検証済みテーブルへ切替（UI 切替は別タスク・要承認）。
3. **旧 pdf_lap_times の直接修正は非推奨**: 取りこぼし由来で出所不明。上書きより Gate 付き再構築が安全。
   どうしても旧を使う場合も、まず本監査の不一致をゼロにする再抽出が前提。

> 本監査は read-only。pdf_lap_times / race_results / Supabase / Workbench 参照先はいずれも未変更。
