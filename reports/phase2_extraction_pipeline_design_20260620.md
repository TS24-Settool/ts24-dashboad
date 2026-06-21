# Phase 2 — Extraction Pipeline 設計書（rev.2）

**作成:** 2026-06-20 / Claude Code（Tatsuki指示・複数エージェント実態調査に基づく）
**改訂 rev.2:** 2026-06-20 Tatsuki承認＋7点修正反映（用語/2A・2B分割/manifest hash/半端コピー対策/status明示/
data_quality_log prefix/scratch FAIL保存）。
**ステータス:** 設計（DESIGN）。Phase 2A は実装着手可（本改訂後）。**Phase 2B 以降、正本「業務テーブル」反映は禁止。**
**位置づけ:** Multi-Agent Data Quality Roadmap の Phase 2（CLAUDE.md §20c/§22）。Phase 0-1（正本DB固定・品質5テーブル）完了が前提。

---

## 0. 設計思想 —「自動で入れる」より先に「自動で疑う」

Phase 2 は **新ファイルを自動で正本の業務テーブルへ入れる仕組みではない**。
Phase 2 が自動化するのは **「検出」と「隔離」と「疑いの記録」まで**。業務テーブル反映（Phase 4）は
Quality Gate（Phase 3）PASS かつ Tatsuki 承認の後に限る。

### 0.1 用語: 業務テーブル vs 管理テーブル（修正1）

`ts24_unified.db` 内のテーブルを2種に分ける。

- **業務テーブル（business tables）= 書込禁止（Phase4・承認後のみ）**:
  `runs` / `laps` / `lap_suspension` / `lap_metrics` / `race_results` / `pdf_lap_times` / `performance` /
  `problem_log` / `setup_decision_log` / `events` / `tags` / `run_tags` / `best_worst_pairs` / `round_brief` /
  `problem_library` / `lap_observation_log`。
- **管理テーブル（management tables）= Phase 2 が書いてよい**:
  `source_file_registry` / `import_queue` / `analysis_run_log` / `data_quality_log` / `metric_version_log`（参照）。

> 旧版の「正本DBに一切書かない」は不正確だった。正しくは **「正本DBの業務テーブルに書かない。管理テーブルへの
> 記録は許可」**。Phase 2 の検出・キュー・ログは管理テーブルに記録される（同じ `ts24_unified.db` ファイル内）。

### 0.2 原則
- 検出した時点では **必ず未検証**。`source_file_registry.status` は `discovered` 起点で、Gate を通るまで前進しない。
- **「見つからない」より「黙って間違える」方が危険。** 検出漏れは検出ログで可視化し、誤検出・矛盾・不完全は
  `incomplete` / `gated` / `unknown` として残す（修正5）。
- 既存の抽出・検証ロジック（`build_master_db.py` の `discover_outings`/`gated_outings`/受入ゲート §8、
  `report_importer.py`、`pdf_result_extractor_v2.py` 等）を **再利用する。作り直さない。**

```
新ファイル                       ┌──── 業務テーブルには触れない（管理テーブルのみ記録）────┐
  ↓ 検出(scan)                                                                          │
=== Phase 2A ============================================                               │
source_file_registry ─登録→ import_queue ─→ Workbench「未処理データ」表示               │
  (discovered/incomplete/                  (pending)        検出チェック=detect_*       │
   gated/unknown)                                            を data_quality_log へ      │
=== Phase 2B ============================================                               │
import_queue(pending) ─→ scratch DB 生成(/tmp,隔離) ─→ awaiting_gate                    │
                          正本は読取のみ              （Gate=Phase3 / 反映=Phase4・承認後）
すべての遷移を analysis_run_log に記録。FAIL時のみ scratch を短期保存（修正7）。
```

---

## 1. Phase 2A / 2B 分割（修正2）

Phase 2 を2段に分け、**2A を先行実装**する。

| | 範囲 | 業務テーブル | scratch | 完了状態 |
|---|---|---|---|---|
| **Phase 2A** | scan → `source_file_registry` 登録 → `import_queue` 投入 → Workbench 表示 | 触れない | **生成しない** | queue が `pending`（または `skipped`） |
| **Phase 2B** | `pending` を取り出し → scratch DB 生成（抽出実行）→ `awaiting_gate` 遷移 | 触れない（読取のみ） | `/tmp` に生成 | queue が `awaiting_gate`（FAIL時 `failed`） |

- **2A は抽出を一切行わない**。ファイルを「見つけて・分類して・並べて・見せる」だけ。scratch も Gate も無い。
- **2B で初めて scratch 生成と抽出**を行うが、書くのは scratch（`/tmp`）と管理テーブルのみ。業務テーブルには書かない。
- Phase 3（Gate 本体）・Phase 4（業務テーブル反映＝承認後）は別フェーズ。**2B 完了でも正本業務テーブルは不変。**

---

## 2. 監視対象（watch targets）

| 領域 | パス | 内容 | 検出単位 | 既存取込ロジック |
|---|---|---|---|---|
| 2Dロガー | `DATA 2D/{event}/…` | MES/LAP/HED/DDD + チャンネル分割(A*/C*) | **outing**（1走行）→ run → lap | `build_master_db.py: discover_outings()` |
| レポート | `01_REPORTS/{DA77,JA52,COMPANY}/*.xlsx` | DAY1/DAY2/REPORT シート | **ファイル** | `report_importer.py`（ステージング） |
| 公式結果 | `07_RESULTS/ROUND*/…`, `07_RESULTS/Company/…-RESULT-BSB/` | リザルトPDF / クロノPDF | **ファイル**/ **フォルダ**(BSB) | `pdf_result_extractor_v2.py` / `parse_bsb_result_pdf.py` |

監視は **scan モード（手動1コマンド・推奨）** を Phase 2A で実装。常駐 watch は後半課題。

> **拡張子なしPDF（必須要件）:** `07_RESULTS/` に拡張子の無い PDF 実体（例 `20260529-ROUND6-FP`）が存在。
> `rglob("*.pdf")` だけでは取りこぼす → **先頭マジック `%PDF` でも判定**する。

---

## 3. ファイル種別ごとの検出ルール

検出は「拡張子」だけに依存せず、**配置 tier + 必須随伴ファイル + 内容シグネチャ + 安定性**で確定する。
確信が持てないものは `file_type='unknown'`／`status='unknown'` で登録し queue には載せない（疑う）。

### 3.1 半端コピー・一時ファイル対策（修正4）

iCloud 同期や手動コピー途中のファイルを誤検出しないためのガード。**検出器は以下を必ず適用**:

- **除外パターン**（ファイル名・パス）: `~$*`（Office一時）、`.tmp` / `*.partial` / `*.crdownload` / `*.download`、
  `.DS_Store`、`*.icloud`（未ダウンロードのプレースホルダ）、先頭 `._`（AppleDouble）。
- **size/mtime 安定性チェック**: 検出時に `(size, mtime)` を記録し、**一定間隔（既定: 2回・5秒間隔）後に再測定して
  不変であること**を確認してから登録対象にする。変動中＝コピー進行中とみなし `incomplete` 保留（次回 scan で再評価）。
- **2D outing は随伴ファイルの揃いも安定性条件**: 必須（`.DDD`/`.LAP`）が揃い、かつ outing 配下の総 size が安定する
  までは `incomplete`。
- 除外・保留はすべて `data_quality_log`（`detect_excluded` / `detect_unstable`）に記録（黙って捨てない）。

### 3.2 DATA 2D（outing 検出 — 既存 `discover_outings()` を権威）

| tier | 配置 | 検出 | base 確定 |
|---|---|---|---|
| `nested` | `…/{base}.MES/` | フォルダ名が `.MES` で終わる | フォルダ名から `.MES` 除去 |
| `copia` | `…/{base}.MES - Copia/` | フォルダ名に `.MES ` を含む | フォルダ内 `.DDD` の stem |
| `loose` | event 直下に `{base}.DDD` | `.DDD` の親が `.MES`系でない | `.DDD` の stem |

- **outing 成立条件**: `{base}.DDD` と `{base}.LAP` が揃う。欠落は `status='incomplete'`（queue 非投入・ログ記録）。
- **ノイズ除外**（既存 `NOISE` 継承）: `ACCENSIONE` / `RD\d+-S\d+` / `-KAW_` / `^D0-`。
- **HED 矛盾は疑う**: copia/loose で HED Circuit がイベント基準と矛盾（例: ROUND11 配下 Portimão HED 誤配置）→
  `status='gated'`（queue 保留・Tatsuki 判断）。HED 単独でデータを捨てない（HEDは不確実: CLAUDE.md memory）。
- `.HED` は任意（Fastest lap 基準）。A*/C* は outing に内包（個別登録しない）。

### 3.3 2D outing の同一性 = manifest hash（修正3）

outing の変更検出は **代表 `.DDD` 単体の sha256 ではなく manifest hash** とする。

- **対象**: `{base}.DDD` / `{base}.LAP` / `{base}.HED`（存在時）＋ チャンネル主要ファイル群。
  チャンネル分割（A*/C* 等）は **全バイト hash は重いため**、各ファイルの `(相対名, size, mtime, 先頭4KB sha256)` を
  正規順に連結して manifest を作り、その manifest 文字列の sha256 を `source_file_registry.sha256` に格納する。
  - 既定対象: `.DDD/.LAP/.HED/.SEC/.STI/.IST/.CAL` は全バイト hash、A*/C*/その他大容量は `(name,size,mtime,head4k)`。
  - manifest の構成方針は `notes` に記録（再現可能性のため）。将来 full-hash モードへ切替可能に設計。
- これにより「DDD は同じだが LAP/HED が差し替わった」「チャンネルが一部追加された」も更新として検出できる。
- レポート/PDF は単一ファイル → 通常の全バイト sha256。

### 3.4 01_REPORTS（Excel・ファイル単位）
- 検出: `01_REPORTS/**/*.xlsx`（`~$` 一時除外）。
- 種別確定: ヘッダ固定位置メタ（B1=rider, H2=circuit, H3=round, D4=date / シート DAY1/DAY2/REPORT）が読めれば
  `report`（COMPANY/BSB は `report_company`）。読めなければ `unknown`。命名とヘッダ矛盾は WARNING（内容優先）。

### 3.5 07_RESULTS（PDF・ファイル/フォルダ単位）
- 検出: `07_RESULTS/**/*.pdf` ＋ **拡張子なしで先頭 `%PDF`**。
- 種別確定: 本文に "Chronological Analysis" 等 → `result_chrono`（ラップ全数）、無ければ `result_classification`。
  `…-RESULT-BSB/` フォルダ → `result_bsb`。セッション種別（FP/QP/SP/WUP1/WUP2/RACE1/RACE2）推定失敗は WARNING。

---

## 4. source_file_registry 運用（修正5: status 明示）

| 列 | Phase 2 での使い方 |
|---|---|
| `file_id` | 安定ID。2D outing は `{event}/{base}` 由来の決定論キー。report/pdf は短縮パス＋hash 先頭 |
| `file_path` | 2D は outing 代表（`.DDD` パス）。report/pdf はファイルパス |
| `file_type` | `2d_outing` / `report` / `report_company` / `result_chrono` / `result_classification` / `result_bsb` / `unknown` |
| `file_size`/`file_mtime` | 安定性チェック・一次変更フィルタ |
| `sha256` | report/pdf=全バイト。**2D outing=manifest hash**（§3.3）。再検出時の同一性判定の本体 |
| `rider/circuit/round/session` | 命名・HED・ヘッダから解析した推定メタ（NULL 可。確定値は業務テーブル側） |
| `discovered_at` | 検出時刻（ISO8601） |
| `status` | **下表の値を明示使用** |
| `notes` | tier / manifest 構成 / HED矛盾 / 命名不一致 / 除外理由 等 |

**status 値（明示・修正5）:**

| status | 意味 | queue投入 | 次 |
|---|---|---|---|
| `discovered` | 検出・安定確認済・種別確定。処理候補 | する | `queued`→`extracted`(2B)→`archived` |
| `incomplete` | 必須随伴欠落 or コピー進行中（size/mtime不安定） | しない | 次回 scan で再評価 |
| `gated` | 矛盾検出（HED↔イベント不一致 等）でTatsuki判断保留 | しない | 解消後 `discovered` |
| `unknown` | 種別判定不能（ヘッダ読めない/シグネチャ不一致） | しない | 手動仕分け |
| `queued` | import_queue 投入済 | — | `extracted` |
| `extracted` | 2B で scratch 抽出済 | — | `archived` |
| `archived` | 旧版・削除/移動済（履歴保持） | — | — |

運用原則:
- **冪等**: `file_path` UNIQUE。sha256/manifest が不変なら何もしない。変化＝更新 → `status='discovered'` に戻し再評価。
- **2D は outing 代表1行**。**削除/移動**は `archived`（消さない）。

---

## 5. import_queue status 遷移

```
=== Phase 2A の範囲 ===          === Phase 2B の範囲 ===              === Phase 3/4 ===
                       取り出し              scratch生成
┌─────────┐          ┌────────────┐        ┌────────────────┐  Gate(P3)  ┌──────┐
│ pending │ ───────▶ │ processing │ ─────▶ │ awaiting_gate  │ ─PASS─┐    │ done │←P4(承認後・業務反映)
└─────────┘          └────────────┘        └────────────────┘       │    └──────┘
   ▲ 2Aが登録            │ 抽出失敗                  │WARNING→保持      │
   │                     ▼                          ▼                 └FAIL→┌────────┐
┌─────────┐          ┌────────┐                                            │ failed │（業務未反映・隔離）
│ skipped │          │ failed │◀──────────────────────────────────────────└────────┘
└─────────┘          └────────┘
(unknown/incomplete/gated は queue 非投入。skipped は対象外明示)
```

- **2A 完了時点で queue は `pending`（または対象外 `skipped`）まで**。`processing` 以降は 2B。
- `awaiting_gate`→`done` は **Phase 4（業務テーブル反映）＝Tatsuki 承認後のみ**。2B 単独では `awaiting_gate` で停止。
- 各遷移は `analysis_run_log` に1行。`processing` 取り残しは次 scan で `failed` 化。

---

## 6. scratch DB 生成ルール（Phase 2B / 修正7: FAIL時のみ保存）

- **場所**: `/tmp/ts24_scratch_<queue_id>.db`。正本と同一スキーマ。**正本 `ts24_unified.db` は読み取りのみ**（既存値の決定論比較用）。
- **粒度**: queue の1単位（2D=outing/event、report=ファイル、pdf=ファイル/フォルダ）ごと。既存 `build_master_db.py --out`
  を対象限定で呼ぶ（scope 引数は実装時に追加検討＝設計確認2）。
- **生成内容**: 抽出結果を scratch に書く。欠損は 0 で埋めない（NULL）。n<5 等のガードは既存規則を踏襲。**業務テーブルには書かない。**
- **決定論ゲート（既存値保護）**: scratch と正本の既存列を lap_id/run_id JOIN で突合（`abs(diff)<1e-6`・キー集合一致、
  timestamp 除外）。§19b で実証済み。新規行/列のみ追加候補。
- **保存ポリシー（修正7）**: scratch は原則 **使い捨て（生成→Gate→破棄）**。ただし **Gate 結果が FAIL の場合のみ
  短期保存**して原因調査を可能にする。
  - 保存先: `/tmp/ts24_scratch_fail/<queue_id>_<ts>.db`（`/tmp` 配下・再起動で消える）。
  - 保存期限: 既定 **72時間**（または最大 N 件のリングバッファ）。期限超過は自動削除。
  - PASS/WARNING の scratch は破棄。保存パスと破棄/保持の別は `analysis_run_log.notes` と `data_quality_log` に記録。

---

## 7. Quality Gate へ渡す単位（Phase 2B→3）

| ソース | Gate 単位 | 主な突合相手 |
|---|---|---|
| 2D | **outing（=run候補）単位**、必要に応じ event 一括 | 同 run の PDF best、既存 runs/laps、HED Fastest |
| レポート | **ファイル（イベント）単位** | 既存 runs のセットアップ、原本 Excel（§1b） |
| 結果PDF | **session（round×session×rider群）単位** | 2D best（受入ゲート §8: |Δ|>1.5s=要確認）、race_results 自然キー |

- Gate 単位は queue 1行に対応（`import_queue.queue_id` ↔ `analysis_run_log.run_scope`）。

---

## 8. data_quality_log のチェック命名（修正6: detect_* / gate_*）

`data_quality_log.check_name` に **prefix を付け、Phase2 検出チェックと Phase3 正式 Gate を区別**する。

- **`detect_*`（Phase 2A/2B の検出時チェック）**: 例
  - `detect_excluded`（一時/半端ファイル除外）、`detect_unstable`（size/mtime 不安定＝コピー中）、
    `detect_incomplete`（必須随伴欠落）、`detect_unknown_type`（種別判定不能）、
    `detect_hed_circuit_mismatch`（HED↔イベント矛盾→gated）、`detect_name_meta_mismatch`（命名↔ヘッダ不一致）、
    `detect_duplicate`（既登録と同一）、`detect_updated`（hash変化＝更新）。
- **`gate_*`（Phase 3 正式 Gate）**: 例
  - `gate_lap_count`、`gate_laptime_range`、`gate_pdf_vs_2d_best`（§8）、`gate_runid_lapid_consistency`、
    `gate_determinism`（既存数値列）、`gate_null_rate`、`gate_zone_sample`、`gate_outlier`、`gate_zero_vs_null`、
    `gate_timestamp_excluded`。
- 集計・Workbench 表示は prefix で「検出段階の所見」と「正式 Gate 結果」を分離表示。result は `PASS/WARNING/FAIL`。

---

## 9. FAIL 時の扱い

**FAIL データは絶対に正本業務テーブルへ到達させない**。

- `import_queue.status='failed'`、`analysis_run_log.quality_status='FAIL'`、`data_quality_log` に失敗 `gate_*` を残す。
- **scratch は FAIL 時のみ短期保存**（§6・修正7）。業務テーブルへのコピーは行わない。
- ソースは消さない・動かさない。`source_file_registry.status` は維持（再評価可能）。
- **Workbench に FAIL 表示**＋理由（どの `gate_*`/`detect_*` が何故落ちたか）。Tatsuki 対処後に手動再 queue（`pending`）。
- WARNING はグレー（反映保留・破棄もしない）。自動 FAIL→業務反映は提供しない。

---

## 10. Workbench への未処理データ表示（Phase 2A）

新タブ「📥 Import / Quality」。Phase 2A では **読み取り（可視化）専用**。

- **未処理キュー**: `import_queue` を status 別一覧（pending/processing/awaiting_gate/failed/skipped）。件数バッジ・種別・
  検出時刻・tier・推定メタ。
- **検出だが未投入**: `source_file_registry` の `incomplete`/`gated`/`unknown` を別枠表示（検出漏れ・誤検出・矛盾の発見）。
- **品質ステータス**: 各行の最新 `data_quality_log` 集約。`detect_*` と `gate_*` を分けて表示。FAIL=赤/WARNING=黄。
  クリックで詳細（observed/expected/tolerance、PDF/2D best差 等）。
- **アクション**（再 queue/skip/承認）は将来。Phase 2A は可視化優先。
- データ源は管理テーブルのみ。業務テーブルには触れない。

---

## 11. 既存実装との対応（再利用・作り直さない）

| Phase 2 要素 | 再利用する既存資産 | 役割 | Phase |
|---|---|---|---|
| 2D outing 検出 | `build_master_db.py: discover_outings()/gated_outings()/NOISE/_lap_timebase()` | tier 判定・HED矛盾・timebase | 2A(検出ルール参照)/2B(抽出) |
| 2D 抽出→scratch | `build_master_db.py: extract_outing()` + `--out` | scratch へ runs/laps/lap_suspension | 2B |
| レポート取込 | `report_importer.py`（pending_* ステージング） | Excel→ステージング | 2B |
| 結果PDF取込 | `pdf_result_extractor_v2.py`/`parse_bsb_result_pdf.py`/`apply_pdf_positions_v2.py` | PDF→race_results 候補 | 2B |
| 受入ゲート §8 | `build_master_db.py` の |2D−PDF best|>1.5s | Gate 中核 | 3 |
| 原本照合 | §1b 照合ルール | レポート Gate 基準 | 3 |
| 品質ログ | `create_quality_tables.py` の4管理テーブル | registry/queue/run_log/quality_log | 2A/2B |

**新規実装はオーケストレーションのみ**: scan→registry→queue→（2B: scratch→Gate呼出）→ログ→Workbench表示。

---

## 12. 未決事項 / Tatsuki 確認ポイント

1. 監視は scan（手動1コマンド）開始で良いか（常駐 watch は後半）。
2. `build_master_db.py` に「event/outing 限定 scratch 生成」scope 引数を足して良いか（2B）。
3. Workbench Import/Quality タブは初期 読み取り専用で良いか。
4. レポートは `report_importer.py` の pending_* ステージングを正式採用で良いか。
5. 拡張子なしPDF の `%PDF` マジック判定を正式採用で良いか。
6. manifest hash の対象集合（§3.3 既定）と full-hash 切替要否。
7. scratch FAIL 保存の期限（既定72h / リングバッファ件数）。
8. 安定性チェックの間隔・回数（既定 2回×5秒）。
9. Phase 3 Gate の具体閾値は別設計書で確定。

---

## 13. スコープ外（本書では扱わない）

- Phase 3 Quality Gate の各 `gate_*` の具体アルゴリズム・閾値（別設計書）。
- Phase 4 DB Integration（業務テーブル反映＝承認後）の手順詳細。
- Case Search / Hypothesis / Supervisor Agent（Phase 5）。
- Phase 2B の実装（本改訂後の実装は **Phase 2A のみ**着手）。
