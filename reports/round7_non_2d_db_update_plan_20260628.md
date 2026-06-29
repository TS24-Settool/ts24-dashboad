# ROUND7 (MISANO) 非2Dデータ DB 反映計画 + 新システム検証（dry-run / read-only）

担当: Claude Code（Obsidian `00_INBOX/FOR_CLAUDE_CODE.md` 2026-06-28 タスク）
ブランチ: `phase2a-extraction-20260620`。位置づけ: **棚卸し・差分監査・dry-run 検証・反映計画のみ**。
正本DB書込・Supabase・Excel/dashboard 再生成・origin push・2D 取込は**一切行っていない**。

---

## 1. 新規/更新ファイル棚卸し（2026-06-28・read-only）

| ファイル | size | sha256(先頭16) |
|---|---:|---|
| `01_REPORTS/JA52/20260612-ROUND7-JA52.xlsx` | 256951 | 4c54a466e13c6239 |
| `04_REFERENCE/Data_Base_TS24_ORIGINAL.xlsx` | 49922 | de6ce565ca9f63f3 |
| `07_RESULTS/ROUND7_MISANO_20260612/20260612-ROUND7-FP.pdf` | 401972 | feffb41ed10a2207 |
| `…/20260612-ROUND7-QP.pdf` | 521579 | 74a40fe02afebad3 |
| `…/20260612-ROUND7-RACE1.pdf` | 737093 | 3697e2318d07ead5 |
| `…/20260612-ROUND7-RACE2.pdf` | 740668 | d44d3965ca7ef8c2 |
| `…/20260612-ROUND7-WUP1.pdf` | 372627 | 0ebafb2b6185d78d |
| `…/20260612-ROUND7-WUP2.pdf` | 376415 | 21fc83590d083e34 |

## 2. 2D data 不在確認（今回対象外の根拠）

- `DATA 2D/` の最新は **`20260529-ROUND6-*`**。ROUND7 / MISANO / 2026-06-12 相当の 2D data は**存在しない**。
- 従って **`runs` / `laps` / `lap_suspension` および 2D 由来 raw/derived 指標は今回反映対象外**。
  これらは 2D outing をキーに生成されるため、2D 不在では新規作成・推測補完しない（捏造禁止）。

## 3. アクティブ DB ターゲット

| ターゲット | 役割 | 今回 |
|---|---|---|
| `02_DATABASE/ts24_unified.db` | 正本 | 非2D のみ反映候補（要承認・本計画は dry-run） |
| `02_DATABASE/TS24 DB Master.xlsx` | 派生レポート | 反映後に安全再生成（別承認） |
| Supabase | cloud mirror | 差分監査・提案のみ（自動 sync しない） |
| `ts24_master.db` / `ts24_setup.db` / `ts24_unified.old.db` / backup配下 | 旧/中間/backup | **更新対象外** |

## 4. 新システム検証（ROUND7 Result PDF v2 system validation）

### 4a. v2 extractor（6 PDF・例外なし）
全6 PDF が例外なく解析でき、meta も正検出（round=ROUND7 / circuit=MISANO / session_type / date=2026-06-12）。

| session | riders | laps |
|---|---:|---:|
| FP | 34 | 571 | 
| QP | 34 | 561 |
| RACE1 | 33 | 569 |
| RACE2 | 33 | 572 |
| WUP1 | 34 | 176 |
| WUP2 | 33 | 186 |

### 4b. ★MISANO レイアウト差を検出 → extractor を安全側に修正
- **検出**: MISANO の Chronological は ASSEN と版が異なり、① 速度がローカルタイムと同一行
  （`240,0 14:04'03.535`）② セグメントが結合行に複数入る等で **セグメント読み順がラップ間で不安定**。
  → 修正前は **speed が取れず**、4セグ揃ったラップは **誤った sector ラベルで写像されるリスク**があった。
- **修正（`pdf_result_extractor_v2.py`・read-only 側のみ）**:
  - 速度を両レイアウトで取得（専用行＝ASSEN系 / ローカルタイム同一行＝MISANO系）。
  - **PDF 単位でレイアウト判定**（`_SPEED_LOCALTIME` 検出で MISANO 系 → `seg_trust=False`）。
    MISANO 系は **seg1..seg4 を写像せず NULL**（誤割当を回避）。lap_no/lap_time/best/is_cancelled/is_pit/speed は両系で取得。
- **再検証（seg_sum_bad=0・無回帰）**:
  | PDF | layout | seg 充填 | speed 充填 |
  |---|---|---|---|
  | ASSEN R3 RACE1 #77/#52/#5 | assen | 17/18 | 17–18 |
  | BALATON R4 / JEREZ R12 | assen | 16–17 | 17–18 |
  | **MISANO R7 RACE1/2 #77/#52** | **misano** | **0（安全NULL）** | **17** |
  - ASSEN で一旦 16 に減った #77 も、PDF 単位判定へ切替えて **17 に復帰**（速度欠落ラップ L7 を誤って MISANO 扱いしない）。

### 4c. Gate（`pdf_v2_scratch_gate.py --all`・51 PDF）
- **正本DB業務テーブル before==after 不変**（runs275/laps1202/lap_suspension1202/race_results792/pdf_lap_times7613）。
- 集計: PASS **425** / WARNING **1006** / FAIL **16**。**既存ラウンドは無回帰**（PASS425・FAIL16 は ROUND7 追加前と同一。
  増分 +201 WARNING はすべて ROUND7）。
- **ROUND7 は全セッション WARNING（truth='–'）**。理由 = **`race_results` に ROUND7 行が 0**（真値が無い）ため
  全ライダーが「extra（race_results に該当なし）」判定。FAIL ではない（lap データ自体は健全）。

### 4d. apply dry-run（RACE PASS 反映候補）
- `apply_pdf_v2_staging.py`（dry-run）= **6616 行 / 399 rider-session（既存ラウンドのみ）**。
  **ROUND7 PASS 行 = 0**（truth 無しで WARNING のため対象外）。正本DB業務テーブル不変。
  → **ROUND7 lap 明細は、先に race_results を入れない限り staging 反映対象にならない**（正しい挙動）。

## 5. Original / Report 差分監査（read-only）

- **`Data_Base_TS24_ORIGINAL.xlsx`**: 単一シート `DATA`（260×37）。**MISANO 行あり**＝ROUND7 setup の照合元
  （§1b 原本照合ルールの権威源）。canonical の `runs` は 2D outing 由来のため、**2D 不在の現状では Original の
  MISANO setup を `runs` に反映できない**（照合参照に留まる）。
- **`20260612-ROUND7-JA52.xlsx`**: シート `DAY1`/`DAY2`/`REPORT`（標準 import 形式・`ts24-report-import` スキル対応）。
  ROUND7/MISANO/2026-06-12 を含む。Report からコメント/run 構造/weekend summary/setup 変更/problem 候補は
  抽出可能だが、`problem_log`/`setup_decision_log` は **run_id（2D outing 由来）にキー付く**ため、2D 不在では
  run へ紐付けできない。`DAY1` に `20260612-ROUND7-JA57` という表記ゆれセルあり（要目視確認）。

## 6. 反映可否（テーブル別）

| テーブル | 反映可否（2D 不在） | 根拠 / 手順 |
|---|---|---|
| `race_results` | **可（最優先）** | Result PDF（非2D）。v2 extractor が6 PDF を例外なく解析。**ROUND7 の真値はこれで初めて成立** |
| pdf lap 明細（v2 staging） | race_results 成立後に可 | Gate は race_results を真値にするため、race_results 反映後に ROUND7 RACE が PASS 判定可能になる |
| `source_file_registry`/`import_queue` | 可（管理テーブル・非破壊） | §24 の scan で ROUND7 PDF/Report を登録（業務テーブル不変） |
| `runs` / `laps` / `lap_suspension` | **不可（2D 不在）** | 2D outing 由来。新規作成・推測補完しない |
| `problem_log` / `setup_decision_log` | 保留 | run_id（2D）にキー付くため 2D 反映後。Report 由来コメントは別途検討 |
| Original 由来 setup | 保留（照合参照のみ） | runs が無いため反映先が無い。2D 反映時に §1b で照合 |

## 7. 反映順序案（各ステップ dry-run → Tatsuki 承認 → apply）

1. **管理テーブル更新**（任意・非破壊）: `extraction_scan.py` で ROUND7 PDF/Report を registry/queue に登録。
2. **`race_results` 反映**（非2D・要承認）: ROUND7 6 PDF を既存 import 経路で `race_results` へ。
   - 既存資産: `pdf_result_extractor_v2.write_to_db()`（race_results 書込）/ `apply_pdf_positions_v2.py`（自然キー UPSERT）/
     `import_all_race_results.py`。**自然キー §1c**（round_no,circuit,session_type,rider_no,position）。
   - 反映前に dry-run 差分（追加予定行数・既存重複・best/laps 妥当性）→ before/after race_results 件数 assert。
3. **pdf lap 明細 staging**（要承認）: race_results 成立後、`pdf_v2_scratch_gate.py` 再実行で ROUND7 RACE が
   PASS 判定可能 → `apply_pdf_v2_staging.py --apply` の対象に含める（MISANO は seg NULL・lap/best/speed は有効）。
4. **`TS24 DB Master.xlsx` 安全再生成**（別承認）: `refresh_db_master_safe.py`（§29）。
5. **Supabase sync**（別承認）: `supabase_audit.py` で差分監査 → 提案のみ。自動実行しない。

各ステップ: rollback 方針（race_results は事前フル DB バックアップ + 自然キー UPSERT は COALESCE で既存保護 /
staging は新規テーブルゆえ DROP で巻き戻し）、自然キー、重複判定、before/after 件数を明記する。

## 8. 2D 不在により未反映にすべき値（明示）

- `laps` の 2D lap time、`lap_suspension`（全列）、APEX/BRAKING/CORNER_EXIT/DAMPING 等の 2D 由来指標、
  zone 速度 5 指標、phase/telemetry metrics。**いずれも ROUND7 では作成しない**（2D 到着後）。

## 9. apply 前に Tatsuki 承認が必要な操作

1. ROUND7 `race_results` 反映（正本書込）。
2. ROUND7 pdf lap 明細 staging 反映（`apply_pdf_v2_staging.py --apply`・正本書込）。
3. `TS24 DB Master.xlsx` 安全再生成。
4. Supabase sync（提案後）。
5. `source_file_registry`/`import_queue` 更新（管理テーブルだが正本DBファイルへの書込）。
6. origin push。

## 10. 本作業の遵守（read-only / dry-run）

- 正本DB書込なし（race_results / pdf_lap_times / staging いずれも未作成・未更新、業務テーブル before==after 不変）。
- 2D 取込なし / 2D 由来値の作成なし / Supabase なし / Excel・dashboard 再生成なし / Phase 2B なし / origin push なし。
- 変更したコードは **`pdf_result_extractor_v2.py`（MISANO レイアウト対応・read-only 抽出器）** のみ。
- 出力: 本レポート / 再生成 `reports/pdf_v2_gate_20260628.md` / `reports/pdf_v2_staging_dry_run_20260627.md`。
