# Workbench Report v2 polish — Cover 英語化 + チーム提出用デザイン（2026-07-02 Claude Code）

- **タスク:** `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02「Report v2 polish」）。既存 Report v2 の polish/bugfix。
- **GO 不要**（install/schema/write なし・依存導入済）。正本DB・Supabase・DB Master・origin push・新2D は触らない。
- **結論: 完了。** PPTX/PDF 出力から日本語 `全` を排除し英語に正規化、Cover をチーム提出用デザインに刷新、ファイル名を ASCII 化。
  他ページ（Data Quality / Phase Summary / Lap by lap / Run Detail / Compare / PDF 出力）は維持。

## 1. Tatsuki feedback（実機テスト）
Workbench の `Create Report v2` で生成した `suspension_report_v2_ARAGON_全_RACE2_20260702_153934.pptx` を確認:
1. 1枚目に日本語 `全` が混入（`ARAGON | 全 / RACE2`）。
2. 1枚目のデザインが簡素すぎる（白地 + title + meta のみ）。
3. チーム提出資料として綺麗な Cover にしたい。

## 2. 原因
- Workbench `PhaseRunCompareWidget` の Circuit/Rider/Session コンボは「全」を all の sentinel に使う（`ts24_workbench.py` L3318/3332/3351）。
- ボタンの `scope` がその **`全` を verbatim** で `suspension_report.build_report_v2` に渡し、cover title と**ファイル名**に流入していた。

## 3. 修正（`suspension_report.py` のみ・Workbench UI の日本語ラベルは維持）

### 3a. scope 英語正規化
- `ALL_SENTINELS`（`全`/`全て`/`全サーキット`/…/空/None）+ `_resolve_scope(scope, df)` を新設。
  - all の場合 → 英語 `All riders` / `All circuits` / `All sessions`。データが1値なら実値、2-3値なら `All riders (DA77, JA52)` と列挙。
  - 例: rider=`全`（ARAGON RACE2）→ 表示 `All riders (DA77, JA52)` / トークン `ALL`。
- **PPTX/PDF 出力は英語のみ。** UI（Workbench）の日本語ラベルは従来通り。

### 3b. Cover をチーム提出用に刷新（`chart_cover()`・matplotlib 画像1枚を PPTX/PDF 共用）
- 左 navy アクセントバー + 上部アクセント。
- **Title** `TS24 Suspension Performance Report` / **Subtitle** `<Circuit> · <Rider scope> · <Session>`。
- **KPI カード ×4**（角丸・淡色）: Runs / Laps / Best lap（`M:SS,CC`）/ Median lap。
- **Scope カード**: Circuit / Session / Rider / Generated（`YYYY-MM-DD HH:MM` 人間可読）。
- **Phase colours legend**: Braking(red) / Apex(blue) / Exit(green) + 説明。
- 過度な装飾なし・余白確保・1枚で「何の資料か / どの session か / 主要数値」が分かる。
- PPTX は cover 画像を全面配置（`_add_cover_slide`）、PDF も同 cover 画像を先頭ページに使用（両者一致）。

### 3c. ファイル名 ASCII 化
- `_ascii_token()`（英数 + `_ -`・CJK 除去・大文字）。
- `全` → `ALL`。例: `suspension_report_v2_ARAGON_ALL_RACE2_<ts>.pptx`。`TEST1_DAY1` は `_` 保持で維持。

## 4. 検証
- `python3 -m py_compile suspension_report.py ts24_workbench.py` → PASS。
- 再生成（指摘条件）: **`suspension_report_v2_ARAGON_ALL_RACE2_20260702_polish.pptx` / `.pdf`**（All riders (DA77, JA52) / RACE2）。
- **CJK チェック（全スライド）**: ARAGON polish=14スライド **CJK 0** / JEREZ sample=18スライド **CJK 0**。cover はスライド1=画像（native text 0）。
- **Cover 目視（Read）**: title/subtitle 英語・KPI 4カード・Scope カード・Phase legend が読める・`全` 無し・空白主体でない。
- 単一 rider（JEREZ/DA77）は cover の Rider が `DA77` と表示（All にならない）ことを確認。
- offscreen smoke: MainWindow 7タブ・`📄 Create Report v2` ボタン・`chart_cover`/`_resolve_scope` callable → PASS。
- 既存ページ（Data Quality / Phase Summary / Lap by lap / Run Detail / Compare / PDF 出力）無回帰。

## 5. 成果物 / スコープ外
- 変更: `suspension_report.py`（`_resolve_scope`/`chart_cover`/`_add_cover_slide`/`_ascii_token`/`_save` tight 引数・build_report_v2/pdf の cover 差替・ASCII filename）。
- 新サンプル: `reports/pptx/suspension_report_v2_ARAGON_ALL_RACE2_20260702_polish.pptx`(+pdf) /
  `..._JEREZ_DA77_TEST1_DAY1_20260702_sample.pptx`(+pdf)（新 cover で再生成・Obsidian リンク維持）。
- **旧 `..._ARAGON_全_RACE2_20260702_153934.pptx/pdf`（Tatsuki テスト出力）は superseded**（削除はしていない）。
- 未実施（別承認）: 正本DB write / Supabase / DB Master 再生成 / origin push（`suspension_report.py`/`ts24_workbench.py`/`requirements_workbench.txt`/`build_excel_master.py` 未コミット）/ 新2D / remote_extra 24 cleanup。

## 6. Multi-agent operating check
- Report/PPT: cover 構成 + PPTX/PDF 再生成。Localization: `全`→英語正規化・CJK 0 チェック。Visual QA: cover 目視（KPI/scope/legend）。
- Workbench/UI: ボタン無回帰・UI 日本語維持。Quality Gate: py_compile / CJK / offscreen / render。Supervisor: DB write/Supabase/DB Master/push/新2D を別承認に保持。
