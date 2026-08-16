# Race Weekend workflow Phase B-3: Workbench provisional overlay 承認前 readiness

- 日付: 2026-07-06
- 種別: **Phase A read-only readiness（設計凍結のみ）**（正本DB `mode=ro` のみ・コード/DB/Excel/UI 無変更）
- 設計元: `reports/race_weekend_live_workflow_design_20260706.md` §3 Stage 3（設計 Task 5）
- 前提: Phase B-2（§53）apply 済み。provisional 3テーブルに Round7 JA52 FP が staging 済み
  （`runs_provisional`=3 / `laps_provisional`=15 / `lap_suspension_provisional`=15・quality_status 全 PASS・
  run_id = `PROV_20260612_ROUND7_MISANO_FP_JA52_R1..R3`）— 本 readiness で read-only 実測再確認済み。
- 成果物: 本レポートのみ。**実装は `Workbench provisional overlay GO` 受領後のみ**。

---

## 1. 目的 / ゲート

Race Weekend 中に staging 済みの provisional データ（現状 Round7 JA52 FP）を、
Workbench の **🦾 Suspension/Posture（`PostureAnalysisTab`）** で final データと重ねて確認できるようにする
UI 変更（Task 5）の設計を凍結する。

- 変更対象は **`ts24_workbench.py` の読み取り側のみ**（read-only feature）。正本DBへの書込・schema 変更は一切ない。
- 業務6テーブル（runs / laps / lap_suspension / race_results / pdf_lap_times / pdf_lap_times_v2_staging）と
  provisional 3テーブルはいずれも本実装で変更しない（SELECT のみ）。
- 次ゲート文言 = **`Workbench provisional overlay GO`**。

作業前 `git status --short`（05_SCRIPTS・HEAD `5651d97`・記録のみ・無変更）:
tracked M = CLAUDE.md / build_excel_master.py / reports/round7_race_results_apply_dry_run_20260629.md /
requirements_workbench.txt / ts24_workbench.py（§48/§51 の未コミット diff）。untracked = 既知の作業メモ md 群・
§45-53 の新スクリプト/レポート（suspension_report.py / session_extract_staging.py 等）・`reports/pptx/`・
`_backup_susp_speed_20260620-071355/`。本タスクの追加は本レポート1ファイルのみ。

---

## 2. 現状確認（read-only 精読・実測）

### 2a. `PostureAnalysisTab._load_data`（`ts24_workbench.py` L3922-3985）

- 現行 SQL は **L3930 の 1 本のみ**:
  ```python
  _rows = _con.execute("SELECT * FROM lap_suspension").fetchall()
  ```
  接続は L3926-3928 で `sqlite3.connect(self._db.db_path)` + `row_factory=Row`（メソッド内ローカル接続・都度クローズ）。
- 後処理（L3931-3962）:
  1. `pd.DataFrame([dict(r) for r in _rows])` → **列名を全小文字化**（L3933）。
  2. `_rows` が空なら **JSON フォールバック**（L3935-3940・`lap_suspension_data.json`＝stale 30列・§0）。
     両方無ければ警告ラベルで return（L3941-3947）。
  3. `apex_susf_avg`/`apex_susr_avg` が存在すれば **pitch / heave / pitch_pct を派生**（L3949-3962）。
     provisional 行も apex 列を持つ（実測・下記 §3）ため同一パスで派生される。
  4. ステータスラベル（riders 列挙）→ Circuit コンボ再構築（L3969-3975・`全サーキット` + unique circuit）→
     `_update_all()`（APEX分析/Damping 描画）→ **L3980 `self._phase_cmp.set_dataframe(self._df)`**
     （try/except 保護）で 3フェーズ Run比較へ同じ DataFrame を渡す。
- 例外は L3983-3985 で捕捉しラベル表示（非クラッシュ）。`refresh()`（L3918）は DB ウォッチャから呼ばれ
  `_load_data()` を再実行 → **provisional apply 後の自動反映もこの1本の SQL 差し替えだけで成立**。

### 2b. `PhaseRunCompareWidget`（L3059-3860）

| 項目 | 実測挙動 | provisional への影響 |
|---|---|---|
| Run リスト構築 | `_repop_runs`（L3369）: `_base_df()` から `run_id` で `drop_duplicates` → `(round, session, rider, run_no)` ソート → `_run_label(rec)`（L3541: `f"{rider}  {sess}  {rn}  ({rnd})"`）。run_id は `UserRole` に格納 | **run_id 列が行にあれば自動で出る**。PROV_ 行は rider=JA52/session=FP/run_no=1..3/round=ROUND7 を持つため `JA52  FP  R1  (ROUND7)` と表示（このままでは final と区別不能 → §5 表示案） |
| `_base_df()`（L3495） | Circuit/Rider/Session コンボ + lap_time 60-300s。**列名参照のみ**（`"circuit" in df.columns` ガード付き） | provisional 15行は lap_time_s 全て有効域 → そのまま通る |
| `_checked_run_ids()`（L3437） | QListWidget のチェック済み UserRole（=run_id）リスト | PROV_ run_id がそのまま返る |
| フィルタコンボ | `_repop_circuit/_rider/_session`（L3314-3367）: DataFrame の unique 値から動的構築 | **MISANO / FP は DataFrame に行がある時点で自動出現**（実測: overlay SQL 実行後 MISANO の session=['FP']）。コード変更不要 |
| 描画/テーブル | `_valid_xy`/`_valid_fr`/`_mean_valid`/`_fill_table` 全て**列名ガード**参照。テーブルは固定14列 `_TCOLS`（L3105） | 追加列（data_stage 等）が DataFrame にあっても不参照＝無害 |

### 2c. 他 Posture サブタブ（📊 APEX分析（基本） / ⚙️ Damping / Phase）への流入

- 両サブタブは `_update_all()`（L4532）→ `_filtered_df()`（L3993・外側 Circuit コンボ + 物理限界 + lap_time
  フィルタ）で **同じ `self._df` を消費**する。overlay 実装後は provisional 15行も両タブに流入する。
- 挙動: 「全サーキット」表示では MISANO の点が散布図/推移に混ざる（run 単位の区別 UI なし）。
  Circuit=MISANO を選べば provisional のみが見える（final の MISANO 行は 0）。
- **判断: 許容（v1）**。理由: ①quality_status 全 PASS の実測値であり品質面の混入リスクは低い
  ②MISANO は新規サーキットで既存サーキットの見え方は不変 ③lap 雲ビューに run 単位マークを足すのは
  Task 5 の最小 diff 方針に反する。**readiness 注記として「APEX分析/Damping では final/provisional の
  視覚区別なし（区別が必要な比較は 3フェーズ Run比較タブで行う）」を実装レポートと Obsidian に明記**する。
  将来必要なら data_stage 列（§4 で DataFrame に載る）でマーカー分岐可能（v2 候補・今回はしない）。

### 2d. `_on_create_report`（L3446-3492）と provisional

- 現行: `_base_df()` + `_checked_run_ids()` を **無検査で** `suspension_report.build_report_v2/build_report_pdf`
  へ渡す。PROV_ run が checked に混ざっていてもそのまま PPTX/PDF が生成される。
- `suspension_report.py` 側（read-only 確認）: `build_report_v2`（L781）は渡された df を run_ids で絞るだけ。
  cover は `_resolve_scope`（L690・circuit/rider/session の値のみ）、Run ラベルは `_run_records`（L153・
  rider/session/run_no）、ファイル名トークンは `_ascii_token`（L670）。
  → **PROV run を含めても cover・スライド・ファイル名のどこにも provisional 表記は出ない**
  （例: `suspension_report_v2_MISANO_JA52_FP_<TS>.pptx` は final 由来と完全に同形）。
  なお Workbench 経由の df には `_is_outlap` 列が無く `run_best` は全 lap fallback（final でも同じ・無回帰）。
- → Task 6（Report v2 provisional モード）が未実施の間のガードが必須（§6 で判断を凍結）。

### 2e. 列互換（69列 + 2列追加の安全性）

- `_load_data` は `SELECT *` → `dict(r)` → DataFrame で、**列数に依存するコードは PostureAnalysisTab /
  PhaseRunCompareWidget に存在しない**（grep 実測: 全て `col in df.columns` の名前ガード、テーブル UI は
  固定列リスト `_TCOLS`(14) / `_fill_dp_table` の固定列 / APEX ポップアップの `_INFO` ガード付き選択）。
- overlay SQL は結果 **71列**（69 + `data_stage` + `quality_status`）。両追加列は誰も参照しない＝無害。
  小文字化（L3933）後も `data_stage`/`quality_status` のままで既存列と衝突しない（実測: 結果列名 71 個ユニーク）。
- `suspension_report.py` も列名参照のみ（PHASE_POS/PHASE_SPD 列 + run メタ）で列数非依存。
- **結論: 2列追加による破壊リスクなし**。

---

## 3. overlay SQL 案（実DB SELECT 検証済み・2026-07-06 実測）

### 3a. 前提実測（正本DB `mode=ro`）

- `lap_suspension` = 69列 / 1202行。`lap_suspension_provisional` = **75列**（先頭69列が final と
  **名前・順序とも完全一致**、末尾に provenance 6列 `data_stage / intake_ts / source_manifest_hash /
  source_file_path / provisional_event_key / quality_status`）。
- → provisional 側は `SELECT *` 不可（列数不一致）。**明示列リストが必要**。

### 3b. 推奨 SQL（最小 diff・PRAGMA から列リストを動的生成）

`_load_data` の L3928-3930 ブロックを次に置換（他は無変更）:

```python
with _sqlite3.connect(_db_path) as _con:
    _con.row_factory = _sqlite3.Row
    _has_prov = _con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table'"
        " AND name='lap_suspension_provisional'").fetchone() is not None
    if _has_prov:
        _cols = ", ".join(
            f'"{r[1]}"' for r in _con.execute("PRAGMA table_info(lap_suspension)"))
        _sql = (
            "SELECT *, 'final' AS data_stage, NULL AS quality_status"
            " FROM lap_suspension"
            " UNION ALL "
            f"SELECT {_cols}, 'provisional', quality_status"
            " FROM lap_suspension_provisional")
    else:
        _sql = "SELECT * FROM lap_suspension"   # 従来どおり（fallback）
    _rows = _con.execute(_sql).fetchall()
```

- 列リストを PRAGMA で動的生成することで、将来 `lap_suspension` に列追加（§44 の前例）があっても
  SQL を手修正せずに追従する（provisional 側が同時に列追加されない場合はその時点で明示的に落ちる＝
  サイレント不整合を許さない）。
- **実DB 検証結果（read-only 実行済み）**: 総行 **1217**（final 1202 + provisional 15）/ 結果 **71列** /
  `data_stage` 集計 final=1202・provisional=15 / **lap_id 重複 0** / provisional は
  (MISANO, FP, JA52) のみ / quality_status 全 PASS / `apex_susf_avg` 等の主要列に実数値
  （例 71.08 / 15.89 / lap_time_s 127.205）→ pitch/heave 派生（§2a-3）も成立。
  pandas 変換（`dict(r)` → DataFrame → 小文字化）も (1217, 71) で正常、MISANO の session=['FP'] を確認。
- fallback 判定 `SELECT name FROM sqlite_master WHERE type='table' AND name='lap_suspension_provisional'`
  も実DBで動作確認済み（現状 = 存在 → overlay 経路）。テーブルが無い古い/コピーDBでは自動的に
  従来 SQL（legacy）へ落ち、**Phase B-2 以前の DB でも無回帰**。

---

## 4. UI 表示案（設計凍結）

### 4a. Run リストの provisional マーク（必須・最小 diff）

`_run_label`（L3541）を run_id 参照付きに変更（rec には `meta_cols` 経由で run_id が既に入っている・L3375）:

```python
@staticmethod
def _run_label(rec, short=False):
    ...（既存の組み立てそのまま）...
    label = f"{rider}  {sess}  {rn}  ({rnd})"
    if str(rec.get("run_id", "")).startswith("PROV_"):
        label = f"⏳ {label} (prov)"
    return label
```

- 表示例: **`⏳ JA52  FP  R1  (ROUND7) (prov)`**。既存ラベル形式（rider/session/Rn/round）を維持しつつ
  先頭絵文字 + 末尾 `(prov)` で final と一目で区別。short=True（Report 用短縮ラベル）にも同じ分岐を適用。
- 判定は **`run_id.startswith("PROV_")`** に統一（§52 の run_id 規約）。`data_stage` 列でも判定可能だが、
  run_id 判定は JSON フォールバック時・列欠落時にも安全（列非依存）。

### 4b. `Data stage: All / Final / Provisional` フィルタ — **v1 では見送り（defer）**

- 理由: ①Run 単位の選択 UI（チェックリスト）+ ⏳ ラベルで provisional の分離・除外は既に可能
  ②コンボ追加は `_repop_*` 連動・選択保持ロジックへの波及が大きく最小 diff 方針に反する
  ③現状 provisional は 1 サーキット 1 セッションのみで実需が薄い。
- 将来 provisional が複数イベントに広がった時点で v2 として再検討（`data_stage` 列は §3 の SQL で既に
  DataFrame に載るため、追加コストは UI のみ）。

### 4c. グラフ/テーブルの混在表示 — **run 単位の分離で足りる（マーカー変更なし）**

- 3フェーズ Run比較のグラフは**色=Run**で系列が完全分離しており、Run リストの ⏳ ラベルで
  どの系列が provisional か判別できる。点マーカー/破線の追加分岐は行わない（凡例ラベルに
  `_run_label` 経由で ⏳ が入るため凡例上でも判別可）。
- 数値テーブル（`_fill_table`）の Run ID 列には PROV_ prefix がそのまま出る（無変更で判別可）。
- APEX分析/Damping サブタブは §2c のとおり視覚区別なしを許容（注記で運用）。

---

## 5. Report v2 暫定ガード判断（Task 6 未実施の間）

**推奨 = 警告ダイアログ + opt-in 続行（既定ボタン = キャンセル）。ハードブロックはしない。**

`_on_create_report`（L3446）の run_ids 取得直後に挿入する最小ガード:

```python
prov = [r for r in run_ids if str(r).startswith("PROV_")]
if prov:
    ret = QMessageBox.warning(
        self, "Provisional data を含みます",
        f"選択 Run に provisional（速報・未確定）が {len(prov)} 件含まれます。\n"
        "現行 Report v2 は cover・ファイル名に provisional 表記を付けません\n"
        "（Task 6 未実装）。生成物はチーム外提出に使わないでください。\n\n"
        "このまま生成しますか？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if ret != QMessageBox.StandardButton.Yes:
        return
```

- **警告（opt-in 続行）を推す理由**:
  1. Phase B-3 の目的は「Race Weekend 中に速報データで判断を速くする」こと。ハードブロックだと
     週末中に一番欲しい「その場の簡易レポート」が使えず、B-3 の価値を自ら削る。
  2. provisional は quality gate PASS 済みの実測値（§53）であり、データ品質面の危険は低い。
     リスクは「provisional 表記の無い成果物が final と誤認されて流通する」ことに限定される
     （§2d 実測: cover/ファイル名とも無表記）→ これは警告文で明示し、既定=キャンセルで
     誤クリック生成を防ぐことで十分制御できる。
  3. ガードは約10行の追加のみで、Task 6（provisional モード=cover リボン + filename トークン）実装時に
     この分岐を「自動で provisional モードへ切替」に置き換えるだけで済む（捨てコストが最小）。
- 代替案（ハードブロック=Task 6 完了まで PROV 混在時は生成拒否）は「誤流通ゼロ」を最優先する場合のみ。
  今回は Tatsuki 単独運用・ローカル出力・警告文で提出禁止を明示、で足りると判断した。
  **本 readiness の推奨は警告方式。GO 時に異議が無ければこれで凍結。**

---

## 6. fallback / rollback

- **fallback（DB 側）**: §3b のとおり `sqlite_master` 存在チェックで provisional テーブルが無い DB では
  自動的に従来 SQL。JSON フォールバック（L3935）経路も不変（overlay 結果 0 行 → JSON の順序は従来同様。
  現実には final 1202 行があるため到達しない）。
- **rollback**: `ts24_workbench.py` の UI diff を revert するのみ（`_load_data` SQL ブロック /
  `_run_label` 分岐 / `_on_create_report` ガードの3箇所）。**DB は一切触っていないため DB 側の
  rollback は不要**（read-only feature）。provisional テーブル自体の撤去は §53c の rollback（別件）。

---

## 7. Phase C 検証計画（GO 後・実装時に全項目実施）

| # | 検証 | 方法 / 合格基準 |
|---|---|---|
| 1 | 構文 | `PYTHONPYCACHEPREFIX=/tmp/ts24_pycache python3 -m py_compile ts24_workbench.py` PASS |
| 2 | offscreen smoke | `QT_QPA_PLATFORM=offscreen` で `MainWindow(db)` 構築 → **7タブ維持**・例外なし |
| 3 | overlay 行数 | `PostureAnalysisTab._df` が **1217 行 / data_stage 列あり**（final 1202 + prov 15） |
| 4 | PROV 表示 | Circuit=MISANO / Rider=JA52 / Session=FP で Run リストに **⏳ … (prov) が 3 件**（R1..R3）表示・チェックで描画/テーブルに PROV_ 行 |
| 5 | final 無回帰 | 既存サーキット（例 ARAGON）の Run 件数・描画・APEX分析/Damping 行数（1081 等）が実装前と一致 |
| 6 | fallback | **正本DBを `/tmp` にコピー → コピー上で `DROP TABLE runs_provisional/laps_provisional/lap_suspension_provisional` → `WorkbenchDB(db_path=コピー)` で offscreen 起動** → legacy SQL 経路で 1202 行・例外なし（正本は不変のまま検証できる具体法として推奨。monkeypatch より実経路に忠実） |
| 7 | Report v2 ガード | offscreen で PROV run をチェックした状態の `_on_create_report` 相当分岐を単体検証（ダイアログ分岐は prov 抽出ロジックを関数化してユニットテスト + 実 GUI は Tatsuki 目視）。final のみ選択時は警告なしで従来どおり生成 |
| 8 | GUI 最終目視 | Tatsuki ローカル `python3 ts24_workbench.py`（ヘッドレス不可・従来どおり） |

---

## 8. Multi-agent operating check（§20 運用ルール準拠）

- Extraction（測る）: 対象外（本タスクは 2D 抽出なし・§53 成果物を read-only 参照のみ）。
- Quality Gate（疑う）: overlay SQL を実DBで SELECT 検証（行数/列数/lap_id 重複0/値サンプル）・
  列互換を grep 全数確認・Report v2 の provisional 無表記リスクを実コードで確認 → ガード必須と判定。
- DB Integration（保存）: **書込ゼロ**（`mode=ro` のみ・git も無変更）。
- Documentation: 本レポート + CLAUDE.md 追記（実装フェーズで §54 として記録予定）。
- Supervisor（止める）: Report v2 の「provisional 表記なしで生成できてしまう」問題を承認境界として
  §5 に判断を明文化（警告方式・既定キャンセル）。実装は GO 受領までブロック。
- Tatsuki（決める）: `Workbench provisional overlay GO` + §5 ガード方式の承認待ち。

---

## 9. 未実施リスト（本 readiness 時点）

| 項目 | 状態 |
|---|---|
| 残り session apply（Round7 JA52: QP / RACE1 / RACE2 / WUP1 / WUP2 = insertable 9 outing / 64 laps） | 未実施（§53c・各別承認） |
| **Task 5: Workbench provisional overlay 実装** | 本 readiness の対象。**`Workbench provisional overlay GO` 待ち** |
| Task 6: Report v2 provisional モード（cover リボン + filename トークン） | 未実施（それまで §5 の警告ガードで暫定運用） |
| Supabase（provisional の同期・remote_extra 24 cleanup） | 未実施（provisional は設計上同期対象外・cleanup は §46 提案のまま） |
| DB Master 再生成 / race_results 由来新シート設計 | 未実施（別承認） |
| origin push（§48/§51 以降の未コミット diff 含む） | 未実施（Tatsuki レビュー後） |
| Post-event final 化（full rebuild + provisional 突合 → cutover → provisional クリア） | 未実施（§50 Stage 5・別承認） |
