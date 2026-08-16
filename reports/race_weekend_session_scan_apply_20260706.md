# Race Weekend workflow Phase B-1: Session Scan 基盤 実装レポート

- 日付: 2026-07-06
- ゲート: **`Race weekend workflow implementation GO` 受領済み**（同セッション・Tatsuki 明示）
- 範囲: Workbench Session Scan ボタンのみ（設計 Task 2 / `reports/race_weekend_live_workflow_design_20260706.md` §5）
- 変更ファイル: `ts24_workbench.py` のみ（`extraction_scan.py` 無変更・二重実装なし）
- 正本業務テーブル: **不変（before==after 検証済み）**

---

## 1. 実装内容

`ImportQualityTab`（表示専用だった 📥 Import/Quality タブ）に以下を追加:

1. **`🔍 Session Scan` ボタン**（`__init__`・「↻ 再読込」の隣）
   - `subprocess.run([sys.executable, extraction_scan.py], timeout=600, cwd=SCRIPT_DIR)` で既存 Phase 2A スキャナを実行。
   - 実行中: ボタン無効化 + 「スキャン中…」+ WaitCursor。全体 try/except/finally で **失敗しても Workbench を落とさない**。
   - stdout/stderr を `reports/session_scan_<YYYYMMDD_HHMMSS>.log` へ保存。
   - exit≠0 → QMessageBox.warning（exit code + 末尾10行 + ログパス）。
2. **`_run_scan()`**: 上記本体。成功時は `self.refresh()` → サマリーを常設ステータスラベル `_lbl_scan` + ダイアログに表示。
   表示には必ず **「Scan only / no 2D extraction yet（スキャンのみ・2D抽出はまだ行いません）」** を含む。
3. **`_scan_summary()`**: scanner stdout（`[INFO] 検出:`/`[DONE] registry:`）から 検出/新規/更新/不変 を解析。
   解析不能時は管理テーブル（registry status 集計・queue pending 件数・最新 `analysis_run_log`）へフォールバック。

DB パス: `extraction_scan.py` の `DEFAULT_DB` は Workbench `DB_PATH` と同一解決（`--db` 不要）。UI toolkit = PyQt6。

## 2. 検証結果（全 PASS）

1. `py_compile`（extraction_scan / ts24_workbench）PASS。
2. offscreen smoke: MainWindow 起動 / **7タブ無回帰** / `_btn_scan` 存在 / `_run_scan`・`_scan_summary` callable / `_lbl_scan` 存在。
   `_scan_summary` は実 stdout と空 stdout フォールバックの両方を単体確認。
3. **業務テーブル不変検証（実 scan 1回・CLI 実行 = ボタンと同等）**:

| テーブル | before | after |
|---|---:|---:|
| runs | 275 | 275 ✅ |
| laps | 1202 | 1202 ✅ |
| lap_suspension | 1202 | 1202 ✅ |
| race_results | 866 | 866 ✅ |
| pdf_lap_times | 7613 | 7613 ✅ |
| pdf_lap_times_v2_staging | 7710 | 7710 ✅ |

4. 管理テーブルの更新（許可範囲・期待どおり）:
   - `source_file_registry` 366→**372**（新規6・更新26・不変340 / queued=364・gated=1・incomplete=7）
   - `import_queue` 358→**364**（全 pending）
   - `data_quality_log` 72→440 / `analysis_run_log` 1→2（最新 `20260706T135020_extraction_scan`・status=success）
   - scanner 自前バックアップ: `02_DATABASE/_backup_extraction_scan_20260706_135020/`

## 3. rollback

- UI: `ts24_workbench.py` の `ImportQualityTab` 追加ブロック（ボタン/`_lbl_scan`/`_run_scan`/`_scan_summary`）を除去するのみ。
- DB: 業務テーブル無変更のため不要。管理テーブルは scanner の冪等性 + 自前バックアップで復元可能。

## 4. Multi-agent operating check

- Workbench/UI: ボタン/ラベル追加・7タブ無回帰・非クラッシュガード。
- 2D intake: `extraction_scan.py` 再利用（無変更）・registry/queue 冪等・manifest_hash 重複防止は既存のまま。
- DB integrity: 業務6テーブル before==after 検証・書込は `assert_mgmt_only()` ガード内の管理4テーブルのみ。
- Operations: Tatsuki 操作 = 📥 タブ → 🔍 Session Scan → 結果ダイアログ（Scan only 明示・ログパス表示）。
- Quality Gate: py_compile / offscreen smoke / exit code 処理 / `reports/session_scan_*.log`。
- Supervisor: session extraction staging・provisional 3テーブル・schema 変更・Supabase・DB Master・origin push・新2D本取込は**別承認のまま**。

## 5. 残作業（各別承認）

- **GUI 最終目視は Tatsuki ローカル**（`python3 ts24_workbench.py` → 📥 Import/Quality → 🔍 Session Scan）。
- 次の実装単位 = Task 3: `session_extract_staging.py` + provisional 3テーブル（正本DBへの新テーブル追加 = 別GO）。
- origin push / Supabase / DB Master は従来どおり別承認。
