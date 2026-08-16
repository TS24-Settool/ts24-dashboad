# Race Weekend workflow Phase B-3 (Task 5): Workbench provisional overlay apply

- 日付: 2026-07-06
- 種別: **Phase C 実装 apply**（Tatsuki 明示 GO `Workbench provisional overlay GO` 受領済）
- 設計元（凍結済 readiness・完全準拠）: `reports/workbench_provisional_overlay_readiness_20260706.md`（§54）
- 変更ファイル: **`ts24_workbench.py` のみ**（他ファイル・他の未コミット diff は不干渉。git commit なし）
- DB: **完全 read-only**（正本DB `02_DATABASE/ts24_unified.db` への書込・queue 変更・insert 一切なし。実測で不変を確認 §3-7）

---

## 1. 変更内容（UI diff 3箇所 = rollback 対象）

### 1a. `PostureAnalysisTab._load_data` — overlay SQL + legacy fallback（L3946-3973 付近）

- 旧: `_rows = _con.execute("SELECT * FROM lap_suspension").fetchall()`（1本のみ）
- 新: `sqlite_master` で `lap_suspension_provisional` の存在チェック（L3954-3956）→ 存在時は
  **PRAGMA table_info(lap_suspension) から 69 列の明示列リストを実行時生成**（L3958-3960）し
  `SELECT *, 'final' AS data_stage, NULL AS quality_status FROM lap_suspension UNION ALL
  SELECT <69列>, 'provisional', quality_status FROM lap_suspension_provisional`（L3961-3967）。
- **overlay ブロック全体を try/except で保護**: overlay 中のいかなる例外も `_rows = None` に落とし、
  テーブル不存在時と同じ legacy `SELECT * FROM lap_suspension`（L3970-3972）へフォールバック。
  overlay の問題でタブが壊れることはない。JSON フォールバック経路（`_rows` 空時）は不変。
- 列リストを PRAGMA 動的生成することで final schema の将来列追加（§44 前例）に自動追従。
  provisional 側が同時に列追加されない場合はその時点で明示的にエラー → legacy fallback（サイレント不整合なし）。

### 1b. `PhaseRunCompareWidget._run_label` — prov 分岐（L3556-3570 付近）

- 既存ラベル組み立て（full: `f"{rider}  {sess}  {rn}  ({rnd})"` / short: `f"{rider} {sess}{rn}"`）はそのまま、
  末尾で `str(rec.get("run_id", "")).startswith("PROV_")` の場合のみ `⏳ {label} (prov)`（L3567-3569）。
- readiness §4a どおり short=True（Report 用短縮ラベル）にも同一分岐を適用。rec の run_id は
  `_repop_runs` の `meta_cols`（L3382 付近）経由で既に供給されており run list builder 側は無変更。

### 1c. `PhaseRunCompareWidget._on_create_report` — Report v2 暫定ガード（L3458-3470）

- `run_ids = self._checked_run_ids()` 直後に `PROV_` prefix の run を抽出し、1件以上あれば
  `QMessageBox.warning`（タイトル「Provisional data を含みます」・readiness §5 の文面 verbatim:
  provisional 表記なし（Task 6 未実装）・チーム外提出禁止・「このまま生成しますか？」）。
- ボタン = **Yes | Cancel・既定 = Cancel**。Yes の明示 opt-in のみ続行、それ以外は return（生成なし）。
  final のみ選択時はガード非表示で従来どおり。ハードブロックはしない（readiness §5 凍結判断）。

その他の変更なし（Data stage フィルタは readiness §4b どおり defer。APEX分析/Damping は共有 DataFrame に
provisional 15 行が自然流入するのみでコード無変更 — §2c 注記参照）。

---

## 2. 検証結果（Phase C 検証計画 §7 全項目）

| # | 検証 | 結果 |
|---|------|------|
| 1 | `python3 -m py_compile ts24_workbench.py` | **PASS** |
| 2 | offscreen smoke（QT_QPA_PLATFORM=offscreen）: `MainWindow(db)` 構築・**7タブ維持**・Suspension/Posture（PostureAnalysisTab）構築・3フェーズ Run比較（PhaseRunCompareWidget）到達 | **PASS**（例外なし） |
| 3 | overlay データ: `PostureAnalysisTab._df` = **1217 行**（final 1202 + provisional 15）・`data_stage` 列あり（74列 = SQL 71 + 派生 pitch/heave/pitch_pct）・data_stage 集計 final=1202/provisional=15・Circuit コンボに **MISANO** 出現・MISANO の Session=**FP** 出現 | **PASS** |
| 4 | PROV 表示: Circuit=MISANO / Rider=JA52 / Session=FP で Run リスト = **ちょうど3件** `PROV_20260612_ROUND7_MISANO_FP_JA52_R1..R3`、ラベル = `⏳ JA52  FP  R1  (ROUND7) (prov)`（R2/R3 同形）。short ラベル分岐も `⏳ JA52 FPR1 (prov)` で PASS | **PASS** |
| 5 | final-only 無回帰: JEREZ / DA77 / TEST1_DAY1 → Run 7件・ラベルに ⏳/(prov) 一切なし・`_base_df()` = **66 行**（§48 記録の 66 laps と一致＝実装前と同数） | **PASS** |
| 6 | fallback: 正本DBを scratchpad にコピー → コピー上で provisional 3テーブルを DROP → `WorkbenchDB(コピー)` で offscreen 構築 → **legacy SQL 経路で 1202 行**・`data_stage` 列なし・MISANO 非表示・status「✅ SQLite (1202 laps)」・例外なし。正本DBは不変（下記 #7） | **PASS** |
| 7 | Report v2 ガード: offscreen で PROV 3 run をチェック → QMessageBox を monkeypatch して `_on_create_report()` 実行 → **warning ダイアログ1回表示**（タイトル/文面一致・prov=3件検出）・**既定ボタン = Cancel**・Cancel 返答で **report 生成なし**（information/critical 呼び出しゼロ＝PROV データの report は未生成） | **PASS** |
| 8 | 正本DB不変（mode=ro・作業前後比較）: 業務6テーブル **runs 275 / laps 1202 / lap_suspension 1202 / race_results 866 / pdf_lap_times 7613 / pdf_lap_times_v2_staging 7710** + provisional 3テーブル **3 / 15 / 15** — before==after 完全一致 | **PASS** |

- 検証スクリプト（セッション scratchpad・非コミット）: `verify_overlay.py`（14/14 PASS）/ `verify_fallback.py`。
- **GUI 最終目視（§7-8）は Tatsuki ローカル**: `python3 ts24_workbench.py`（ヘッドレス不可・従来どおり）。

---

## 3. rollback

**`ts24_workbench.py` の UI diff 3箇所を revert するのみ。DB 側の rollback は不要**（read-only feature・DB 無変更）:

1. `_load_data` の overlay SQL ブロック（L3946-3973）→ 旧 `_rows = _con.execute("SELECT * FROM lap_suspension").fetchall()` 1行に戻す。
2. `_run_label` の PROV_ 分岐（L3556-3570）→ 旧 return 2行形式に戻す。
3. `_on_create_report` の警告ガード（L3458-3470）→ ブロック削除。

provisional 3テーブル自体の撤去は §53c の rollback（別件・本タスク対象外）。

---

## 4. Multi-agent operating check（§20 運用ルール準拠）

- Extraction（測る）: 対象外（2D 抽出なし。§53 成果物を SELECT のみで overlay 表示）。
- Quality Gate（疑う）: overlay 行数/列数/PROV run_id 完全一致/final 無回帰(66行)/fallback 1202行/ガード既定 Cancel を
  offscreen 実測で全数検証。正本DB before==after を mode=ro で機械照合。
- DB Integration（保存）: **書込ゼロ**（UI read-only feature・queue/insert なし・git commit なし）。
- Documentation: 本レポート + CLAUDE.md §55 追記は親セッション判断（本タスクはレポートのみ）。Obsidian へは注記
  「**APEX分析/Damping では final/provisional の視覚区別なし（区別が必要な比較は 3フェーズ Run比較タブで行う）**」を転記のこと（readiness §2c）。
- Supervisor（止める）: Report v2 の provisional 無表記リスクは §5 凍結どおり警告 + 既定 Cancel で制御。ハードブロックせず。
- Tatsuki（決める）: GO 受領済。GUI 最終目視のみ残。

---

## 5. 未実施リスト（本 apply 時点・各別承認）

| 項目 | 状態 |
|---|---|
| 残り session apply（Round7 JA52: QP / RACE1 / RACE2 / WUP1 / WUP2 = insertable 9 outing / 64 laps） | 未実施（§53c・各別承認） |
| Task 6: Report v2 provisional 本対応（cover リボン + filename トークン・本ガードを自動モード切替に置換） | 未実施（それまで §1c の警告ガードで暫定運用） |
| Supabase（provisional 同期は設計上対象外・remote_extra 24 cleanup 提案のまま） | 未実施 |
| DB Master 再生成 / race_results 由来新シート設計 | 未実施 |
| origin push（§48/§51 + 本 diff 含む未コミット群） | 未実施（Tatsuki レビュー後） |
| Post-event final 化（full rebuild + provisional 突合 → cutover → provisional クリア） | 未実施（§50 Stage 5） |
