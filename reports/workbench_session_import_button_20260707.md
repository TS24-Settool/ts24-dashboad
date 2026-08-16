# Workbench「⬇ Session Import (staging)」ボタン実装（Task 4）— 2026-07-07 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（Task 4・finish gate 方式=追加承認不要、apply 経路はダイアログ内確認・既定 Cancel）。
**変更 = `ts24_workbench.py` のみ**（`session_extract_staging.py`/`extraction_scan.py` 無変更・DB 書込なし・commit なし）。

## 1. 事前状態確認

- `git status --short`（記録のみ・何も revert していない）: `M CLAUDE.md / M build_excel_master.py /
  M reports/round7_race_results_apply_dry_run_20260629.md / M requirements_workbench.txt / M ts24_workbench.py`
  + 多数 untracked（既知の §46e/§48/§51/§55/§58/§60 未コミット分）。
- **Task 4 は未実装であることを確認**: `ts24_workbench.py` に `Session Import` / `session_extract_staging` 参照ゼロ。
  `ImportQualityTab` には `🔍 Session Scan`（§51）と `↻ 再読込` のみ存在。

## 2. 実装（`ts24_workbench.py`・最小差分・ImportQualityTab 内のみ）

| 箇所 | 行 | 内容 |
|---|---|---|
| module import | L18 | `import re` 追加（新メソッドで使用。既存 `_scan_summary` はローカル import のまま無変更） |
| ボタン追加 | L6763-6768 | `⬇ Session Import (staging)`（Session Scan の隣・tooltip に「provisional のみ書込/業務不変」明記） |
| 常設ラベル | L6785-6788 | `_lbl_import`（`_lbl_scan` と同スタイル） |
| 本体 | L6908-7095 | `_IMPORT_NOTE` / `_run_import()` / `_prov_counts()` / `_import_summary()` |

### クリックフロー（`_run_import`・§51 `_run_scan` と同パターン）
1. **dry-run**: `subprocess.run([sys.executable, session_extract_staging.py])`（`--apply` なし・timeout 600・
   WaitCursor・ボタン無効化）。stdout/stderr → `reports/session_import_dryrun_<TS>.log`。
2. **exit 1（候補 0）**: information ダイアログ「新規取込候補はありません（queue pending 0）」で終了。**apply 選択肢なし**。
3. **exit 0/2**: stdout から要約（insert 候補 outing/laps・PASS/WARNING/FAIL・skip。gate 行が無ければ
   queue/provisional 件数へフォールバック）→ 確認ダイアログ:
   「Apply の書込先は provisional テーブルと管理テーブルのみ。業務テーブルは変更されません」+ **Apply|Cancel（既定 Cancel）**。
4. **Apply 時のみ** `--apply` を subprocess 実行 → `reports/session_import_apply_<TS>.log` →
   `self.refresh()` + 結果ダイアログ（provisional 件数 before→after・queue 遷移・stdout のバックアップパス・
   exit 2 は FAIL 隔離注記）。exit 0/2 以外（3=assert 違反 rollback 済 等）は warning（末尾10行+ログパス）。
5. 全経路 try/except/finally（cursor 復元・ボタン復帰）＝**Workbench は落とさない**。ラベルに常時
   `staging import: provisional tables only / business tables unchanged` を表示。

## 3. 検証結果（全 PASS）

1. `PYTHONPYCACHEPREFIX=/tmp/ts24_pycache python3 -m py_compile ts24_workbench.py session_extract_staging.py` → PASS。
2. offscreen スモーク①（実 subprocess dry-run・read-only）: MainWindow **7タブ**維持・ImportQualityTab に
   Session Scan と Session Import 両ボタン存在・QMessageBox monkeypatch で確認ダイアログ表示 →
   **既定ボタン（Cancel）選択 → DB 完全不変**。`_import_summary` 単体テスト（PASS/WARNING/FAIL/skip 合成 stdout）PASS。
3. offscreen スモーク②（subprocess mock exit 1）: **0 候補ダイアログ経路** = information のみ・apply 選択肢なし・ラベル更新 OK。
4. **DB 不変**（mode=ro・作業前後）: 業務6 = **275/1202/1202/866/7613/7710**・provisional 3 = **12/79/79**・
   queue = pending 364 / awaiting_gate 12 / failed 7 / skipped 14（すべて作業前と同一）。
5. 回帰: `PostureAnalysisTab` DataFrame **1281 行**（final 1202 + provisional 79）・MISANO/JA52 **12 prov runs** 表示維持
   （絶対 DB パス使用・importlib 相対パス人工物は回避）。Report v2 provisional guard/dialog（L3463-3466
   `QMessageBox.question`「provisional reportとして生成しますか？」既定 Cancel）**無改変で存置**を grep 確認。

## 4. ★運用上の重要注意（実測で判明）

- タスク文の想定「本日 dry-run は候補 0（exit 1）」は **Round7 JA52 に限った話**。フィルタなし dry-run は
  import_queue の**歴史的 pending 364 件**（Phase 2A で登録済みの過去イベント・2B consumer 未消費）を走査し、
  実測で **insert 候補 160 outing / 1249 laps（PASS 72 / WARNING 88 / FAIL 110・skip 2）** を提示した。
  これらは既に final テーブルに取込済みの過去データであり、**現時点で Apply を押すべきではない**
  （provisional に歴史データが重複投入される）。確認ダイアログの既定 Cancel がこの誤操作を防ぐ。
  → 次レースウィークエンドでの実運用前に、歴史的 pending の skip/整理（別タスク・要承認）を推奨。
- **live apply テストは未実施**: 上記のとおり本日押すべき対象がなく（Round7 は消費済み・pending は歴史データ）、
  apply 経路は subprocess コマンドレベル（`--apply` 引数・ログ保存・exit 分岐・refresh）で検証済み。
  実 apply は次レースウィークエンドの新規 2D データ到着時に行使される。

## 5. rollback / 禁止事項遵守 / multi-agent check

- **rollback**: UI diff の revert のみ（L18 / L6763-6768 / L6785-6788 / L6908-7095）。DB 操作不要（本作業は read-only）。
- **禁止事項遵守**: Supabase 操作なし / final 化・provisional クリアなし / FAIL 7 outing 救済なし /
  DB Master 再生成なし / origin push なし / 業務テーブル書込なし / schema 変更なし。
- **multi-agent check**: Implementation（Claude Code・本UI差分）/ Quality Gate（dry-run→確認→既定 Cancel の
  誤操作遮断・DB 不変 assert は script 側に既存）/ Supervisor（歴史的 pending 160 候補の誤 Apply リスクを検出し §4 に記録・
  操作は停止側に倒す既定 Cancel）/ Documentation（本レポート+CLAUDE.md/Obsidian 記録）/ Tatsuki=GUI 最終目視
  （`python3 ts24_workbench.py` → 📥 Import / Quality → ⬇ Session Import (staging)）。

新規: 本レポート / `reports/session_import_dryrun_20260707_*.log`（スモーク実行の副産物）。変更: `ts24_workbench.py`。
