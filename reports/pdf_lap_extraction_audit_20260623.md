# Result PDF Lap Extraction Audit — 20260623

read-only 監査（SQLite `mode=ro` / DB 書込なし）。scope = **ALL**、対象 46 セッション。

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
| ROUND1 | FP1 | 33 | 0 | 33 | — | — |
| ROUND1 | QP | 33 | 0 | 33 | — | — |
| ROUND1 | RACE1 | 28 | 17 | 11 | rr only | rr+pl |
| ROUND1 | RACE2 | 48 | 19 | 29 | rr only | rr+pl |
| ROUND1 | SP | 2 | 23 | 0 | rr+pl | rr+pl |
| ROUND1 | WUP | 32 | 0 | 32 | — | — |
| ROUND1 | WUP1 | 2 | 19 | 0 | rr+pl | rr+pl |
| ROUND1 | WUP2 | 2 | 19 | 0 | rr+pl | rr+pl |
| ROUND11 | RACE1 | 33 | 18 | 15 | rr only | rr+pl |
| ROUND11 | RACE2 | 33 | 19 | 14 | rr only | rr only |
| ROUND11 | SP | 2 | 22 | 0 | rr+pl | rr+pl |
| ROUND11 | WUP2 | 2 | 22 | 1 | rr+pl | rr only |
| ROUND12 | RACE1 | 33 | 17 | 16 | rr+pl | rr+pl |
| ROUND12 | RACE2 | 30 | 14 | 16 | rr+pl | rr+pl |
| ROUND12 | SP | 2 | 27 | 0 | rr+pl | rr+pl |
| ROUND12 | WUP1 | 2 | 23 | 0 | rr+pl | rr+pl |
| ROUND12 | WUP2 | 2 | 22 | 0 | rr+pl | rr+pl |
| ROUND2 | FP1 | 33 | 0 | 33 | — | — |
| ROUND2 | FP2 | 31 | 0 | 31 | — | — |
| ROUND2 | QP | 32 | 0 | 32 | — | — |
| ROUND2 | RACE1 | 46 | 22 | 24 | rr+pl | rr+pl |
| ROUND2 | RACE2 | 49 | 19 | 30 | rr only | rr only |
| ROUND2 | SP | 2 | 20 | 1 | rr only | rr+pl |
| ROUND2 | WUP | 28 | 0 | 28 | — | — |
| ROUND2 | WUP1 | 2 | 19 | 1 | rr only | rr+pl |
| ROUND2 | WUP2 | 2 | 17 | 0 | rr+pl | rr+pl |
| ROUND3 | RACE1 | 34 | 19 | 15 | rr only | rr+pl |
| ROUND3 | RACE2 | 34 | 24 | 10 | rr only | rr+pl |
| ROUND3 | SP | 2 | 26 | 0 | rr+pl | rr+pl |
| ROUND3 | WUP1 | 2 | 25 | 0 | rr+pl | rr+pl |
| ROUND3 | WUP2 | 2 | 14 | 2 | rr only | rr only |
| ROUND4 | FP | 2 | 25 | 0 | rr+pl | rr+pl |
| ROUND4 | QP | 2 | 0 | 2 | rr only | rr only |
| ROUND4 | RACE1 | 33 | 16 | 17 | rr+pl | rr+pl |
| ROUND4 | RACE2 | 32 | 18 | 14 | rr+pl | rr+pl |
| ROUND4 | WUP1 | 2 | 15 | 2 | rr only | rr only |
| ROUND4 | WUP2 | 2 | 16 | 2 | rr only | rr only |
| ROUND5 | FP | 2 | 27 | 1 | rr only | rr+pl |
| ROUND5 | QP | 2 | 0 | 2 | rr only | rr only |
| ROUND5 | RACE1 | 32 | 19 | 13 | rr+pl | rr+pl |
| ROUND5 | RACE2 | 33 | 17 | 16 | rr+pl | rr+pl |
| ROUND5 | WUP1 | 2 | 31 | 0 | rr+pl | rr+pl |
| ROUND5 | WUP2 | 2 | 22 | 1 | rr+pl | rr only |
| ROUND6 | RACE2 | 2 | 21 | 0 | rr+pl | rr+pl |
| ROUND6 | WUP1 | 2 | 11 | 2 | rr only | rr only |
| ROUND6 | WUP2 | 2 | 21 | 1 | rr only | rr+pl |

- race_results にあって pdf_lap_times に無いライダー（全 field 合計）: **480**

## 2. Team riders（#77 / #52）が pdf_lap_times に欠落しているセッション

| round | session | rider | name |
|---|---|---:|---|
| ROUND1 | RACE1 | 77 | D.AEGERTER |
| ROUND1 | RACE2 | 77 | D.AEGERTER |
| ROUND11 | RACE1 | 77 | F.FARIOLI |
| ROUND11 | RACE2 | 52 | J.ALCOBA |
| ROUND11 | RACE2 | 77 | F.FARIOLI |
| ROUND11 | WUP2 | 52 | None |
| ROUND2 | RACE2 | 52 | J.ALCOBA |
| ROUND2 | RACE2 | 77 | D.AEGERTER |
| ROUND2 | SP | 77 | None |
| ROUND2 | WUP1 | 77 | None |
| ROUND3 | RACE1 | 77 | D.AEGERTER |
| ROUND3 | RACE2 | 77 | D.AEGERTER |
| ROUND3 | WUP2 | 52 | None |
| ROUND3 | WUP2 | 77 | None |
| ROUND4 | QP | 52 | None |
| ROUND4 | QP | 77 | None |
| ROUND4 | WUP1 | 52 | None |
| ROUND4 | WUP1 | 77 | None |
| ROUND4 | WUP2 | 52 | None |
| ROUND4 | WUP2 | 77 | None |
| ROUND5 | FP | 77 | None |
| ROUND5 | QP | 52 | None |
| ROUND5 | QP | 77 | None |
| ROUND5 | WUP2 | 52 | None |
| ROUND6 | WUP1 | 52 | None |
| ROUND6 | WUP1 | 77 | None |
| ROUND6 | WUP2 | 77 | None |

## 3. Lap-count 不一致（pdf valid != race_results.laps / 共通ライダー）

対象 258 件。pdf valid = is_outlap=0 かつ is_cancelled=0 の行数。

| round | session | rider | name | rr.laps | pl.valid | pl.total |
|---|---|---:|---|---:|---:|---:|
| ROUND2 | RACE1 | 6 | C.PEROLARI | 17 | 0 | 1 |
| ROUND2 | RACE1 | 88 | A.GIOMBINI | 17 | 0 | 1 |
| ROUND5 | RACE1 | 70 | J. WHATLEY | 19 | 2 | 3 |
| ROUND1 | RACE2 | 7 | Joshua BANNISTER | 17 | 1 | 1 |
| ROUND5 | RACE2 | 6 | C.PEROLARI | 19 | 3 | 3 |
| ROUND12 | RACE1 | 22 | A.CARRASCO | 17 | 2 | 2 |
| ROUND1 | RACE2 | 43 | S.JESPERSEN | 17 | 4 | 4 |
| ROUND2 | RACE1 | 52 | J.ALCOBA | 17 | 4 | 4 |
| ROUND2 | RACE2 | 16 | Jamie DAVIS | 17 | 4 | 4 |
| ROUND4 | RACE2 | 88 | A.GIOMBINI | 18 | 5 | 8 |
| ROUND5 | RACE2 | 31 | Y.OKAMOTO | 19 | 6 | 9 |
| ROUND5 | RACE2 | 88 | A.GIOMBINI | 19 | 6 | 9 |
| ROUND1 | RACE1 | 88 | A.GIOMBINI | 18 | 6 | 8 |
| ROUND11 | RACE1 | 31 | Y.OKAMOTO | 18 | 6 | 9 |
| ROUND12 | RACE1 | 37 | R.GARCIA | 17 | 5 | 5 |
| ROUND12 | RACE2 | 3 | R.DE | 17 | 5 | 5 |
| ROUND4 | RACE2 | 43 | S.JESPERSEN | 18 | 6 | 8 |
| ROUND4 | RACE2 | 73 | J.CRETARO | 18 | 6 | 8 |
| ROUND5 | RACE1 | 54 | R. ROSSI | 19 | 7 | 9 |
| ROUND5 | RACE2 | 10 | L.TACCINI | 19 | 7 | 11 |
| ROUND5 | RACE2 | 40 | M.CASADEI | 19 | 7 | 10 |
| ROUND1 | RACE1 | 7 | F.FARIOLI | 18 | 7 | 8 |
| ROUND1 | RACE1 | 10 | L.TACCINI | 18 | 7 | 8 |
| ROUND1 | RACE1 | 37 | R.GARCIA | 18 | 7 | 8 |
| ROUND1 | RACE1 | 43 | S.JESPERSEN | 18 | 7 | 8 |
| ROUND3 | RACE1 | 3 | R.DE | 18 | 7 | 8 |
| ROUND3 | RACE1 | 7 | F.FARIOLI | 18 | 7 | 8 |
| ROUND3 | RACE1 | 10 | L.TACCINI | 18 | 7 | 8 |
| ROUND3 | RACE1 | 22 | A.CARRASCO | 18 | 7 | 8 |
| ROUND3 | RACE1 | 32 | O.BAYLISS | 18 | 7 | 8 |
| ROUND3 | RACE1 | 52 | J.ALCOBA | 18 | 7 | 8 |
| ROUND3 | RACE1 | 57 | A.MAHENDRA | 18 | 7 | 8 |
| ROUND3 | RACE2 | 10 | L.TACCINI | 12 | 1 | 1 |
| ROUND3 | RACE2 | 54 | R.ROSSI | 12 | 1 | 1 |
| ROUND4 | RACE2 | 19 | A.KOFLER | 18 | 7 | 8 |
| ROUND5 | RACE2 | 7 | F.FARIOLI | 19 | 8 | 9 |
| ROUND1 | RACE2 | 52 | J.ALCOBA | 17 | 7 | 7 |
| ROUND11 | RACE1 | 24 | L.TACCINI | 18 | 8 | 9 |
| ROUND11 | RACE1 | 70 | J.WHATLEY | 18 | 8 | 9 |
| ROUND3 | RACE2 | 24 | M.RAMIREZ | 12 | 2 | 2 |
| ROUND3 | RACE2 | 64 | F.CARICASULO | 12 | 2 | 2 |
| ROUND3 | RACE2 | 73 | J.CRETARO | 12 | 2 | 2 |
| ROUND4 | RACE1 | 31 | Y.OKAMOTO | 18 | 8 | 8 |
| ROUND4 | RACE1 | 57 | A.MAHENDRA | 18 | 8 | 8 |
| ROUND4 | RACE1 | 64 | F.CARICASULO | 18 | 8 | 8 |
| ROUND4 | RACE1 | 73 | J.CRETARO | 18 | 8 | 8 |
| ROUND4 | RACE1 | 77 | D.AEGERTER | 18 | 8 | 8 |
| ROUND4 | RACE1 | 91 | B.JIMENEZ | 18 | 8 | 8 |
| ROUND4 | RACE2 | 10 | L.TACCINI | 18 | 8 | 8 |
| ROUND4 | RACE2 | 50 | O.VOSTATEK | 18 | 8 | 8 |

（先頭 50 件のみ表示。全 258 件。差が大きい順）

## 4. best_lap_s 乖離（|race_results.best - pdf valid MIN| > 0.5s）

対象 41 件。

| round | session | rider | name | rr.best_s | pl.best_s | diff_s |
|---|---|---:|---|---:|---:|---:|
| ROUND1 | RACE2 | 7 | Joshua BANNISTER | 93.680 | 111.296 | 17.616 |
| ROUND2 | RACE1 | 73 | Jack MAHAFFY | 91.026 | 107.217 | 16.191 |
| ROUND2 | RACE1 | 61 | C.ONCU | 90.231 | 104.979 | 14.748 |
| ROUND1 | RACE2 | 43 | S.JESPERSEN | 93.085 | 107.521 | 14.436 |
| ROUND2 | RACE1 | 19 | Harvey CLARIDGE | 91.865 | 105.263 | 13.398 |
| ROUND2 | RACE2 | 61 | C.ONCU | 90.849 | 103.751 | 12.902 |
| ROUND2 | RACE2 | 37 | R.GARCIA | 91.041 | 103.855 | 12.814 |
| ROUND2 | RACE2 | 19 | Harvey CLARIDGE | 91.995 | 104.676 | 12.681 |
| ROUND2 | RACE1 | 16 | Jamie DAVIS | 91.593 | 103.973 | 12.380 |
| ROUND2 | RACE2 | 43 | S.JESPERSEN | 91.887 | 103.981 | 12.094 |
| ROUND1 | WUP1 | 52 | None | 92.865 | 104.844 | 11.979 |
| ROUND2 | RACE1 | 7 | Joshua BANNISTER | 93.136 | 105.007 | 11.871 |
| ROUND2 | RACE2 | 16 | Jamie DAVIS | 92.176 | 103.969 | 11.793 |
| ROUND2 | RACE2 | 7 | Joshua BANNISTER | 93.068 | 104.131 | 11.063 |
| ROUND1 | RACE2 | 20 | X.CARDELUS | 102.436 | 93.816 | 8.620 |
| ROUND1 | RACE2 | 61 | C.ONCU | 85.203 | 93.205 | 8.002 |
| ROUND1 | WUP2 | 77 | None | 95.575 | 99.128 | 3.553 |
| ROUND5 | RACE1 | 22 | A. CARRASCO | 97.361 | 94.673 | 2.688 |
| ROUND4 | RACE1 | 22 | A.CARRASCO | 105.445 | 102.900 | 2.545 |
| ROUND3 | RACE1 | 88 | A.GIOMBINI | 100.469 | 98.039 | 2.430 |
| ROUND11 | RACE2 | 22 | A.CARRASCO | 102.333 | 99.969 | 2.364 |
| ROUND12 | RACE2 | 19 | J.DEL | 105.774 | 103.677 | 2.097 |
| ROUND12 | RACE1 | 63 | S.AZMAN | 104.765 | 103.434 | 1.331 |
| ROUND3 | RACE2 | 31 | Y.OKAMOTO | 99.242 | 100.531 | 1.289 |
| ROUND11 | RACE1 | 87 | A.GIOMBINI | 101.368 | 100.134 | 1.234 |
| ROUND1 | RACE1 | 54 | R.ROSSI | 94.545 | 93.457 | 1.088 |
| ROUND2 | RACE2 | 54 | R.ROSSI | 105.411 | 106.298 | 0.887 |
| ROUND1 | RACE2 | 31 | Y.OKAMOTO | 94.662 | 95.464 | 0.802 |
| ROUND2 | RACE2 | 50 | O.VOSTATEK | 104.600 | 105.373 | 0.773 |
| ROUND12 | RACE1 | 66 | N.TUULI | 103.307 | 104.051 | 0.744 |
| ROUND12 | RACE1 | 43 | S.JESPERSEN | 104.047 | 104.789 | 0.742 |
| ROUND2 | RACE1 | 31 | Y.OKAMOTO | 105.067 | 105.785 | 0.718 |
| ROUND2 | WUP1 | 52 | None | 103.871 | 104.583 | 0.712 |
| ROUND3 | RACE2 | 88 | A.GIOMBINI | 100.128 | 100.808 | 0.680 |
| ROUND2 | RACE1 | 91 | B.JIMENEZ | 105.770 | 106.436 | 0.666 |
| ROUND2 | RACE2 | 58 | M.JESUS | 105.253 | 104.612 | 0.641 |
| ROUND3 | RACE1 | 22 | A.CARRASCO | 99.614 | 100.196 | 0.582 |
| ROUND2 | RACE2 | 25 | O.KONIG | 104.974 | 105.536 | 0.562 |
| ROUND1 | RACE1 | 88 | A.GIOMBINI | 94.399 | 94.912 | 0.513 |
| ROUND12 | RACE1 | 31 | Y.OKAMOTO | 104.796 | 105.302 | 0.506 |
| ROUND3 | RACE2 | 61 | C.ONCU | 97.647 | 97.145 | 0.502 |

## 5. 具体例: ROUND3 / RACE1 / #77

- race_results: [(77, 'D.AEGERTER', 6, 18, 97.35, 'ROUND3_ASSEN_RACE1.pdf')]
- pdf_lap_times の #77 行数: **0**

## 6. v2 再パース比較（extract_pdf のみ・書込なし）

再パース対象: 6 PDF（上限 6）。
※ runtime 抑制のため一部スキップ（silent cap 回避のため明記）。全 scope=46 セッション。

| round | session | rider | v2.laps | v2.valid | v2.best_s | pl rows(DB) |
|---|---|---:|---:|---:|---:|---:|
| ROUND3 | RACE1 | 77 | 18 | 17 | 97.350 | 0 |
| ROUND3 | RACE1 | 52 | 18 | 17 | 97.457 | 8 |
| ROUND1 | RACE1 | 77 | 18 | 16 | 93.224 | 0 |
| ROUND1 | RACE1 | 52 | 18 | 16 | 93.125 | 14 |
| ROUND1 | RACE2 | 77 | 16 | 16 | 94.313 | 0 |
| ROUND1 | RACE2 | 52 | 17 | 17 | 93.443 | 7 |
| ROUND1 | SP | 77 | 17 | 16 | 93.408 | 11 |
| ROUND1 | SP | 52 | 17 | 16 | 93.159 | 12 |
| ROUND1 | WUP1 | 77 | 7 | 6 | 92.974 | 4 |
| ROUND1 | WUP1 | 52 | 7 | 6 | 92.865 | 1 |
| ROUND1 | WUP2 | 77 | 6 | 6 | 95.575 | 4 |
| ROUND1 | WUP2 | 52 | 6 | 6 | 93.586 | 1 |

## 7. is_outlap / is_pit / is_cancelled の扱い（pdf_lap_times・共通ライダー集計）

- is_outlap=1 行: 22 / is_pit=1 行: 49 / is_cancelled=1 行: 170
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
