Every claim in the items is verified against the live codebase and DB. I have what I need. Confirming the build_excel loop at lines 224-226 marks all 3 sheets preserved (but RUN_LOG=DB_LOG is actually regenerated at line 121). Now I'll synthesize the roadmap.

---

# TS24 Part B 実装ロードマップ
## 残9シート正データ反映 / 生データ抽出システム / 全DB結合 / Workbench反映

**作成: 2026-06-19 / リードエンジニア / 正本DB: `02_DATABASE/ts24_unified.db`（検証済み, 3.6MB）**

> 注: items の主要数値・コード状態はライブDB/スクリプトと**全件一致を確認済み**（comment 80/275, problem_log 4, run_tags 61, setup_decision_log 7, lap_suspension 1202, pdf_lap_times 7613, race_results 792 / dashboard は `services/` `domain/` `components/` フォルダ不在で import 不可 / build_excel_master L224-226 が3シートを「保持/未再生成」とマーク / Workbench L1698-1971 で6メソッド未実装）。

---

## (1) 現状サマリ — 何が正 / stale / broken / missing

### ✅ 正（権威・継続使用可）
- **`ts24_unified.db` 新スキーマ本体** — 充填率良好、16テーブル健全。全DB結合の唯一の正本。
- **MES/2D 抽出のコア** — `extract_outing()` の3エリア完全性、`_lap_timebase()`（400/1000 自動検出, split-lap 修正済）、`gated_outings()`（copia/loose の HED矛盾ゲート, 2026-06-18 退行回避）。
- **PDF 取込のコア** — `pdf_result_extractor_v2` 複数ページ連結、`apply_pdf_positions_v2` の自然キーUPSERT幂等性。
- **Workbench 読取系** — `get_runs/get_run/get_laps`、PostureAnalysis（wf_*列自動取込）、Setup/ProblemLog/QuickLog UI（DB駆動）。
- **DB_LOG (=RUN_LOG)** — build_excel_master L121 で runs から実際に再生成済み（items の「保持」表記は誤り、コード上は再生成されている）。

### ⚠️ stale（値はあるが古い／フローが二重化）
- **WheelForce_Proxy** — SQLite には正値、JSON は null。`lap_suspension_stats.py` 最終実行が未来日付(2026-05-29)で以降のWF再計算が未走。FIELDS/HEADERS の重複定義(L598/607)残存。
- **TREND_ANALYSIS シート** — 旧238runs/178comments のまま。現DBは80comments。
- **旧DB乖離** — `ts24_master.db`(1.9MB) / `ts24_setup.db`(0byte) 残存。スクリプト群が複数DB参照、更新フロー二重化。
- **dynamics/corner_phase/lap_overlay JSON** — 旧APEX定義(2026-04-30前)・progressベース等の旧データ残存疑い。

### 🔴 broken（実行不可・データ誤り）
- **`dashboard.py`** — import 時点で失敗。`services/`/`domain/`/`components/` フォルダ不在（確認済）。`find_db()` が 0byte `ts24_setup.db` を探索。**ローカル実行不可**。
- **Workbench TrendAnalysisTab** — `get_trend_laps/runs/problems/lap_suspension/all_rounds/runs_detail` 等 **6メソッド未実装**でタブ動作不能。
- **comment_extraction** — `parse_report()` row48 列マッピング誤り（session label列とrun_no列の混同）、run_no キーイング(`i+1`)が Original 実番号と不整合。
- **TREND_ANALYSIS / SOLUTION_SEARCH 再生成** — build_excel_master L224-226 が両シートをスキップ（設計意図「DB由来・正 再生成」と乖離）。
- **problem_log スパース** — 4行のみ（設計100+）。TREND/SOLUTION の集計を全面ブロック。

### ❓ missing（未実装）
- **CORNER_EXIT エリア** — `parse_2d_channels.py` に検出関数なし／`lap_suspension` に ce_* 列なし／DYNAMICS_ANALYSIS Excel出力なし。
- **excel_parser のコメント抽出** — 新レポート取込時のコメント自動同期なし。
- **solution_case_index** — tag/PH→過去run→setup/結果 のデータ駆動索引なし。
- **comment→problem_log ブリッジ** — コメント知見が構造化DBへ移行されない。

---

## (2) フェーズ分け実装計画（依存順・各フェーズの成果物）

```
Phase 0 (基盤整地) ──┬─→ Phase 1 (コメント正データ復元) ──→ Phase 3 (preserved 3シート再生成)
                     ├─→ Phase 2 (生データ抽出: CORNER_EXIT) ──┘（lap_suspension拡張で合流）
                     └─→ Phase 4 (Workbench/Dashboard 表示層)  ←依存: Phase1/2の正データ
                                                              ↓
                                                    Phase 5 (索引・Supabase結合・恒久化)
```

### Phase 0 — 基盤整地（DB単一化・JSON再生成）
*依存: なし。最初に必ず実施。*
- `find_db()` を `ts24_unified.db` 直指定に修正（`ts24_setup.db` 探索撤去）。
- 旧DB（`ts24_master.db`, `ts24_setup.db`, `ts24_unified.old.db`）を `_old_backup/` へ退避・正式 deprecate。
- `lap_suspension_stats.py` の FIELDS/HEADERS 重複定義(L607)削除 → 再実行で WF/JSON 再生成。
- **成果物**: 全スクリプトが単一DB参照／WF値が入った `lap_suspension_data.json`／旧DB退避完了。

### Phase 1 — コメント正データ復元（80→170+）
*依存: Phase 0。preserved シート再生成の前提。*
- `parse_report()` row48 列マッピング修正（session label列のみ抽出）。
- run_no キーイングを Original 実番号ベースへ変更。
- `comment_extractor.py` スタンドアロン作成（01_REPORTS/** 全走査、±1 run_no 許容マッチ、reconcile ログ）。
- `excel_parser.parse_report_excel()` にコメント抽出追加（新レポート自動同期）。
- 旧TREND_ANALYSIS 178件との突合レポート（missing/orphaned 診断）。
- **成果物**: runs.comment 170-180件復元／reconciliation レポート／新規取込で自動同期。

### Phase 2 — 生データ抽出システム拡張（CORNER_EXIT）
*依存: Phase 0。Phase 1 と並行可。*
- `parse_2d_channels.py` に `detect_corner_exit_area()` + analyze_mes 出力4項目追加。
- `build_master_db.py` SCHEMA に ce_* 列、`_build_lap_suspension()` で ce 射影 + WheelForce計算。
- DYNAMICS_ANALYSIS Excel HEADERS に Corner Exit グループ追加。
- lap_metrics の CORNER_EXIT n=0 比率統計ログ（条件再検討の根拠）。
- **成果物**: CORNER_EXIT が MES→DB→Excel→JSON まで end-to-end 反映。

### Phase 3 — preserved 9シート正データ再生成
*依存: Phase 1（comment）+ problem_log 充填。*
- build_excel_master L224-226 撤去 → `build_trend_analysis_sheet()` + `build_solution_search_sheet()` 実装。
- `comment_to_problem_log()` で problem_log を 100+ へ充填（PH/コーナー/tag キーワード分類）。
- TREND_ANALYSIS 5セクション（circuit summary / top tags / rider trends / circuit×problem / comment log）。
- SOLUTION_SEARCH をデータ駆動 case index（40-50行）へ変換。
- **成果物**: 9シート全てDB由来で再生成された `TS24 DB Master.xlsx`。

### Phase 4 — Workbench / Dashboard 表示層
*依存: Phase 0（DB単一化）+ Phase 1/2 の正データ。*
- WorkbenchDB に未実装6メソッド実装（get_trend_laps/runs/problems/lap_suspension/all_rounds/runs_detail、列名 perf_best_lap↔best_lap_s マッピング解決）。
- dashboard.py の import を inline実装 or `services/data_loader.py` 新規作成で復旧。
- get_perf_correlation / get_trend_notes（large）は後続。
- **成果物**: Workbench TrendAnalysisTab 動作／dashboard ローカル実行可。

### Phase 5 — 全DB結合・索引・恒久化
*依存: Phase 1-4。*
- `solution_case_index`（tag/PH→run→setup→Δlap）materialize。
- pdf_lap_times ↔ lap_suspension の date込み JOIN 検証（dual-source 優先度フラグ）。
- sync_to_supabase v3 本実行（UNIQUE制約/conflict_col 確認、行数照合）。
- CLAUDE.md Section 17（preserved_sheets 再生成戦略 + runbook）追記。
- **成果物**: 全テーブル結合索引／Supabase同期完了／恒久ドキュメント。

---

## (3) P1（緊急）項目の具体アクション一覧

| # | ドメイン | コンポーネント | アクション | eff | Phase |
|---|---|---|---|---|---|
| 1 | comment | parse_report row48 マッピング | session label列のみで row48 抽出（c/c+1ペア廃止） | small | 1 |
| 2 | comment | run_no キーイング | `i+1` → Original 実 run_no 採用 | medium | 1 |
| 3 | comment | excel_parser コメント抽出 | `parse_report_excel()` に row48抽出 + report_importer 連携 | medium | 1 |
| 4 | comment | TREND vs RUN_LOG 突合 | reconciliation スクリプト（98件gap の bug/legit 分類） | medium | 1 |
| 5 | preserved | comment_extractor.py | 01_REPORTS全走査→±1許容マッチ→UPDATE（170+復元目標） | medium | 1 |
| 6 | mes_2d | CORNER_EXIT 検出 | `detect_corner_exit_area()` 追加（apex類似5条件マスク） | medium | 2 |
| 7 | mes_2d | lap_suspension ce_*射影 | SCHEMA+`_build_lap_suspension()`+INSERT に ce_*/wf_* 追加 | medium | 2 |
| 8 | mes_2d | analyze_mes ce出力 | 戻りdict に corner_exit_count/speed/susF/susR 追加 | small | 2 |
| 9 | pdf | race_results session_position | circuit正規化キー10ケース検証 + date列でyear判別 | medium | 5 |
| 10 | db_int | WheelForce_Proxy | lap_suspension_stats 重複定義(L607)削除→再実行→JSON再生成 | small | 0 |
| 11 | db_int | dashboard.py import | services/data_loader 作成 or inline復帰、find_db修正 | large | 4 |
| 12 | db_int | JSON→Dashboard flow | stats 再実行 + WF null 解消 + cache flush | small | 0 |
| 13-19 | workbench | TrendAnalysisTab 6メソッド | get_trend_laps/runs/problems/lap_suspension/all_rounds/runs_detail 実装 | small-med | 4 |
| 20 | preserved | TREND_ANALYSIS 再生成 | `build_trend_analysis_sheet()` 5セクション実装 | large | 3 |
| 21 | preserved | SOLUTION_SEARCH 再生成 | static手順→データ駆動 case index 変換 | large | 3 |
| 22 | preserved | comment→problem_log | `comment_to_problem_log()` で 100+ 充填 | large | 3 |
| 23 | preserved | build_excel L224-226 | 保持ループ撤去→2関数呼出追加 | large | 3 |
| 24 | preserved | TREND grouping | circuit×session coverage pivot 実装 | medium | 3 |
| 25 | preserved | SOLUTION navigation | REFERENCE(1-8) + CASE DATA(9+) 2分割 + PH色分け | large | 3 |

---

## (4) Quick Wins（small effort・効果大）

1. **`find_db()` 修正**（Phase 0, small）— 0byte DB探索を撤去し unified直指定。dashboard/build系の全障害の根。一行修正で連鎖解消。
2. **lap_suspension_stats 重複定義削除 + 再実行**（#10/#12, small）— WF が SQLite→JSON→dashboard へ通る。既に正値はDBにあるので「流すだけ」。
3. **parse_report row48 マッピング修正**（#1, small）— 80件中の誤キー是正。Phase1の最大ボトルネックを最小工数で解消。
4. **analyze_mes に ce出力4項目追加**（#8, small）— 検出関数(#6)完成後の配線のみ。Excel/JSON 露出に直結。
5. **Workbench get_all_rounds 実装**（#18, small）— `SELECT DISTINCT round FROM runs`。TrendAnalysisTab 初期化(L1698)の即死を解消、他5メソッド実装の足場。
6. **旧DB退避**（Phase 0, small）— 二重参照リスクを物理的に除去。

---

## (5) リスク / 要確認点

- **comment 98件gap の正体未診断**: 復元目標170+ のうち、2D-only run（コメント源なしの正当ドロップ）と抽出bug の比率が不明。**Phase 1 の reconciliation(#4) を先行**し、目標値を実数で再設定すること。盲目的な170固定は危険。
- **run_no キーイング変更(#2) の回帰**: Original 実番号採用は既存80件のキーも変わりうる。変更前後で既存マッチが壊れないか差分テスト必須。
- **CORNER_EXIT n=0 多発リスク**: BRAKE_FRONT -0.5~0.0 ∩ THROTTLE 50-100% が全ラップで不検出の可能性。n=0比率50%超なら条件再設計（items でも明記）。実装前にサンプルMESで条件成立率を確認。
- **problem_log 自動充填の分類精度**: comment→PH/tag のキーワード分類は誤分類リスク。DA77/JA52 のFP/QPで精度検証してから一括投入。`problem_library.complaint_en` マッピング前提。
- **circuit 表記揺れ / 複数年(2025/2026)**: race_results の session_position 照合と pdf_lap_times JOIN の両方で year 衝突リスク。**date列の追加が共通の鍵**。`_normalize_circuit()` ユーティリティ共有化を先行。
- **build_excel 書式保持**: TREND/SOLUTION 再生成時、既存テンプレの font/fill/border をコピーしないと崩れる。`repopulate()` の書式継承を確認。
- **dashboard 設計図の所在**: CLAUDE.md にtp設計図記載との注記あり。コード実装前に仕様確認（items明記）。Streamlit Cloud用JSON とローカルSQLite の優先順位を確定。
- **Supabase 権限/制約**: service role key の insert/update 権限、UNIQUE制約・conflict_col 実装(`dedup_and_constraints_*.sql` 実行有無)を本実行前に dry-run 確認。

---

## 次に着手すべきフェーズ

# → Phase 0（基盤整地: DB単一化・JSON再生成）

**理由**: `find_db()` の 0byte DB探索と `services/` フォルダ不在が、dashboard 実行不可・WF null 表示・更新フロー二重化という複数の broken/stale を同時に引き起こす**共通根**。Quick Win 3件（#1除く #10/#12/find_db）が全てここに集中し、工数 small ながら Phase 3/4 の前提を一掃する。依存ゼロで即着手可能、かつ後続全フェーズの土台。Phase 0 完了直後に Phase 1（comment正データ）と Phase 2（CORNER_EXIT）を並行起動するのが最短経路。