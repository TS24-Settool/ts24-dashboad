# Result PDF v2 staging 反映 dry-run — 2026-06-29 15:24

**dry-run（正本DBは `mode=ro`・無変更）**。`apply_pdf_v2_staging.py`（`--apply` 無し）。
対象: `session_type IN ('RACE1', 'RACE2')` かつ `gate_status IN ('PASS',)`。 入力 scratch=`/tmp/ts24_pdf_v2_scratch.db`。反映先(承認後)=正本DB内 **新規** `pdf_lap_times_v2_staging`。

## 投入予定サマリ

- 投入予定 lap 行数: **7710**
- 投入予定 rider-session 数: **461**
- seg 充填行: 6165（80.0%・スタートラップ等は NULL=正常）

## 検証（投入前チェック）

| 検査 | 結果 | 判定 |
|---|---:|:--:|
| 自然キー重複（候補内） | 0 | ✅ |
| date NULL/空 行 | 0 | ✅ |
| lap_time_s NULL 行 | 0 | ✅ |
| 来歴欠落行（source/extractor/generated）| 0 | ✅ |
| 物理レンジ外 valid lap（best×[0.9,1.6]） | 0 | ✅ |

## ラウンド×セッション別 内訳

| round | session | rows | riders | seg_rows |
|---|---|---:|---:|---:|
| ROUND1 | RACE1 | 404 | 24 | 380 |
| ROUND1 | RACE2 | 105 | 6 | 99 |
| ROUND11 | RACE1 | 528 | 31 | 494 |
| ROUND11 | RACE2 | 541 | 31 | 509 |
| ROUND12 | RACE1 | 498 | 31 | 466 |
| ROUND12 | RACE2 | 470 | 30 | 440 |
| ROUND2 | RACE1 | 515 | 31 | 484 |
| ROUND2 | RACE2 | 491 | 30 | 461 |
| ROUND3 | RACE1 | 541 | 31 | 510 |
| ROUND3 | RACE2 | 396 | 33 | 363 |
| ROUND4 | RACE1 | 491 | 29 | 461 |
| ROUND4 | RACE2 | 508 | 29 | 479 |
| ROUND5 | RACE1 | 532 | 29 | 503 |
| ROUND5 | RACE2 | 566 | 32 | 516 |
| ROUND6 | RACE2 | 30 | 2 | 0 |
| ROUND7 | RACE1 | 528 | 30 | 0 |
| ROUND7 | RACE2 | 566 | 32 | 0 |

## 正本DB業務テーブル（dry-run: 無変更を確認）

| table | before | after | 不変 |
|---|---:|---:|:--:|
| runs | 275 | 275 | ✅ |
| laps | 1202 | 1202 | ✅ |
| lap_suspension | 1202 | 1202 | ✅ |
| race_results | 866 | 866 | ✅ |
| pdf_lap_times | 7613 | 7613 | ✅ |

## 生成 SQL

- レビュー用 SQL: `reports/pdf_v2_staging_ddl_20260627.sql`
  （staging DDL + UNIQUE INDEX + INSERT テンプレート + 参考 VIEW。VIEW は別承認・本スクリプト不実行）

## 承認後に Tatsuki が実行するコマンド（案）

```bash
# 1) RACE PASS を正本 staging へ反映（事前バックアップ + before==after assert 付き）
python3 apply_pdf_v2_staging.py --apply
# 2) （別承認）Workbench 切替用 VIEW を作成 → その後 Workbench を RACE_LAP_SRC=race_lap_detail に
#    VIEW SQL は reports/pdf_v2_staging_ddl_20260627.sql の (3) を参照
```

> `--apply` は正本DBへ書き込む（新規 staging テーブル作成 + INSERT）。業務テーブルは不変（before==after を assert・違反時 rollback）。VIEW 作成と Workbench 切替は別タスク・別承認。