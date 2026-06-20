# Phase 2 — Extraction Pipeline 設計書

**作成:** 2026-06-20 / Claude Code（Tatsuki指示・複数エージェント実態調査に基づく）
**ステータス:** 設計（DESIGN ONLY）。本書は実装ではなく仕様。実装着手は Tatsuki 承認後。
**位置づけ:** Multi-Agent Data Quality Roadmap の Phase 2（CLAUDE.md §20c）。Phase 0-1（正本DB固定・品質5テーブル）完了が前提。

---

## 0. 設計思想 —「自動で入れる」より先に「自動で疑う」

Phase 2 は **新ファイルを自動で正本DBへ入れる仕組みではない**。
Phase 2 が自動化するのは **「検出」と「隔離」と「疑いの記録」まで**。正本DB反映（Phase 4）は
Quality Gate（Phase 3）PASS かつ Tatsuki 承認の後に限る。

- **正本DB（`02_DATABASE/ts24_unified.db`）には Phase 2 は一切書き込まない。** 書くのは管理4テーブル
  （`source_file_registry` / `import_queue` / `analysis_run_log` / `data_quality_log`）と scratch DB のみ。
- 検出した時点では **必ず「未検証(unverified)」**。`status` は `discovered` から始まり、Gate を通るまで前進しない。
- **「見つからない」より「黙って間違える」方が危険。** 検出漏れは検出ログで可視化し、誤検出・矛盾は FAIL/WARNING として残す。
- 既存の抽出・検証ロジック（`build_master_db.py` の `discover_outings`/`gated_outings`/受入ゲート §8、
  `report_importer.py`、`pdf_result_extractor_v2.py` 等）を **再利用する。作り直さない。** Phase 2 はそれらを
  「いつ・何に対して走らせるか」を管理するオーケストレーション層。

```
新ファイル                         ┌─────────── 正本DBには触れない ───────────┐
  ↓ 検出(watch/scan)
source_file_registry  ──登録──▶ import_queue ──▶ scratch DB 生成 ──▶ Quality Gate(Phase3)
  (discovered)                    (pending)        (/tmp, 隔離)        ├ PASS  ─▶ Phase4(承認後 正本反映)
                                                                       ├ WARN ─▶ 要確認(Tatsuki)
                                                                       └ FAIL ─▶ 隔離・正本到達禁止
                              すべての遷移を analysis_run_log / data_quality_log に記録
                                       ↓
                              Workbench「未処理データ」タブで可視化 → Tatsuki が判断
```

---

## 1. 監視対象（watch targets）

| 領域 | パス | 内容 | 検出単位 | 既存取込ロジック |
|---|---|---|---|---|
| 2Dロガー | `DATA 2D/{event}/…` | MES/LAP/HED/DDD + チャンネル分割(A*/C*) | **outing**（1走行）→ run → lap | `build_master_db.py: discover_outings()` |
| レポート | `01_REPORTS/{DA77,JA52,COMPANY}/*.xlsx` | DAY1/DAY2/REPORT シート（セットアップ・コメント・タイヤ） | **ファイル**（1レポート=1イベント） | `report_importer.py`（ステージング） |
| 公式結果 | `07_RESULTS/ROUND*/…`, `07_RESULTS/Company/…-RESULT-BSB/` | リザルトPDF / クロノPDF | **ファイル**（PDF）/ **フォルダ**（BSB一式） | `pdf_result_extractor_v2.py` / `parse_bsb_result_pdf.py` |

監視は **(a) オンデマンド scan（推奨・第一段）** と **(b) 常駐 watch（将来）** の2モードを想定。
Phase 2 初期は **scan モードのみ**（Tatsuki がデータ保存後に1コマンドで実行）。`ts24_watcher.py` 型の常駐は
誤検出・半端コピー検出の難しさがあるため Phase 2 後半の課題とする。

> **重要な実装要件（拡張子なしPDF）:** `07_RESULTS/` には拡張子の無い PDF 実体（例 `20260529-ROUND6-FP`）が
> 存在する。`rglob("*.pdf")` だけでは取りこぼす。検出は **ファイル先頭マジック `%PDF` でも判定**すること。

---

## 2. ファイル種別ごとの検出ルール

検出は「拡張子」だけに依存せず、**配置 tier + 必須随伴ファイル + 内容シグネチャ**で確定する。
誤検出を防ぐため、確信が持てないものは `file_type = 'unknown'` で登録し queue には載せない（疑う）。

### 2.1 DATA 2D（outing 検出 — 既存 `discover_outings()` を権威とする）

| tier | 配置 | 検出 | base 確定 |
|---|---|---|---|
| `nested` | `…/{base}.MES/` フォルダ | フォルダ名が `.MES` で終わる | フォルダ名から `.MES` 除去 |
| `copia` | `…/{base}.MES - Copia/` | フォルダ名に `.MES ` を含む | フォルダ内 `.DDD` の stem |
| `loose` | event 直下に `{base}.DDD` 直置き | `.DDD` の親が `.MES`系でない | `.DDD` の stem |

- **outing 成立の必須条件**: `{base}.DDD`（チャンネル辞書）と `{base}.LAP`（ラップマーカー）が揃うこと。
  `.LAP` 欠落は outing 不成立 → 検出ログに「不完全」記録、queue には載せない。
- **ノイズ除外**（既存 `NOISE` 正規表現を継承）: `ACCENSIONE` / `RD\d+-S\d+` / `-KAW_` / `^D0-` 等のテスト・内部記録。
- **HED 矛盾は検出時に疑う**: copia/loose で HED の Circuit がイベント基準サーキットと矛盾する場合
  （例: ROUND11 配下に Portimão HED の誤配置）、`status='gated'` で登録し queue を保留。HED は不確実（CLAUDE.md
  memory）なので **HED 単独でデータを捨てず、矛盾を記録して Tatsuki に上げる**。
- `.HED` は任意（メタ・Fastest lap 基準）。チャンネル分割 A*/C* は outing に内包（個別登録しない）。

### 2.2 01_REPORTS（Excel — ファイル単位）

- 検出: `01_REPORTS/**/*.xlsx`。
- 種別確定: 拡張子 `.xlsx` かつ **ヘッダ固定位置にメタが読めること**（B1=rider, H2=circuit, H3=round, D4=date,
  シート DAY1/DAY2/REPORT のいずれか）。読めなければ `unknown`。
- 命名規則の参考: `YYYYMMDD-{ROUNDx|TESTx}-{RIDER}.xlsx`。命名とヘッダが矛盾する場合は WARNING 記録（命名は参考、
  内容を優先）。
- COMPANY/BSB レポートは別ライダー体系 → `file_type='report_company'` で区別。

### 2.3 07_RESULTS（PDF — ファイル/フォルダ単位）

- 検出: `07_RESULTS/**/*.pdf` **＋ 拡張子なしで先頭が `%PDF` のファイル**。
- 種別確定: PDF 本文に "Chronological Analysis" 等があれば `result_chrono`（ラップ全数）、無ければ `result_classification`
  （順位・ベストのみ）。BSB は `…-RESULT-BSB/` フォルダ単位で `result_bsb`。
- セッション種別はファイル名＋本文から推定（FP/QP/SP/WUP1/WUP2/RACE1/RACE2）。推定失敗は WARNING。

> いずれの種別も、**検出＝確定ではない**。`source_file_registry.file_type` は「検出器の推定」であり、
> Quality Gate と Tatsuki が最終確定する。

---

## 3. source_file_registry 運用

Phase 1 で作成済（CLAUDE.md §20b）。Phase 2 での運用ルール。

| 列 | Phase 2 での使い方 |
|---|---|
| `file_id` | 安定ID。`sha256` 先頭16桁 + 短縮パス、または outing は `{event}/{base}` 由来の決定論キー |
| `file_path` | リポジトリ相対 or 絶対（DATA 2D は outing 代表 = `.DDD` のパス） |
| `file_type` | 2.x の検出器が付与（`2d_outing` / `report` / `report_company` / `result_chrono` / `result_classification` / `result_bsb` / `unknown`） |
| `file_size` / `file_mtime` | 変更検出の一次フィルタ |
| `sha256` | **再検出時の同一性判定の本体**。size/mtime 一致でも hash 不一致なら「更新」扱いで再 queue |
| `rider/circuit/round/session` | 命名・HED・ヘッダから解析した推定メタ（NULL 可。確定値は正本側） |
| `discovered_at` | 検出時刻（ISO8601） |
| `status` | `discovered`→`queued`→`extracted`→`archived`。矛盾検出時は `gated`（保留）も使用 |
| `notes` | tier、HED矛盾、命名不一致、拡張子なしPDF 等の検出時メモ |

運用原則:
- **冪等**: 同一 `file_path` は UNIQUE。再 scan で size/mtime/sha256 が不変なら何もしない（既処理スキップ）。
- **更新検出**: sha256 変化＝ソース差し替え → `status` を `discovered` に戻し再 queue（再検証を強制）。
- **2D は outing 代表1行**で登録（随伴ファイル群はメモに件数のみ）。レポート/PDF は1ファイル1行。
- **削除/移動**: 既登録パスが消えた場合は `archived` にし、消さない（履歴を残す）。

---

## 4. import_queue status 遷移

Phase 1 で作成済。状態機械を以下に固定する。

```
                       (検出器が登録)
        ┌──────────────────────────────────────────────┐
        ▼                                                │
   ┌─────────┐  取り出し   ┌────────────┐  scratch生成  ┌────────────────┐
   │ pending │ ─────────▶ │ processing │ ───────────▶ │ awaiting_gate  │
   └─────────┘            └────────────┘               └────────────────┘
        │ 検出器が              │ 抽出中エラー                │ Gate 実行(Phase3)
        │ 種別unknown/不完全     ▼                            ├─ PASS ─▶ ┌──────┐
        ▼                  ┌────────┐                        │          │ done │（Phase4で正本反映=承認後）
   ┌─────────┐            │ failed │◀──(抽出失敗)            │          └──────┘
   │ skipped │            └────────┘                        ├─ WARNING ▶ awaiting_gate のまま要確認フラグ
   └─────────┘                                              └─ FAIL ──▶ ┌────────┐
   (queueに載せない/対象外)                                              │ failed │（正本到達禁止・隔離）
                                                                         └────────┘
```

| status | 意味 | 次 |
|---|---|---|
| `pending` | queue 投入済・未着手 | `processing` |
| `processing` | scratch 生成・抽出実行中 | `awaiting_gate` / `failed` |
| `awaiting_gate` | 抽出済、Quality Gate 待ち/結果保持 | `done`(PASS+承認) / `failed`(FAIL) |
| `done` | Gate PASS かつ Phase4 で正本反映完了 | — |
| `failed` | 抽出失敗 or Gate FAIL。**正本未反映** | 再投入は手動 |
| `skipped` | 対象外・unknown・不完全（意図的に処理しない） | — |

- 各遷移は **`analysis_run_log` に1行**（script/開始終了/rows/quality_status/error）。
- `awaiting_gate` → `done` は **Phase 4（DB Integration）＝Tatsuki 承認後**にのみ起こる。Phase 2 単独では `awaiting_gate` で停止する。
- 異常終了で `processing` に取り残された行は次回 scan で検出し `failed` 化（タイムアウト・再投入対象）。

---

## 5. scratch DB 生成ルール

正本を汚さず「疑う」ための隔離領域。

- **場所**: `/tmp/ts24_scratch_<run>.db`（既存 `backfill_susp_zone_speed.py` / `build_master_db.py --out` の流儀）。
  正本と同一スキーマを使い、**正本 `ts24_unified.db` は読み取りのみ**（既存値との決定論比較に使用）。
- **粒度**: queue の1単位（2D=event or outing、report=ファイル、pdf=ファイル/フォルダ）ごとに scratch を生成。
  既存の `build_master_db.py --out /tmp/...` を **対象限定**で呼べるようにするのが理想（実装時に scope 引数を検討）。
- **生成内容**: 抽出結果（runs/laps/lap_suspension/race_results/pdf_lap_times 等の該当分）を scratch に書く。
  欠損は 0 で埋めない（NULL）。サンプル不足は NULL（n<5 ガード等、既存規則を踏襲）。
- **決定論ゲート（既存値保護）**: scratch と正本の **既存列を lap_id/run_id JOIN で突合**し、`abs(diff)<1e-6`・
  キー集合一致を要求（timestamp 列は除外）。これは §19b で実証済みの安全手順。新規行/新規列のみ追加候補とする。
- scratch は使い捨て。Gate 結果と差分サマリを `data_quality_log` / `analysis_run_log` に残してから破棄。

---

## 6. Quality Gate へ渡す単位

Gate（Phase 3）に渡すのは **「1つの検証可能なまとまり」**。

| ソース | Gate 単位 | 主な突合相手 |
|---|---|---|
| 2D | **outing（=run候補）単位**、必要に応じ event 一括 | 同 run の PDF best、既存 runs/laps、HED Fastest |
| レポート | **ファイル（イベント）単位** | 既存 runs のセットアップ、原本 Excel（§1b 照合ルール） |
| 結果PDF | **session（round×session×rider群）単位** | 2D best（受入ゲート §8: |Δ|>1.5s=要確認）、既存 race_results 自然キー |

- Gate 単位は queue の1行に対応づく（`import_queue.queue_id` ↔ `analysis_run_log.run_scope`）。
- Gate チェック項目（Phase 3 で詳細化）は最低限: lap数一致 / lap_time 物理範囲 / **PDF best vs 2D best 差(§8)** /
  run_id・lap_id 整合 / 既存数値列の決定論一致 / 新規指標 NULL率 / zone sample count / 外れ値 / 0とNULLの意味論 /
  timestamp 除外比較。各結果は `data_quality_log`（PASS/WARNING/FAIL）に1チェック1行。

---

## 7. FAIL 時の扱い

**FAIL データは絶対に正本DBへ到達させない**（roadmap 禁止事項）。

- `import_queue.status='failed'`、`analysis_run_log.quality_status='FAIL'`、`data_quality_log` に失敗チェックを残す。
- scratch DB は破棄（または `/tmp` に短期保持してデバッグ）。**正本へのコピーは行わない。**
- ソースファイルは消さない・動かさない。`source_file_registry.status` は `discovered`/`gated` のまま（再検証可能に）。
- **Workbench に FAIL として表示**し、理由（どのチェックが何故落ちたか）を提示。Tatsuki が原因（誤配置・命名・
  ソース差し替え等）に対処後、手動で再 queue（`pending` に戻す）。
- WARNING は「正本反映は保留、ただし破棄もしない」グレー状態。Tatsuki 確認で PASS 昇格 or FAIL 降格。
- **自動での FAIL→正本 強制反映は提供しない**（思想 §0）。

---

## 8. Workbench への未処理データ表示

新タブ（仮称「📥 Import / Quality」）で、**入れる前に疑える**ビューを提供。

- **未処理キュー**: `import_queue` を status 別に一覧（pending/processing/awaiting_gate/failed/skipped）。
  件数バッジ、ソース種別、検出時刻、tier、推定メタ（rider/circuit/round/session）。
- **品質ステータス**: 各 queue 行の最新 `data_quality_log` 集約（PASS/WARNING/**FAIL**）。FAIL は赤、WARNING は黄。
  クリックで失敗チェックの詳細（observed vs expected、tolerance、PDF/2D best差 等）。
- **検出だが未登録/不完全**: `.LAP` 欠落・`file_type=unknown`・HED矛盾(`gated`) を別枠で可視化（検出漏れ・誤検出の発見）。
- **アクション（Tatsuki操作）**: 「再検証(再queue)」「skipにする」「PASS承認→Phase4へ」。これらは将来実装。Phase 2
  初期は **読み取り（可視化）優先**で、書き込みアクションは段階導入。
- データ源は管理4テーブルのみ（正本データには触れない）。`ts24_unified.db` 接続は Workbench 既存経路を流用。

---

## 9. 既存実装との対応（再利用方針・作り直さない）

| Phase 2 要素 | 再利用する既存資産 | 役割 |
|---|---|---|
| 2D outing 検出 | `build_master_db.py: discover_outings()/gated_outings()`、`NOISE`、`_lap_timebase()` | tier 判定・HED矛盾ゲート・timebase自動判定 |
| 2D 抽出→scratch | `build_master_db.py: extract_outing()` ＋ `--out` | scratch へ runs/laps/lap_suspension |
| レポート取込 | `report_importer.py`（pending_* ステージング） | Excel→ステージング（正本直書きしない設計と整合） |
| 結果PDF取込 | `pdf_result_extractor_v2.py`(複数ページ連結)、`parse_bsb_result_pdf.py`、`apply_pdf_positions_v2.py`(自然キーUPSERT) | PDF→race_results 候補 |
| 受入ゲート §8 | `build_master_db.py` の |2D best − PDF best|>1.5s 検出 | Gate の中核チェック（検出のみ・判断はTatsuki） |
| 原本照合 | §1b 照合ルール（原本が勝つのは明示値のみ） | レポート/セットアップの Gate 基準 |
| 品質ログ | `create_quality_tables.py` の4テーブル | registry/queue/run_log/quality_log |

**新規に書く必要があるのは「オーケストレーション」だけ**: scan→registry登録→queue投入→scratch呼び出し→Gate実行→
ログ記録→Workbench表示。抽出・解析・突合の本体は既存を呼ぶ。

---

## 10. 未決事項 / Tatsuki 確認ポイント

1. **監視モード**: 初期は scan（手動1コマンド）で良いか。常駐 watch は Phase 2 後半送りで良いか。
2. **scratch スコープ**: `build_master_db.py` に「event/outing 限定で scratch 生成」する scope 引数を足してよいか
   （現状は `--all`。対象限定実行が Phase 2 の効率に効く）。
3. **Workbench Import/Quality タブ**: 初期は読み取り専用（可視化のみ）で良いか。再queue/承認ボタンは後続か。
4. **レポートのステージング**: `report_importer.py` の pending_* 経路を Phase 2 の正式ステージングとして採用してよいか
   （正本直書きしない方針と一致）。
5. **拡張子なしPDF**: マジック判定での検出を正式採用してよいか（`07_RESULTS` の実態に必須）。
6. **Phase 3 Gate 閾値**: lap_time 物理範囲・外れ値・NULL率の具体閾値は Phase 3 設計で確定（本書では項目のみ）。

---

## 11. スコープ外（本書では扱わない）

- Phase 3 Quality Gate の各チェックの**具体アルゴリズム・閾値**（別設計書）。
- Phase 4 DB Integration の反映手順詳細（既存 cutover/backfill 流儀を踏襲予定）。
- Case Search / Hypothesis / Supervisor Agent（Phase 5）。
- 実装コード（本書は設計のみ）。
