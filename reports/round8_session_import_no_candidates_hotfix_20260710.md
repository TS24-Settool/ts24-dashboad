# Round8 Session Import "No Candidates" Hotfix — Apply Report

Date: 2026-07-10
Priority: P0 field recovery during Round8
Author: Claude Code
Instruction: `05_SCRIPTS/reports/round8_session_import_no_candidates_hotfix_code_instruction_20260710.md`
Scope: Workbench `Import / Quality` の zero-candidate 診断改善 + 安全な Session Scan 復旧導線
Result: **実装・検証 完了（業務テーブル無変更・Round8 guard 不変）**

---

## 1. Root cause（確定）

Tatsuki が Round8 2D data を保存したが Workbench `Session Import (staging)` が
`新規取込候補はありません（queue pending 0）` を表示した。現地・DB の read-only 確認で確定した原因:

- `DATA 2D/20260710-ROUND8-JA52` は**ディスク上に実在**（`FP-JA52-01.MES` / `FP-JA52-02.MES`・
  各 `.DDD`/`.LAP`/`.HED` 完備・mtime 2026-07-10）。`build_master_db.discover_outings()` は
  2 outing（nested）を検出可能。
- しかし正本DBの `source_file_registry` / `import_queue` に **Round8 行は 0**（`file_path LIKE '%20260710-ROUND8%'` = 0）。
- `session_extract_staging.py`（= Session Import の実体）は **filesystem を直接読まず `import_queue` を読む**。
  → Session Scan で管理テーブルへ登録される前に Import を押すと、候補0（exit 1）になる。
- 従来UIはこの状態を「候補なし」としか表示せず、**復旧手順（先に Session Scan）を説明しなかった**ため現地で詰まる。

> つまり「Round8 data はディスクにあるが未Scan」＝ **正常なワークフロー順序の未実行**であり、
> データ欠損でもコードバグでもない。UI が復旧導線を出さなかったことが唯一の問題。

## 2. Exact code change（`ts24_workbench.py` のみ・`ImportQualityTab`）

**変更ファイル = `05_SCRIPTS/ts24_workbench.py` 1ファイルのみ**。
`extraction_scan.py` / `session_extract_staging.py` は無変更（Round8 guard §68 完全保持）。

### 2a. 新規: `_looks_unstable(ev_dir)`
半端コピー / iCloud placeholder / コピー継続中の兆候を **name + stat のみ**で検出（ファイル内容は開かない
＝ iCloud DL を誘発しない・§24a 原則）。
- `.icloud` / `._` / `.~` / `.partial` / `.tmp` / `~$` を placeholder として計数。
- mtime が 30 秒以内のファイルを「コピー継続中の可能性」として計数。
- 兆候があれば説明文字列、無ければ `""`。

### 2b. 新規: `_diagnose_zero_candidates(ev)`（read-only）
dry-run 候補0（exit 1）の原因を切り分ける。管理テーブルを SELECT するのみ（書込なし）。
戻り値 `(case, title, message, offer_scan)`:

| case | 条件 | offer_scan | メッセージ要旨 |
|---|---|:---:|---|
| `folder_missing` | `DATA 2D/<event>` が存在しない | ✕ | event 名を確認。DATA 2D 内の `ROUND8` 候補を併記 |
| `not_scanned` | folder あり・registry/queue に該当 0 | ○ | 「データはディスク上にあるが未Scan。先に Session Scan → 再 Import」 |
| `unstable` | folder あり・未登録・かつ未安定サイン検出 | ○ | 「コピー/同期が未完了の可能性。Finder の雲表示消失を待って Scan」 |
| `not_scanned`(registryのみ) | registry あり・queue 0 | ○ | 「Scan 再実行で queue 作成」 |
| `no_pending` | queue あり・pending 0 | ✕ | 「既に取込済(awaiting_gate/skipped/failed)。要確認/未処理キュータブ確認」 |
| `unknown` | 上記以外 | ✕ | dry-run ログ・検出チェックタブを確認 |

### 2c. `_run_import` の exit==1 分岐を差し替え
従来の「候補なし」info ダイアログ1本 → `_diagnose_zero_candidates(ev)` で原因別メッセージ。
`offer_scan=True` のときは **「Session Scan を実行」ボタン付きダイアログ**を出し、押下時に既存
`self._run_scan()`（`extraction_scan.py`・管理テーブルのみ）を実行 → 「Scan 後にもう一度 Import」を案内。
**auto-apply は行わない**（provisional 書込は従来どおり人手の Apply ボタン + event guard 経由のみ）。

## 3. 現在の `20260710-ROUND8-JA52` の復旧手順

1. Finder でクラウド/アップロード表示が消えていることを確認（本データは既に安定＝下記テストで `_looks_unstable=""`）。
2. Workbench `📥 Import / Quality` タブで **`🔍 Session Scan`** を押す（管理テーブルのみ更新・業務テーブル不変）。
3. Scan 完了後 **`⬇ Session Import (staging)`** を押す。
4. event 入力に `20260710-ROUND8-JA52` を入れる（`_guess_event_key` が自動 pre-fill）。
5. dry-run サマリが Round8 / JA52 / FP の候補のみであることを確認 → `Apply`（既定 Cancel）。

※ もし手順3で「候補なし」が出ても、本 hotfix により **未Scan なら「Session Scan を実行」導線が自動表示**されるため、
そこから 1 クリックで Scan → 再 Import できる。

### CLI 等価（参考・Round8 guard 付き）
```bash
# 1) 検出のみ確認（DB 書込なし）
python3 extraction_scan.py --dry-run --min-age 0
# 2) 実 Scan（管理テーブルのみ）
python3 extraction_scan.py
# 3) Round8 限定 dry-run → apply（event + required-round guard・§68）
python3 session_extract_staging.py --event 20260710-ROUND8-JA52 --required-round ROUND8
python3 session_extract_staging.py --apply --event 20260710-ROUND8-JA52 --required-round ROUND8
```

## 4. Tests（全 PASS）

1. `python3 -m py_compile ts24_workbench.py extraction_scan.py session_extract_staging.py` → **PASS**。
2. `DATA 2D/20260710-ROUND8-JA52` 実在確認: `FP-JA52-01.MES` / `FP-JA52-02.MES`・各 `.DDD`/`.LAP`/`.HED` あり。
   `discover_outings()` → 2 outing（nested）検出。
3. Scan 前の DB に Round8 registry/queue 行なし（= 0）を確認。
4. `extraction_scan.py --dry-run --min-age 0` → 検出 2D=315/report=29/pdf=64=408（Round8 含む）・**DB 書込なし**
   （dry-run 後も registry/queue Round8 = 0）。
5. Workbench offscreen smoke（`QT_QPA_PLATFORM=offscreen`）:
   - 上位7タブ構築 OK（無回帰）。
   - `_diagnose_zero_candidates('20260710-ROUND8-JA52')` = `not_scanned` / offer_scan=True。
   - `_diagnose_zero_candidates('20260710-ROUND8-NOPE')` = `folder_missing` / offer_scan=False。
   - `_looks_unstable(<real dir>)` = `""`（本データは安定・placeholder なし・mtime 十分古い）。
   - `_run_import`（subprocess exit1 を monkeypatch）: 「閉じる」→ scan 呼出 **0**、
     「Session Scan を実行」→ scan 呼出 **1**（安全導線が正しく配線されている）。
6. **GUI 最終目視は Tatsuki ローカル**（`python3 ts24_workbench.py`・ヘッドレス不可）。

## 5. No-write proof（業務テーブル）

上記全テスト（診断は read-only・実 apply は未実行・実 Scan も本作業では未実行）の前後で:

| table | before | after |
|---|---:|---:|
| runs | 286 | 286 |
| laps | 1279 | 1279 |
| lap_suspension | 1279 | 1279 |
| race_results | 866 | 866 |
| pdf_lap_times | 7613 | 7613 |
| runs/laps/lap_suspension_provisional | 0/0/0 | 0/0/0 |
| source_file_registry (Round8) | 0 | 0 |
| import_queue (Round8) | 0 | 0 |

**before == after**（業務・provisional・Round8 管理行すべて不変）。dry-run scan も DB 書込なしを実証。

## 6. Forbidden 遵守（本作業で未実施）

- Round8 以外の import ✕ / event filter なし apply ✕ / Round8 final化 ✕ / canonical business tables 書込 ✕ /
  historical `import_queue` cleanup ✕ / DB Master refresh ✕ / Supabase sync ✕ / commit・push ✕ /
  folder watcher auto-apply ✕。
- Round8-only guard（§68 `--event` / `--required-round ROUND8`）は**無変更で維持**。診断は guard を一切弱めない。
- **本作業では実 Session Scan / 実 Session Import(apply) を実行していない**（現地で iCloud 同期状態を
  Finder で目視確認する運用のため、Scan→Import の実行は Tatsuki のローカル操作に委ねる。データ安定性は
  `_looks_unstable=""` で確認済＝安全に実行可能）。

## 7. rollback / 変更範囲

- rollback: `git checkout -- ts24_workbench.py`（DB 無変更のため他影響なし）。
- 変更: `ts24_workbench.py`（`ImportQualityTab` に `_looks_unstable` / `_diagnose_zero_candidates` 追加 +
  `_run_import` exit==1 分岐の差し替え）。
- 新規: 本レポート。
- 記録: `CLAUDE.md §69`（予定）/ Obsidian `log.md` / `CURRENT_STATE.md` / `AI_HANDOFF_LATEST.md` /
  `00_INBOX/FOR_CLAUDE_CODE.md` Result 欄。
