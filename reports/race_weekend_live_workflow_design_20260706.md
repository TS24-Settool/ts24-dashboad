# TS24 Race Weekend Live Workflow 設計（2D session-first → post-event 統合）

- 日付: 2026-07-06
- 種別: Phase A 設計レポート（read-only・GO不要・正本DB/コード/Excel 無変更）
- 発端: Tatsuki 新ノート `08_OBSIDIAN/.../2026-07-06 TS24 New Workflow.md` + 手書きスケッチ `IMG_1057 1.heic`
- 実装は `Race weekend workflow implementation GO` 受領後のみ（Phase B）

---

## 0. 要件（Tatsuki ノート + 手書きスケッチの転記）

添付 HEIC は sips で PNG 変換し読解に成功。手書き「TS24 Workbench Workflow」の内容:

1. Race Weekend 中、毎セッション後に 2D data file をできるだけ早く保存する。
2. 2D data が「2D Data」フォルダに保存されたら、Claude Code がデータを確認し、
   **Workbench に必要なデータだけを先に抽出する**（※SpecSheet なし・session data のみ）。
3. データが Workbench-ready になったら、新システム（Report v2）で **Auto "Report"** を作る。
4. 日曜レース後、Tatsuki がいつもの Report と `TS24_Data_Base_Original` を保存する。
5. Claude Code が全データ・全情報を照合し、**DB を最終更新（up-date all the DB）**する。

要件の本質: **「セッション直後の暫定解析（2Dのみ）」と「イベント後の最終統合（Report/Original/Result PDF）」の2段化**。

---

## 1. 現行システム棚卸し（read-only 調査結果）

### 1a. 2D 取込パイプライン（`build_master_db.py`・960行）

- **full-rebuild 専用**: `build_all()` は全イベント discover → 全スキーマ `DROP TABLE` → 全再抽出。
  per-session 増分機構は存在しない。出力は中間 `02_DATABASE/ts24_master.db` → `cutover_db.py` で昇格（§20a）。
- ただし **outing 単位の関数は完全独立**: `discover_events()` (L125) / `discover_outings()` (L380・nested/copia/loose 3レイアウト) /
  `gated_outings()` (L418) / `extract_outing()` (L207・laps + §44 22列含む全派生)。session-first 抽出はこれらを直接再利用できる。
- **増分化の唯一の難所 = run 番号/setup 割当** (L780-806): run 数は Original の n_orig と突合し、setup は Original pool を
  順に consume する。**Original はイベント後まで存在しない**ため、session 直後には確定 run_id/setup は作れない。
- rider/round/date = イベントフォルダ名、circuit = Report DAY1 → fallback 2D `.line`、session = ファイル名 prefix
  （`session_canon_2d` L78）。session 直後は Report も無いので **circuit は `.line` fallback + Event.ini で推定可能**。
- 受入ゲート: PDF best vs 2D session best Δ>1.5s = 0 件（L915）。session 直後は Result PDF も無いので適用不可 → 暫定段階では省略し final 時に適用。

### 1b. Phase 2A 管理層（`extraction_scan.py`・542行）

※タスク文の `scan_phase2a_sources.py` は存在せず、実体は `extraction_scan.py`。

- DATA 2D / 01_REPORTS / 07_RESULTS を scan → `source_file_registry`（file_path UNIQUE・manifest_hash= name|size sha256・
  mtime は iCloud jitter で不使用）→ discovered を `import_queue`（pending）→ `data_quality_log` `detect_*` → `analysis_run_log`。
- **冪等・管理テーブルのみ・業務テーブル防御あり**（`assert_mgmt_only()` L359）。半端コピー除外（.icloud/.partial/mtime<10s→incomplete）。
- 現状: registry 366 行 / queue 358 行 **全 pending**（2B consumer 未実装のため未消化）。
- **session-first intake はこの registry/queue をそのまま使える**（新規テーブル不要）。

### 1c. Workbench（`ts24_workbench.py`・6965行・7タブ）

- **📥 Import/Quality タブ（L6691）は表示専用**。ボタンは「↻ 再読込」のみ。scan/import トリガは存在しない → session import ボタンの自然な設置場所。
- 🦾 Suspension/Posture（L3864）→ `_load_data()` L3930 が `SELECT * FROM lap_suspension` **一点**。ここが provisional 切替ポイントで、
  DataFrame は 3フェーズ Run比較（`PhaseRunCompareWidget` L3059）まで自動伝搬する。
- `📄 Create Report v2` ボタン（L3146）→ `_on_create_report()` L3446 → `suspension_report.build_report_v2/pdf`。
- 🏁 Race Analysis は `RACE_LAP_SRC="race_lap_detail"`（VIEW overlay・§40）。**VIEW overlay パターンの実績あり**。
- DB は `QFileSystemWatcher`（L6890）監視で **DB ファイル更新時に全タブ自動 refresh**（再起動不要）。session import 後の反映配線は不要。
- **現状 provisional/final の区別は一切ない**（品質表示は RaceAnalysis の PDF 由来1行のみ）。

### 1d. Report v2（`suspension_report.py`・1036行）

- 入力 = Workbench DataFrame or `load_lap_suspension()`（`mode=ro`・lap_suspension 自己完結）。CLI あり。PPTX ~18枚 + 単一 PDF。
- **provisional/session モードの追加は容易で局所的**: `build_report_v2/pdf` に `provisional` フラグ →
  ①`chart_cover()` に「PROVISIONAL — SESSION DATA (official results not reflected)」リボン ②footer 注記
  ③filename `_PROVISIONAL` トークン ④CLI フラグ。現状 provenance 入力は皆無なので、フラグは呼び出し側から渡す。

### 1e. Post-event 統合（確立済み safe apply パターン）

`apply_round7_race_results.py` / `apply_pdf_v2_staging.py` / `refresh_db_master_safe.py` / `supabase_audit.py` に共通:

```text
dry-run 既定（mode=ro）→ Quality gate → readiness report → 明示GO → full backup
→ 1トランザクション apply + 非対象テーブル before==after assert（違反=rollback・exit 3）
→ 事後検証 → report → CLAUDE.md §/Obsidian 記録
```

依存順: ①extraction_scan（GO不要）→ ②race_results（真値・最優先）→ ③pdf_v2_scratch_gate G1-G6 →
④v2 staging apply → ⑤VIEW/Workbench（済）→ ⑥2D は scratch full rebuild+決定論ゲート→cutover →
⑦DB Master（派生）→ ⑧Supabase audit→sync → ⑨push（全て別承認）。

### 1f. 発見した矛盾・注意点

- **ts24-report-import スキルが旧アーキテクチャ**: Step 3 が `build_unified_db.py`（Master.xlsx → DB 逆方向・DB/Excel 両上書き）で、
  現行正本方向（`build_master_db.py`→`cutover_db.py`、Excel は `build_excel_master.py` 派生）と矛盾。**スキル改訂 or 廃止を Task 7 に含めるべき**。
- ルート直下 `ts24_unified.db` は 0 byte 孤児（削除は別承認・§20a）。
- Workbench の DB 接続は `mode=ro` でない（自前ログテーブルへ正当な書込あり）。provisional 読取は既存接続でよいが、
  **import 実行は Workbench プロセス内で正本 DB へ直接書かない**設計にする（後述）。
- DB Master（`build_excel_master.py`）は race_results/v2 系を読まない（§41a）→ session-first の影響なし。

---

## 2. 現行の課題（何が遅いのか）

| 課題 | 原因 |
|---|---|
| セッション直後に Workbench で新データを見られない | 2D 取込が full rebuild + Original/Report 依存（run/setup 割当）でイベント後に寄る |
| Report v2 がセッション判断に使えない | Report v2 の価値 = lap_suspension 更新後。その lap_suspension がイベント後にしか更新されない |
| import_queue 358 pending | Phase 2B consumer 未実装（検出だけして消化する仕組みが無い） |
| 暫定と最終の区別が無い | provisional 概念が DB にも UI にも Report にも無い |

---

## 3. 新 Workflow 設計（5ステージ）

原則: **正本業務テーブル（runs/laps/lap_suspension/race_results/pdf_lap_times）は Race Weekend 中に一切触らない**。
暫定データは PDF v2 staging と同型の **追加専用テーブル + VIEW overlay** で持ち、final 化は従来の full rebuild + 決定論ゲート + cutover で行う。

### Stage 1 — Session Intake（セッション後・手動ボタン）

- Tatsuki が 2D data を `DATA 2D/<event>/` へ保存（現行と同じ・SAVE 運用）。
- Workbench 📥 Import/Quality タブの新ボタン **「🔍 Session Scan」** → `extraction_scan.py` をサブプロセス実行。
  registry へ hash 登録・重複/incomplete/gated 判定・queue へ pending 投入（全て既存機構・管理テーブルのみ・GO不要領域）。
- iCloud 対策は既存（manifest_hash・mtime<10s incomplete・`--min-age`）をそのまま利用。

### Stage 2 — Session Extraction（staging・dry-run 品質確認つき）

- 新スクリプト **`session_extract_staging.py`**（新規・dry-run 既定）:
  - 対象 = import_queue の pending のうち **当該イベントの新規 2D outing のみ**（queue consumer = Phase 2B の最小実装）。
  - `discover_outings`/`gated_outings`/`extract_outing` を import して outing 単位で抽出（本番ロジック再利用・二重実装しない）。
  - **provisional run_id**: Original が無いので確定 R 番号は付けられない → `PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}`
    （2D 時系列順の暫定連番）。setup 値は空欄（SpecSheet なし = Tatsuki スケッチの「without SpecSheet」と一致）。
    circuit は Event.ini/`.line` から推定し、`session_canon_2d` で session 判定。
  - 書込先 = 正本 DB 内の新テーブル **`runs_provisional` / `laps_provisional` / `lap_suspension_provisional`**
    （lap_suspension と同 69 列 + `data_stage='provisional'` + `intake_ts` + `source_manifest_hash`）。
    業務テーブルは before==after assert（既存パターン流用）。
  - Quality gate（apply 前に dry-run report）: lap count>0 / session label 判定成功 / rider 一致 / lap_time 60–300s 分布 /
    braking/apex/exit 成立率 / §44 22列の n条件成立率 / 既存 lap_id 衝突 0。FAIL outing は staging 不採用（隔離のみ）。
  - queue status: pending → processing → awaiting_gate（gate PASS 後 done は final 化時）。
- 実行トリガ: Workbench 📥 タブの新ボタン **「⬇ Session Import (staging)」**（dry-run 結果ダイアログ → 確認 → apply）。
  CLI 単独実行も可（Claude Code が現場サポートで実行する場合）。

### Stage 3 — Workbench Provisional Refresh

- 🦾 Suspension/Posture `_load_data()`（L3930）を
  `SELECT *, 'final' AS data_stage FROM lap_suspension UNION ALL SELECT *, 'provisional' FROM lap_suspension_provisional` 相当へ切替
  （race_lap_detail と同じ overlay 思想。provisional テーブルが無ければ従来 SQL に fallback）。
- UI: 3フェーズ Run比較の Run リストに provisional run は **「⏳ R1 (prov)」** 等のマーク表示。フィルタで provisional 含む/除外を選択可。
- `QFileSystemWatcher` により staging apply 後は自動 refresh（配線不要）。

### Stage 4 — Session Report（Report v2 provisional モード）

- `build_report_v2/pdf` に `provisional=True`: cover リボン「PROVISIONAL — SESSION DATA」、
  metadata 注記（official results / Original setup 未反映・run 番号は暫定）、filename `_PROVISIONAL_` トークン。
- rider/team への暫定共有資料として使用。final report と取り違えない。

### Stage 5 — Post-event Integration（final 化）

1. Tatsuki が Report / `Data_Base_TS24_ORIGINAL` / Result PDF を保存（現行どおり）。
2. race_results apply（dry-run→GO→apply・§36-37 パターン）→ pdf_v2_scratch_gate → v2 staging apply（§38）。
3. **2D final 化 = 従来の full rebuild**: `build_master_db.py --all --out scratch` → 決定論ゲート
   （provisional 抽出値と scratch の lap 値突合も追加チェック: 同一 .MES から同値が出ること）→ cutover。
   run 番号/setup は Original と突合して確定（従来ロジックのまま）。
4. final 化成功後、当該イベントの provisional 行を **クリア**（DROP せず DELETE・backup 付き・provisional テーブルは業務テーブル外だが行削除は承認境界に従い GO 内で実施）。queue → done。
5. DB Master / Supabase / push は従来どおり各別承認。

---

## 4. 実装方式の比較

| 比較軸 | Option A: 現行 batch 維持 | **Option B: 手動ボタン式 session-first（推奨）** | Option C: folder watch 半自動 |
|---|---|---|---|
| Race Weekend 中の実用性 | ✗ 変わらず使えない | ◎ セッション後 数分で Workbench/Report v2 | ◎（最速だが差は小さい） |
| DB 安全性 | ◎ 変更なし | ◎ 業務テーブル不変・staging+assert・確立パターン踏襲 | △ 自動書込はコピー中/誤配置ファイル巻込みリスク |
| 取り込みミスのリスク | ◎ | ○ dry-run gate + 人間確認を挟める | △ HED 誤配置（ROUND11 実例）や iCloud 遅延を無人で踏む |
| Workbench UI 実装量 | ◎ なし | ○ 中（ボタン2 + Run マーク + `_load_data` 切替） | ○ B と同等 + watcher 常駐管理 |
| rollback 容易性 | ◎ | ◎ provisional テーブル DELETE/DROP のみ・業務不変 | ○ 同左だが自動実行分の追跡が必要 |
| Tatsuki 操作負担 | ✗ 現状の待ち時間 | ○ ボタン2回（Scan → Import）/セッション | ◎ 保存するだけ |

**推奨 = Option B**。理由: ①自動監視より安全（iCloud 部分同期・コピー途中・HED 誤配置の実績リスクを人間確認で遮断）
②Race Weekend に必要な速度は十分（ボタン2回・数分）③既存 Import/Quality タブ・registry/queue・staging+assert パターンと最も整合
④DB 書込前に dry-run/quality 確認を挟める ⑤安定運用後に C（watch が Scan だけ自動化し Import は手動のまま等）へ段階的移行可能。

---

## 5. 実装タスク分割（Phase B 以降・各ゲート）

| Task | 内容 | 主変更 | ゲート |
|---|---|---|---|
| 1 | 本設計（今回） | reports/Obsidian のみ | GO不要・完了 |
| 2 | 2D session intake dry-run scanner | Workbench 「🔍 Session Scan」ボタン + extraction_scan 呼出 | 管理テーブルのみ・implementation GO 内 |
| 3 | session extraction staging | `session_extract_staging.py` + provisional 3テーブル | 正本DBへの新テーブル追加 = GO 必須 |
| 4 | Workbench Import/Quality UI 強化 | Import ボタン・dry-run 結果表示・queue 消化表示 | implementation GO 内 |
| 5 | 3フェーズタブ provisional 可視化 | `_load_data` overlay + Run マーク | implementation GO 内 |
| 6 | Report v2 session モード | `provisional` フラグ + cover リボン + filename | implementation GO 内 |
| 7 | post-event reconciliation | 決定論ゲートへ provisional 突合追加・provisional クリア手順・**ts24-report-import スキル改訂** | final 化は各既存 GO |
| 8 | finalization + 同期ゲート | DB Master / Supabase / origin push | 各別承認（従来どおり） |

推奨実装順: 2→3→5→6→4（4 は 2/3 の CLI が安定してから UI 統合）。

## 6. Multi-agent operating check

- Workflow architect: 5ステージ順序・Option 比較（本書 §3-4）。
- 2D ingestion: outing 単位再利用・manifest_hash 重複防止・iCloud/incomplete 対策（§1a-1b・Stage 1-2）。
- DB integrity: provisional 分離・業務テーブル before==after assert・rollback=DELETE/DROP（Stage 2/5）。
- Workbench/UI: 表示専用タブへのボタン追加・`_load_data` 一点切替・FileWatcher 自動 refresh（§1c・Stage 3）。
- Report: provisional/final の視覚分離（Stage 4）。
- Operations: Tatsuki 現場手順 = 保存 → Scan → Import → Report ボタン（各セッション 2-3 分）。
- Quality Gate: dry-run 既定・FAIL 隔離・final 決定論ゲート突合（Stage 2/5）。
- Supervisor: 正本業務テーブル書込・schema 変更・Supabase・DB Master・origin push・新2D本取込は全て別承認のまま（本設計で緩和しない）。

## 7. まだ実施しないこと（本レポート時点）

新2D本取込 / 正本DB schema 変更・行更新 / Workbench 改修 / folder watch / Supabase sync / DB Master 再生成 /
origin push / `Data_Base_TS24_ORIGINAL.xlsx` 上書き — 全て `Race weekend workflow implementation GO` 以降・各ゲート。
