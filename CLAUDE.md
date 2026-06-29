# CLAUDE.md — TS24 Project Team Shared Context
**Project:** TS24 SET-UP TOOL / Puccetti Racing WorldSSP Suspension Management System
**Last Updated:** 2026-06-20
**Read this file at the start of every session — Claude Code, Cowork Claude, and ChatGPT both.**

---

## ⚠️ 0. 最新の正（READ FIRST）— 旧記述スコープ宣言（2026-06-20）

**§2〜§17 は 2026-05 時点の旧アーキテクチャ記述。現行と矛盾する箇所は §18 / §19 / §20 が正。**
迷ったら §18-§20 を優先すること。特に以下は**旧情報**（本文内にも【旧情報】マーカーあり）:

| 項目 | 旧記述（§2-§17） | 現行の正 |
|---|---|---|
| 正本DB | `ts24_setup.db`（sessions/tags/...） | **`02_DATABASE/ts24_unified.db`**（§4.4更新済/§18/§20a）。run_id/lap_id規則は §20a |
| データフロー | MES→各種JSON→dashboard | **build_master_db.py → ts24_unified.db 駆動**（§18/§19）。Workbenchは完全DB駆動（§18c/§19c） |
| dashboard用JSON | lap_suspension_data/dynamics_data/lap_overlay_data/lap_times_data/corner_phase_data.json を「使用」 | **HEAD版を保持（削除commitしない / 2026-06-20 Tatsuki決定 §21）**。dashboard.py がまだ参照中のため、dashboard refocus / Supabase完全移行が別PRで完了するまで削除判断は先送り。`lap_suspension_data.json` は **stale/deprecated**(HEAD版=旧30列)、**WorkbenchはDB(46列)優先**(§19c)。DB由来46列JSON再生成フローは未実装 |
| race_memory.json | 「全AI共有文脈・必須・自動追記」 | **保持（削除しない / 2026-06-20 Tatsuki決定 §21）。将来DB化候補**：知見蓄積をDB(problem_log/setup_decision_log等)へ完全移行する設計が確定するまで現行ファイルを維持。dashboard.py(memory_service)が参照中 |
| 件数（844行/615行/17387行 等） | 旧スナップショット | 現行: runs275 / laps1202 / lap_suspension1202(46列) / race_results792（§18d/§20a） |

---

## 1. チームとその役割

このプロジェクトは4者チームで運営される。

| メンバー | 役割 | 主な責任 |
|---------|------|---------|
| **Tatsuki Suzuki（鈴木達樹）** | チームマネージャー / データ収集 | MESデータ収集・現場フィードバック・最終意思決定・AI間のハブ |
| **Claude Cowork** | データ分析 / ソリューション提示 | ダッシュボード上でのリアルタイム分析・セットアップ提案・知見の蓄積 |
| **Claude Code** | システム管理 / ダッシュボード維持 | dashboard.py更新・データ処理・Git管理・スクリプト実行 |
| **ChatGPT** | プロジェクト監視 / 改善提案 | システム全体の俯瞰・問題発見・改善点の提示・第三者視点でのレビュー |

**重要:** 各AIは直接通信できない。Tatsukiがハブとなり情報を橋渡しする。
このファイル（CLAUDE.md）と `race_memory.json` が全AIの共有文脈として機能する。
作業前に必ずこのファイルを読むこと。

### 役割境界ルール（厳守）

| 行為 | Cowork Claude | Claude Code |
|-----|:---:|:---:|
| ダッシュボードで分析・提案 | ✅ | ❌ |
| race_memory.json に知見を追記 | ✅ | ✅ |
| CLAUDE.md の設計・仕様を更新 | ✅ | ✅ |
| dashboard.py / .py ファイルを実装 | ❌ | ✅ |
| git add/commit/push | ❌ | ✅ |
| データ処理スクリプトを実行 | ❌ | ✅ |

**Cowork Claude はコードを直接書かない。** 設計・仕様・修正方針をCLAUDE.mdに記述し、Claude Codeに渡す。

### チーム通信フロー

```
ChatGPT
   ↕ (問題・改善提案を報告)
Tatsuki Suzuki ← → Claude Cowork（ダッシュボード上で分析対話）
   ↕ (実装指示)
Claude Code（コード修正・Git管理）
```

### 各AIの参照ファイル

| AI | 主な参照 | 参照方法 |
|---|---------|---------|
| Claude Cowork | race_memory.json・ダッシュボードデータ | フローティングチャット |
| Claude Code | CLAUDE.md・dashboard.py・全ファイル | ローカルファイルシステム |
| ChatGPT | CLAUDE.md・Tatsukiが共有するスクリーンショット・コード断片 | Tatsuki経由で共有 |

---

## 1b. 原本照合ルール（確定 2026-06-05・Tatsuki承認済み）

`04_REFERENCE/Data_Base_TS24_ORIGINAL.xlsx` を権威源として DB（`TS24 DB Master.xlsx / RUN_LOG`）と
照合する際の補正可否ルール。**原本は常に読み取り専用**だが、「原本が勝つ」を機械的に適用すると
かえって情報が劣化するケースがあるため、以下を確定ルールとする。

照合キー = `(RIDER, CIRCUIT_norm, SESSION.strip().upper(), RUN)`。サーキット名は別表で正規化。

### 補正の判定（フィールド単位）

| ケース | 原本 | DB | 補正するか | 理由 |
|---|---|---|---|---|
| 原本に値があり DB と矛盾 | 値あり | 値あり（異なる） | ✅ 原本で上書き | 原本が真実 |
| **原本が空** | 空 / None | 値あり | ❌ DB を残す | 原本未記入＝原本の欠落。DB の実測値を消さない |
| **DB の方が詳細（粒度差）** | 粗い（例 `SC1`） | 詳細（例 `SC1 NEW`） | ❌ DB を残す | DB の付加情報（NEW/USED 等）は価値あり、劣化させない |
| 原本にあるが DB に無いキー | 行あり | 行なし | ✅ DB に追加 | 原本のカバー範囲内で DB が取りこぼし |
| DB にあるが原本に無いキー | 行なし | 行あり | ❌ 触らない | 原本のカバー範囲外（ROUND3+ 等の未バックフィル） |

### 要点（一言で）

> **「原本が勝つ」は "原本に明示的な値があるとき" のみ。原本の空欄・DB の付加情報は DB を残す。**

このルールにより、2026-06-05 の初回照合で検出された 24 件のフィールド不一致
（TYRE_FRONT/REAR の NEW/USED 表記差 18 件 + 原本空欄の AIR/TRACK_TEMP 6 件）は
**すべて補正対象外**と判定された。詳細は `05_SCRIPTS/reports/reconcile_original_vs_db_20260605.md`。

---

## 1c. Supabase sync の conflict キー（確定 2026-06-05）

`sync_to_supabase.py` は **自然キー（business key）で upsert する**。旧実装は
`conflict_col="id"` だったが SELECT に id を含めず on_conflict が無効化され、
再 sync のたびに全行 INSERT → オンラインが local の 5〜13 倍に肥大した。

| テーブル | conflict_col（= Supabase 側 UNIQUE INDEX） |
|---|---|
| race_results | round_no, circuit, session_type, rider_no, position |
| lap_times | round_id, circuit, session_type, rider_num, lap_no |
| sessions_2d | round, circuit, session_type, rider, run_no, **date** |
| lap_times_2d | round, circuit, session_type, rider, run_no, lap_no, **date** |

対応 UNIQUE INDEX は `reports/supabase_dedup_and_constraints_*.sql` で作成（`NULLS NOT DISTINCT`）。
**新テーブルを sync 対象に追加する場合は必ず自然キー + UNIQUE 制約をセットで用意すること。**
`id`（autoincrement）は再ビルドごとに振り直されるため conflict キーに使ってはいけない。

### 更新（DB再構築 2026-06-18）

- **`sessions` / `chassis_geometry` は sync 対象から除外**。再構築で源テーブル
  (`ts24_sessions` / `chassis_geometry`) が廃止されたため。sync_to_supabase.py v3
  は `race_results / lap_times / sessions_2d / lap_times_2d` の4本のみ。
- **`sessions_2d` / `lap_times_2d` の conflict_col に `date` を追加**。新 run_id が
  日付付き ({date}_{round}_...) になり、同一 round 番号がシーズンを跨いで再利用
  される（例: ROUND1 PHILLIP ISLAND が 2025/2026 両方に存在）。date 無しでは
  natural key 衝突で sync が 21000 エラー。対応 SQL =
  `reports/supabase_dedup_and_constraints_20260618.sql`（Supabase で先に実行 → 再 sync）。

---

## 2. プロジェクト概要

- **チーム:** Puccetti Racing（プチェッティ・レーシング）
- **バイク:** Kawasaki ZX-636（WorldSSP）
- **ライダー:** DA77（ダ77）・JA52（ジャ52）
- **シーズン:** TS24（2025-10 ～ 2026 継続中）
- **ダッシュボード:** https://ts24-dashboad-3gf7gbyieajua9ygq9f8rr.streamlit.app
- **GitHubリポジトリ:** https://github.com/TS24-Settool/ts24-dashboad

---

## 3. フォルダ構造

```
~/Desktop/Data TS24 Claude/          ← iCloud同期済み
├── 01_REPORTS/
│   ├── DA77/                        ← DA77イベントレポート (.xlsx)
│   └── JA52/                        ← JA52イベントレポート (.xlsx)
├── 02_DATABASE/
│   ├── TS24 DB Master.xlsx          ← メインDB（Excel）
│   ├── ts24_setup.db                ← 【旧情報】0B廃止。正本=ts24_unified.db（§4.4/§20a）
│   └── all_sessions.json            ← 【旧情報】旧キャッシュ。現行はDB駆動（§18）
├── 03_TEMPLATES/                    ← イベントレポートテンプレート
├── 04_REFERENCE/
│   ├── TS24_Knowledge_Base.md       ← サスペンション理論・ZX-636知識（必読）
│   ├── TS24_System_Architecture.md ← システム設計書
│   ├── 2D_Software_Knowledge.md    ← 【NEW】2D Analyzer/CalcTool/GPSTracks 知識ベース（2026-05-05作成）
│   └── 2D_Software/                ← 2D社PDFマニュアル原本
│       ├── AC-DOC_Analyzer_e-000.pdf
│       ├── AC-DOC_CalcTool.pdf
│       └── AC-DOC_2D_GPSTracks.pdf
├── 05_SCRIPTS/                      ← Claude Codeが主管するディレクトリ
│   ├── CLAUDE.md                    ← このファイル（必読）
│   ├── dashboard.py                 ← Streamlitダッシュボード（本体）
│   ├── parse_2d_channels.py         ← MESデータ解析（APEX検出アルゴリズム）
│   ├── lap_suspension_stats.py      ← ラップサスペンション統計生成（WF_F/R列含む）
│   ├── lap_suspension_data.json     ← 615行・38列（WF_F_APEX_N等4列追加済）
│   ├── dynamics_data.json           ← DYNAMICS_ANALYSIS（Streamlit Cloud用）
│   ├── lap_times_data.json          ← ラップタイムデータ
│   ├── race_memory.json             ← 【重要】AI分析知見の蓄積ファイル
│   ├── git_push_fix.command         ← GitHubプッシュスクリプト（手動実行）
│   ├── run_full_analysis.command    ← 全データ再処理スクリプト
│   ├── ts24_workbench.py            ← 【NEW】PyQt6 Engineer Workbench（ローカルデスクトップアプリ）
│   ├── create_workbench_tables.py   ← 【NEW】problem_log / setup_decision_log テーブル作成スクリプト
│   └── requirements_workbench.txt  ← 【NEW】Workbench依存パッケージ（PyQt6, pyqtgraph, pandas）
├── 04_MES/                          ← MES生データ（2Dロガー出力）
│   └── [RIDER]/[DATE]/              ← ライダー別・日付別
└── 06_CSV/                          ← 【NEW】2D CSV Export専用（Workbench用）
    └── [CIRCUIT]/[SESSION]/         ← 例: ASSEN/FP/JA52_R1.csv
```

---

## 4. 技術アーキテクチャ

### 4.1 データフロー

```
MES生データ（.MES）
    ↓ parse_2d_channels.py
    ↓ lap_suspension_stats.py
lap_suspension_data.json  →  dashboard.py（Streamlit Cloud）
dynamics_data.json        →
lap_times_data.json       →
    ↑
ts24_setup.db（SQLite）   →  sessions / tags / race_results テーブル
```

### 4.2 主要JSONファイル（Streamlit Cloud用）

> **【旧情報 / stale・deprecated】** 以下のJSON群（lap_suspension_data / corner_phase_data / lap_overlay_data /
> dynamics_data / lap_times_data）は **HEAD版を保持**（削除commitしない / 2026-06-20 Tatsuki決定 §21）。
> dashboard.py がまだ参照中のため、dashboard refocus / Supabase完全移行が別PRで完了するまで削除は先送り。
> 件数(844/615/17387等)は旧スナップショット。現行のデータ正は `ts24_unified.db`（§18/§19）。
> `lap_suspension_data.json` は **stale/deprecated**（HEAD版=旧30列）、**WorkbenchはDB(46列)優先**（§19c）。
> DB由来46列JSON再生成フローは未実装（将来 §18d Cloud再生成の残課題）。

| ファイル | レコード数 | 主要列 | 更新タイミング |
|---------|-----------|--------|---------------|
| `lap_suspension_data.json` | 844行・30列 | APEX_CNT, APEX_SPD_AVG, APEX_SUSF_AVG, APEX_SUSR_AVG, **WF_F_APEX_N, WF_R_APEX_N**, BRK_CNT, BRK_SUSF_AVG, BRK_SUSR_AVG, **WF_F_BRK_N, WF_R_BRK_N**, FULLBRK_CNT, FULLBRK_SUSF, FULLBRK_SUSR, LAP_SUSF_MEAN, LAP_SUSF_MIN, LAP_SUSF_MAX, LAP_SUSR_MEAN | MES再処理時 |
| `corner_phase_data.json` | 17387行 | round, circuit, date, session_type, rider, run_no, lap_no, lap_time_s, corner_no, ph12_duration_ms, ph12_brake_peak_bar, ph12_susf_avg, ph3_duration_ms, ph3_speed_min, ph3_susf_avg, ph3_susr_avg, ph45_duration_ms, ph45_gas_avg, ph45_susf_avg, total_corner_ms | corner_phase_analysis.py 実行時 |
| `lap_overlay_data.json` | 844ラップ | circuit, rider, session_type, run_no, lap_no, lap_time_s, n_points(200), **lap_distance_m(null/将来GPS)**, **distance_progress(null/将来GPS)**, channels{lap_progress, speed, brake, gas, sus_f, sus_r} | lap_overlay_extractor.py 実行時 |
| `dynamics_data.json` | ラップ単位 | ACC_Y_PEAK, BOFF_SUSF, THRON_SUSF | MES再処理時 |
| `lap_times_data.json` | セッション単位 | best_lap, rider, circuit, date, run_no | セッション登録時 |

### 4.3 lap_overlay_data.json スキーマ（Future GPSフック含む）

```json
{
  "circuit": "ASSEN", "rider": "DA77", "session_type": "RACE1",
  "run_no": 1, "lap_no": 5, "lap_time_s": 97.901, "n_points": 200,
  "lap_distance_m": null,      // GPS実装後に有効化
  "distance_progress": null,   // GPS実装後に有効化
  "channels": {
    "lap_progress": [0.0, ..., 1.0],  // 200点 時間正規化（現在のみ）
    "speed": [...], "brake": [...], "gas": [...], "sus_f": [...], "sus_r": [...]
  }
}
```

`lap_comparison_latest.json` は Streamlitが書き込む一時ファイル（.gitignore済み）。

### 4.4 データベース（SQLite）

**ファイル:** `02_DATABASE/ts24_unified.db`（Streamlit/ローカル共用）

```sql
-- 既存テーブル（Streamlit読み取り）
sessions        -- セッション基本情報
tags            -- 問題タグ（chattering_brake等）
race_results    -- 公式レース結果
laps            -- ラップタイム
runs            -- ランデータ（session列 / perf_best_lap列 を使用）
events          -- イベント情報
lap_suspension  -- ラップサスペンション統計

-- Workbench専用テーブル（2026-05-03 追加、create_workbench_tables.py で作成）
problem_log     -- エンジニアが記録する問題ログ
setup_decision_log  -- セットアップ変更の意思決定ログ
```

**重要な列名（runs テーブル）:**
- `session` ← `session_type` ではない
- `perf_best_lap` ← `best_lap_s` ではない

**problem_log スキーマ:**
```sql
problem_id TEXT PRIMARY KEY, run_id TEXT, round TEXT, circuit TEXT, session TEXT,
rider TEXT, run_no INTEGER, lap_no INTEGER, corner TEXT, phase TEXT,
problem_tag TEXT, description TEXT, severity TEXT, source TEXT,
created_at TEXT, updated_at TEXT,
-- Phase 2拡張列（Workbench範囲選択→自動入力）
distance_start_m REAL,      -- 問題区間の開始距離 (m)
distance_end_m REAL,        -- 問題区間の終了距離 (m)
time_start_s REAL,          -- 問題区間の開始時間 (s)
time_end_s REAL,            -- 問題区間の終了時間 (s)
data_source_file TEXT,      -- 元CSVファイル名
analysis_note TEXT          -- 分析メモ（フリーテキスト）
```

**Phase 2 DB拡張 — ALTER TABLE 手順:**
```sql
ALTER TABLE problem_log ADD COLUMN distance_start_m REAL;
ALTER TABLE problem_log ADD COLUMN distance_end_m REAL;
ALTER TABLE problem_log ADD COLUMN time_start_s REAL;
ALTER TABLE problem_log ADD COLUMN time_end_s REAL;
ALTER TABLE problem_log ADD COLUMN data_source_file TEXT;
ALTER TABLE problem_log ADD COLUMN analysis_note TEXT;
```

**setup_decision_log スキーマ:**
```sql
decision_id TEXT PRIMARY KEY, run_id_from TEXT, run_id_to TEXT, round TEXT,
circuit TEXT, session TEXT, rider TEXT, change_type TEXT, component TEXT,
from_value TEXT, to_value TEXT, rationale TEXT, expected_effect TEXT,
actual_effect TEXT, result_eval TEXT, created_at TEXT, updated_at TEXT
```

### 4.4 Streamlit Cloud設定

- **デプロイ:** GitHub mainブランチへのpushで自動デプロイ（約1〜2分）
- **Secrets:** Anthropic APIキー・Supabase URLはst.secretsで管理
- **データ読込:** JSONファイルをキャッシュ（`@st.cache_data(ttl=120)`）

---

## 5. APEX定義システム（最重要）

**現在の方針 (2026-04-30 チーム確定、dTPS_A緩和 2026-04-30 チーム承認):**
APEX Area = BRAKE_FRONT -0.6~0.3Bar ∩ GAS 0~6% ∩ dTPS_A -10~100 ∩ SUSP_F 20~140mm ∩ SUSP_R 5~50mm
5条件が同時成立する区間の平均をAPEX値とする。旧ACC_Y/BRAKE_OFF/THR_ON定義は廃止。

| チャンネル | 条件 | サンプルレート比 |
|-----------|------|----------------|
| BRAKE_FRONT | -0.6 〜 0.3 Bar | 1x（基準） |
| GAS | 0.0 〜 6.0 % | 2x |
| dTPS_A | -10.0 〜 100.0 （実質非制約） | 2x |
| SUSP_FRONT | 20.0 〜 140.0 mm | 4x |
| SUSP_REAR | 5.0 〜 50.0 mm | 4x |

**フォールバック:** dTPS_Aチャンネルが存在しない古いMESファイルは旧THR_ON定義で検出。

### APEX検出アルゴリズム（parse_2d_channels.py）

```python
# detect_apex_area(): 5条件マスクを生成 → 連続区間を抽出 → マージ → 代表値計算
# ラップ区間をbrake_fレートでスライス → GAS/dTPS_Aは2x → SUSP_F/Rは4xにマップ
# dTPS_A未搭載ファイル: has_dtps=False → 旧THR_ON方式にフォールバック
```

### 出力列（後方互換）
- `APEX_SUSF_AVG` / `THRON_SUSF_AVG` → 新APEX定義の値（同値）
- `BOFF_SUSF_AVG` → None（廃止、列のみ保持）

---

## 6. PyQt6 Engineer Workbench（ts24_workbench.py）

**目的:** Deep Analysis専用ツール。2D CSVを読み込み、問題箇所をDBに直接記録し、次Roundの判断に使える知見を蓄積する。
**Workbench = "Deep Analysis記録ツール"（2026-05-03 方針確定）**
**Streamlit Dashboard とは独立した別アプリ。Streamlit Cloudに影響しない。**

### ワークフロー（確定）

```
2D Analyzer（正式分析・詳細確認）
    ↓  CSVをWorkbenchに読み込み
Workbench（Distance軸で問題箇所を確認）
    ↓  問題・仮説・判断をDBに直接記録
Problem Log / Setup Decision Log（SQLite）
    ↓  知見として蓄積・再利用
次Round判断への入力
```

### 役割分担（確定）

| ツール | 役割 |
|--------|------|
| 2D Analyzer | 正式な波形分析・詳細確認 |
| **Workbench** | **Deep Analysis整理・問題定義・DB記録** |
| Excel / SQLite DB | 正式な記録・知見蓄積 |
| Streamlit | 軽い確認・共有・AI Chat入口 |

### 設計原則（確定）

| 原則 | 内容 |
|------|------|
| **目的** | グラフを見るツールではなく、Deep Analysisの知見をDBに保存するツール |
| **X軸優先順位** | **Distance（m）> Time（秒）> Progress（fallback）** |
| **データソース** | **2D CSVを直接読む**（lap_overlay_data.jsonは使用しない） |
| **Dist仕様** | 累積値（セッション通算・リセットなし）→ Lap内で `dist - dist[lap_start]` で0始まりに変換 |
| **禁止** | Workbenchでセットアップ提案を自動確定しない。2D Analyzerの完全再現を目指さない |

### 禁止事項
- `lap_overlay_data.json` をWorkbenchのデータソースとして使用すること
- time-normalized overlay（0-1正規化）を正確な分析として扱うこと
- 不正確なTurn同期（lap_progressベース）を前提にした分析

### ✅ 確定チャンネル構成（2026-05-03 Tatsuki確定）

**設計思想: 「問題を定義できること」が目的。データ量≠精度。**

| 優先度 | チャンネル名 | 単位 | 役割 | 状態 |
|--------|------------|------|------|------|
| **必須** | Time | s | X軸基準 | ✅ |
| **必須** | SPEED（またはSPEED_FRONT） | km/h | Entry/Apex/Exit判断の全基準 | ✅ |
| **必須** | BRAKE_FRONT | Bar | PH1/PH2判断・リリース問題検出 | ✅ |
| **必須** | GAS | % | PH4/PH5・立ち上がり問題 | ✅ |
| **必須** | SUSP_FRONT | mm | コア領域・問題定義の根幹 | ✅ |
| **必須** | SUSP_REAR | mm | コア領域・問題定義の根幹 | ✅ |
| 推奨 | LEAN_ANGLE | deg | 「曲がらない」の正体を見抜く | あれば追加 |
| **Distance軸** | Dist | m | X軸（Distance mode時）累積値→Lap内リセット | ✅ 有効確認 |
| 後回し | GEAR / RPM | - | ライダー操作vs車体挙動切り分け | 将来 |
| **不使用** | BRAKE_REAR / 細かいダンパー速度 | - | 現段階ではノイズ | ❌ |

**Dist列の仕様（2026-05-03 X_F1-#77-03_DISTANCE.csv で確認）:**
```
- 累積値：セッション開始からの積算距離（例: 4356m → 49905m）
- Lap境界ではリセットしない → Lap分割後、dist - dist[lap_start] で0始まり変換
- Dist有効判定: dist.max() > 10m
- X軸表示単位: m（Distance mode）
```

**分析ロジック（このチャンネルで成立する）:**
```
どこで遅いか → SPEED
なぜ遅いか   → BRAKE_FRONT / GAS
車体状態     → SUSP_FRONT / SUSP_REAR
```

### 2D CSV フォーマット仕様

```
区切り文字: セミコロン (;)
小数点: カンマ (,) ← Europeanフォーマット
行1: ヘッダー（チャンネル名）
行2: 単位
行3以降: データ
サンプルレート: 400 Hz（0.0025秒間隔）

確定エクスポートチャンネル（Tatsukiが2Dからこの設定でExport）:
  Time[s], Dist[m], SPEED[km/h], BRAKE_FRONT[Bar], GAS[%], SUSP_FRONT[mm], SUSP_REAR[mm]
  + LEAN_ANGLE[deg] （あれば）
  + MAP[mBar], V_GPS[km/h] （CSVによる）
```

### CSVファイル保存場所（運用ルール）

```
~/Desktop/Data TS24 Claude/
└── 06_CSV/                    ← 2D CSV Export専用フォルダ（新設）
    ├── ASSEN/
    │   ├── FP/
    │   │   ├── JA52_R1.csv
    │   │   ├── JA52_R2.csv
    │   │   └── DA77_R1.csv
    │   └── QP/
    └── CREMONA/
        └── ...
```

**命名規則（提案）:** `{RIDER}_R{run_no}.csv`
現在の2DのExport名と異なる場合はTatsukiが都度確認する。

### CSVパース要件（Claude Code実装）

```python
# 正しいパース方法
import pandas as pd

def load_2d_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=';', decimal=',', skiprows=[1])
    # skiprows=[1] で単位行をスキップ、ヘッダー行は自動取得
    # 列名例: Time, Dist, GAS, SUSP_REAR, SPEED_FRONT, BRAKE_REAR, BRAKE_FRONT
    return df

# Dist有効性チェック
def dist_is_valid(df: pd.DataFrame) -> bool:
    if 'Dist' not in df.columns:
        return False
    return df['Dist'].max() > 10  # 10m以上の変化があれば有効とみなす
```

### 表示チャンネル優先順位

| 優先度 | チャンネル | Y軸単位 | 表示色 |
|--------|-----------|---------|--------|
| 1位 | SPEED_FRONT | km/h | 青 |
| 2位 | BRAKE_FRONT | Bar | 赤 |
| 3位 | GAS | % | 緑 |
| 4位 | SUSP_REAR | mm | オレンジ |
| 5位（あれば）| SUSP_FRONT | mm | 紫 |

### ✅ 現行UI構成（Phase 3 完了 — 2026-05-05）

```
┌─ トップツールバー ──────────────────────────────────────┐
│  Circuit: [ASSEN▼]   📂 CSVを開く   Run: ─             │
└────────────────────────────────────────────────────────┘
┌─ タブエリア ─────────────────────────────────────────────────────────┐
│ [波形] [Problem Log] [Setup Decision]                                  │
│                                                                         │
│ ┌─ チャンネル選択 ──────────────────────────────────────────────────┐ │
│ │ ☑Speed  ☑Brake  ☑Gas  ☑SUSP_F  ☑SUSP_R  (チェックで表示/非表示) │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                         │
│ ┌─ 波形 (左) ──────────────────────┐ ┌─ Problem Log 入力パネル(右)─┐ │
│ │ Speed (km/h) ─────────────────── │ │  Range: 48.0m → 958.8m      │ │
│ │ Brake (Bar)  ─────────────────── │ │  Corner: [T1▼]              │ │
│ │ Gas   (%)    ─────────────────── │ │  Phase:  [PH2▼]             │ │
│ │ SusF  (mm)   ─────────────────── │ │  Tag:    [chattering▼]      │ │
│ │ SusR  (mm)   ─────────────────── │ │  Severity: [Medium▼]        │ │
│ │  [███ LinearRegionItem ████]     │ │  [追加]                     │ │
│ └──────────────────────────────────┘ └─────────────────────────────┘ │
│                          [Problem Log へ送る]                           │
└─────────────────────────────────────────────────────────────────────────┘
```

**Phase 3 実装内容（2026-05-05 完了）:**
- 左サイドバー（DBランツリー）を廃止 → トップツールバーに移行
- `QSplitter(Horizontal)`: 波形(左) + Problem Log 入力パネル(右) の分割表示
- 個別 `PlotWidget` × 5（`GraphicsLayoutWidget` から置き換え） → 各チャンネル独立表示/非表示
- `QCheckBox.toggled` → `PlotWidget.setVisible()` でチャンネルオン/オフ
- `_ProblemRightPanel`: コンパクト入力フォーム（Corner/Phase/Tag/Desc/Severity/Source）
- CSV直ロード: ファイルダイアログ → `_load_csv()` → `_send()` の一連フロー確定

### CSVファイル命名パターン（現在把握済み）

```
X_R1-JA52-01.csv  → セッション種別不明_Run1-JA52-ラップor連番01
```
命名規則はTatsukiから都度確認すること。

### 現在の実装状態 (2026-05-05)

| 機能 | 状態 | 備考 |
|------|------|------|
| 2D CSV Import（CsvImportTab） | ✅ 完了 | 06_CSV/デフォルト・UTF-8/Shift-JIS自動検出・列マッピングUI |
| Time軸表示 | ✅ 完了 | `x_mode="time"` でX軸=経過秒数 |
| Progress軸フォールバック | ✅ 完了 | Timeカラム未マッピング時は 0-1 正規化 |
| **WaveformView 5パネル** | ✅ **完了** | 個別 `PlotWidget` × 5、Speed/Brake/Gas/SusF/SusR |
| 自動チャンネルマッピング | ✅ 完了 | GAS_SMOOTH→gas / SUSP_FRONT→susp_front 全て自動 |
| Problem Log DB保存（9列） | ✅ 完了 | INSERT/SELECT/DELETE 正常動作確認済み |
| Setup Decision Log DB保存 | ✅ 完了 | INSERT/SELECT/UPDATE 正常動作確認済み |
| **DB駆動Lap分割** | ✅ 完了 | commit 8bc5973・最大誤差0.02s |
| **LinearRegionItem 範囲選択** | ✅ **Phase 2完了** | 青ハイライト・ドラッグ可能・初期値[0,100] |
| **範囲 → Problem Log 自動入力** | ✅ **Phase 2完了** | dist_start/end, time_start/end 自動pre-fill |
| **"Problem Log へ送る" ボタン** | ✅ **Phase 2完了** | 波形下部ボタン → 右パネルを開いてRange表示 |
| **トップツールバー** | ✅ **Phase 3完了** | Circuit ComboBox + 📂 CSVを開く（左サイドバー廃止） |
| **QSplitter 分割ビュー** | ✅ **Phase 3完了** | 波形(左) + _ProblemRightPanel(右)・初期は右非表示 |
| **チャンネル選択チェックボックス** | ✅ **Phase 3完了** | Speed/Brake/Gas/SUSP_F/SUSP_R の表示/非表示 |
| **_ProblemRightPanel** | ✅ **Phase 3完了** | Corner/Phase/Tag/Desc/Severity/Source フォーム |
| **WheelForce_Proxy DB列** | ✅ **完了** | WF_F_APEX_N/WF_R_APEX_N/WF_F_BRK_N/WF_R_BRK_N（MR=0.5） |
| Distance軸表示 | 🔜 将来実装 | `x_mode="distance"` — Dist累積→Lap内0始まり変換 |
| PH1〜PH5自動フェーズ検出 | 🔜 最重要・将来 | 波形上にフェーズ境界オーバーレイ |

### Claude Code への実装指示（2026-05-03 確定）

**タスク1: 2D CSV Import 機能を追加**
- ツールバーまたは左パネルに「CSVを開く」ボタンを追加
- `QFileDialog.getOpenFileName()` でCSVを選択
- `load_2d_csv()` でパース（セミコロン区切り・カンマ小数点）
- Dist有効性をチェックし、無効なら「X軸: Time固定」を表示

**タスク2: Time軸でWaveform表示**
- X軸: `Time`列の値（秒）をそのまま使用
- Y軸: SPEED_FRONT / BRAKE_FRONT / GAS / SUSP_REAR を個別パネルで表示
- `enableAutoRange(axis="y")` を先に呼んでから X軸範囲設定（pyqtgraph順序ルール）

**タスク3: lap_overlay_data.json 依存を除去**
- WaveformViewクラスのデータソースをCSVに切り替える
- 既存の左パネル（DB由来の Run選択）は残す（Problem Log との紐付けに使用）

**タスク4: Problem Log との連携**
- CSVを開いた状態で波形を見ながら「+ Problem追加」ができること
- Problem追加時に現在のTime位置（秒）をフィールドに自動入力（オプション）

**タスク4b: WaveformView Time軸対応 — ✅ 完了（2026-05-03 Claude Code）**

実装済みロジック：
```python
# x_mode の決定（CsvImportTab._send_to_waveform 内）
if "time" チャンネルがマッピング済み:
    x_mode = "time"   # X値 = ラップ開始からの経過秒数（0始まり）
else:
    x_mode = "progress"  # X値 = 行インデックス正規化 0.0-1.0

# WaveformView._draw() での分岐
if x_mode == "time":
    _normalize_x() をスキップ → 生の秒値をそのままプロット
    enableAutoRange(axis="x")  # 実際の時間範囲に自動フィット
    Turn markers をスキップ（進捗位置基準のため無効）
else:
    従来通り 0-1 正規化 → setXRange(0,1)
    Turn markers 表示

# "Reference only" 警告
x_mode == "time" → 非表示
x_mode == "progress" → 表示
```

**タスク5（将来・最重要）: PH1〜PH5 自動分割ロジック**
- SPEED + BRAKE_FRONT + GAS の組み合わせでコーナーフェーズを自動検出
- PH1（ブレーキング開始）、PH2（ブレーキングピーク）、PH3（アペックス）、PH4（スロットルオン）、PH5（フル加速）
- 波形上にフェーズ境界をオーバーレイ表示
- Problem Log記録時にフェーズを自動提案
- **これが最強の武器になる（corner_phase_data.jsonとの統合も視野）**

### Workbench フェーズ・ロードマップ（2026-05-05 更新）

| Phase | 機能 | 状態 |
|-------|------|------|
| **Phase 1** | CSV Import / Time軸 / DB駆動Lap分割 | ✅ 完了 |
| **Phase 2** | LinearRegionItem 範囲選択 → Problem Log自動入力 | ✅ 完了 |
| **Phase 3** | UX再設計: 左サイドバー廃止・分割ビュー・チャンネル選択 | ✅ 完了 |
| **Phase 4** | Knowledge Cases昇格（繰り返し問題→知見化） | 将来 |
| **Phase 5** | PH1-PH5自動フェーズ検出 → Problem Log提案（最重要武器） | 将来 |

**Phase 2 実装済み技術メモ:**
```python
# LinearRegionItem — 波形上の青ハイライト
region = LinearRegionItem([0, 100], movable=True)
region.sigRegionChanged.connect(self._on_region_changed)
self._pw_speed.addItem(region)  # SpeedパネルにAdd

# p.clear() 後に必ず再Add（データロード時のバグ対策）
for p in self._all_plots:
    p.clear()
self._pw_speed.addItem(self._region)  # ← 必須

# 初期値を _redraw() でデータ範囲の20-40%に設定
lo = x_vals[0] + 0.2 * (x_vals[-1] - x_vals[0])
hi = x_vals[0] + 0.4 * (x_vals[-1] - x_vals[0])
self._region.setRegion([lo, hi])

# "Problem Log へ送る" ボタン → prefill_from_waveform() 呼び出し
# → QSplitter 右パネル (_ProblemRightPanel) を展開し Range 自動表示
```

**Phase 3 実装済み技術メモ:**
```python
# 個別 PlotWidget（GraphicsLayoutWidget から移行）
self._pw_speed = pg.PlotWidget(title="Speed (km/h)")
# X-link
for _pw in [self._pw_brake, self._pw_gas, self._pw_suspf, self._pw_suspr]:
    _pw.setXLink(self._pw_speed)

# QSplitter — 波形左 / Problem入力右
self._wave_splitter = QSplitter(Qt.Orientation.Horizontal)
self._wave_splitter.addWidget(self._wave_scroll)
self._wave_splitter.addWidget(self._right_panel)
self._wave_splitter.setSizes([1, 0])  # 初期は右パネル非表示

# layout に stretch=1 を必ず指定（グリーンバグ防止）
layout.addWidget(self._wave_splitter, 1)

# 各ラベルに固定高さ（QLabel が縦拡張しないよう）
self._lbl_warn.setFixedHeight(24)
self._lbl_xmode.setFixedHeight(22)
```

### 解決済みバグ（2026-05-05 まで 確認済み）
- ✅ X軸正規化: `_normalize_x()` で各ラップ独立0-1正規化
- ✅ Speed Y軸: `enableAutoRange(axis="y")` → `setXRange()` の順序
- ✅ turn_templates: `isinstance()` でlist/dict両対応 + circuit名正規化
- ✅ ProblemLogTab フリーズ: `SELECT *` + `cur.description` で列名動的取得
- ✅ LinearRegionItem 選択不可: 初期値 [0.2, 0.4] が小さすぎ → [0, 100] に変更
- ✅ LinearRegionItem 消滅: `p.clear()` 後に `self._pw_speed.addItem(self._region)` 再追加
- ✅ レイアウト破損: `setFixedHeight()` + `layout.addWidget(splitter, 1)` で修正

### 起動方法
```bash
cd ~/Desktop/"Data TS24 Claude"/05_SCRIPTS
python3 ts24_workbench.py
```

### サーキット情報（Workbench Distance軸 設計用）

| サーキット | 1周距離 | 確認方法 |
|-----------|---------|---------|
| **ASSEN** | **4555m** | X_F1-#77-03_DISTANCE.csv で確認（13665/3=4555, 27329/6=4555 完全一致） |
| その他 | 未確認 | 走行データから都度計算 |

**Assenセッション構造の確認例（X_F1-#77-03_DISTANCE.csv）:**
```
時間ギャップ法で2セグメントに分割:
  Segment 1 (CSV Lap 1): 3周 × 4555m = 13665m / 300.6s → 平均 1:40,21
  Gap: 105s（ピットストップ）
  Segment 2 (CSV Lap 2): 6周 × 4555m = 27329m / 594.4s → 平均 1:39,07
  合計: 9周
```

**重要設計メモ:**
**Lap分割の優先順位（2026-05-03 v2確定 / commit 8bc5973）:**
```
優先1: CSV内の Lap / LapNo / LapCounter / LapTrigger 列 → ✅ 最も正確（2D側でExportする）
優先2: DB の laps テーブル駆動分割                        → ✅ sub-0.02s精度（最重要手法）
優先3: 固定距離近似分割（dist >= circuit_len_m）          → ⚠ Approximate表示（ズレ累積あり）
優先4: 時間ギャップ > 5s                                  → セッション境界のみ（最終fallback）
```

**DB駆動分割アルゴリズム（ROUND3_ASSEN_FP_DA77_R1で検証済み）:**
1. CSVの時間ギャップ(>5s)を検出 → セグメント境界とgap_dur（ピット等）を記録
2. DBのlapsテーブルからis_outlap≠1のラップを取得
3. CSVギャップ秒数とDBラップタイムをGAP_TOLERANCE=2sで照合 → gap lapを除外
4. 有効ラップのlap_time_sを累積し np.searchsorted でCSV行番号を特定
- 結果: 9ラップ × 0→4554m、最大誤差 0.02s ✅

**CsvImportTabとDB連携の仕組み（v2以降）:**
- `CsvImportTab(wave_view=..., db=self._db)` — dbパラメータ追加
- `_on_run_selected` → `self._tab_csv.set_run(run_id)` で選択Runを通知
- `WorkbenchDB.get_laps(run_id)` → `SELECT lap_no, lap_time_s, is_outlap FROM laps WHERE run_id=?`
- 左パネルでRun未選択時は優先3（固定距離）または優先4（時間ギャップ）にfallback

**固定距離分割の限界（参考）:**
```python
circuit_len_m = 4555  # Assen確定値（4555mで9ラップ完全検出）
min_span = circuit_len_m * 0.5  # 50%未満はピットアーティファクトとして除外
```

---

## 6b. 2D Analyzer / CalcTool 知識ベース（2026-05-05 追加）

**参照ファイル:** `04_REFERENCE/2D_Software_Knowledge.md`
**元文書:** `04_REFERENCE/2D_Software/` 内 3冊のPDF（Analyzer / CalcTool / GPSTracks）

### Workbench との接続ポイント

| 項目 | 内容 |
|------|------|
| **CSV発生源** | `2D_DistanceAndTimeCH.CAL` が `Dist` 列（累積オドメーター）を生成する |
| **Lap列** | 2D GPSトリガー(`CreateLapTriggerByLine`)から生成 → Lap分割Priority 1 |
| **セパレータ** | `;`（セミコロン）または `,`。`_load_csv()` で両対応済み |
| **エンコーディング** | UTF-8-sig または Shift-JIS。両対応済み |

### 2D側でできること（将来の改善候補）

| 機能 | 内容 | TS24への示唆 |
|------|------|-------------|
| **Section Times** | GPS座標でセクションを定義しタイムを自動計算 | Workbench DBに `section_times` テーブル追加で自動取込可能 |
| **2D_Conditions.CAL** | コーナーフェーズ（PH1-5）をCAL定義 | CSV の `phase` 列として出力 → Workbench Phase 5 と統合 |
| **CAL計算関数** | `AvgWhileTrue`, `MaxWhileTrue`, `CreateLapTriggerByLine` など | カスタム分析チャンネルをCSVに含めてExport可能 |

---

## 6c. WheelForce_Proxy — サスペンション力計算（2026-05-05 確定）

### 確定パラメータ（ZX-636R）

| パラメータ | 値 | 根拠 |
|----------|---|------|
| リアリンク比 LR | **2.0**（実走域 MR=0.5） | ZeroChassisデータ `Link ratio.csv`（SUSP_R 40-58mm範囲） |
| フロント MR | **1.0**（テレスコピック直結） | 構造上の定義 |
| センサーゼロ点 | 完全伸び切り（オフセット補正不要） | ライダー確認済み |

### 計算式（Level 1 バネ成分のみ）

```python
# フロント
WF_F_N = SUSP_FRONT_mm × (F_SPR_L + F_SPR_R) / 2   # [N]
# 例: 71.8 × (9.0+9.0)/2 = 71.8 × 9.0 = 647N

# リア（LR=2.0 → MR=0.5）
WF_R_N = SUSP_REAR_mm × R_SPR × 0.5                  # [N]
# 例: 16.2 × 84 × 0.5 = 682N
```

### ASSEN APEX の基準値（参照用）

| ライダー | セッション | WF_F_N | WF_R_N | F/R 比 |
|---------|---------|--------|--------|--------|
| DA77 | FP（R1-R3平均） | ~604N | ~643N | **0.94**（均等） |
| JA52 | FP（R1-R3平均） | ~618N | ~766N | **0.79**（リア重め） |
| DA77 | RACE1 | 618N | 775N | 0.80 |

DA77 は F/R ≈ 0.94、JA52 は F/R ≈ 0.79 が ASSEN の特徴的パターン。

### CAL実装例（2D Analyzer用 / TS24_WheelForce_Proxy v1.0）

```cal
; FRONT
C_Ff_filt = F(#SUSP_FRONT, F(10))
Front_SpringLoad_Proxy = *(#C_Ff_filt, 9.5)       ; [N] ← per-run のバネレートを入力

; REAR
C_Fr_filt = F(#SUSP_REAR, F(10))
C_Fr_shock_force = *(#C_Fr_filt, 84.0)             ; [N] ← per-run の R_SPR
Rear_WheelForce_Proxy = *(#C_Fr_shock_force, 0.5)  ; wheel-position force [N]

; VELOCITY (Level 2 準備)
Front_Susp_Velocity = F'(#C_Ff_filt)               ; [mm/s]
Rear_Susp_Velocity  = F'(#C_Fr_filt)               ; [mm/s]
```

**注意:** Level 1 = バネ成分のみ。ダンパー力・空力・慣性力は含まれない。

---

## 7. ダッシュボード（dashboard.py）構成

### ページ一覧と役割

| ページ | 役割 | 主なデータソース |
|-------|------|----------------|
| Problem Analysis | 問題タグ頻度・位相分布 | SQLite tags |
| Heatmap | サーキット×フェーズのヒートマップ | SQLite tags |
| Season Trend | シーズン推移 | SQLite sessions |
| Race Results | 公式結果 | SQLite race_results |
| Race Pace | ペース分析 | SQLite |
| Lap Analysis | ラップタイム分析 | SQLite |
| 2D Lap Data | MESラップデータ可視化 | lap_suspension_data.json |
| Suspension Dynamics | APEX/Braking/PitLimiter可視化 | dynamics_data.json |
| Lap Sus Stats | ラップ統計・APEX比較 | lap_suspension_data.json |
| **Setup Target** | FAST/SLOW比較・Δ分析 | lap_suspension_data.json + lap_times_data.json |
| **Corner Phase** | PH1-2/PH3/PH4-5タイミング比較・APEX速度ヒートマップ | corner_phase_data.json |
| **Lap Overlay** | ラップ間マルチチャンネル重ね合わせ・ΔTimeトレース | lap_overlay_data.json |
| Session Detail | セッション詳細 | SQLite |
| Trend Analysis | シーズントレンド | SQLite |
| Problem→Solution | 問題→解決策DB | SQLite |
| Performance | パフォーマンス分析 | SQLite |
| AI Advice | Claude AIセットアップ提案 | Claude API |
| Setup Chat | 通常チャット | Claude API |

### 重要な実装詳細

```python
# レイアウト: st.sidebar非使用、st.columns([1,5])でナビ+コンテンツ
_nav_col, _content_col = st.columns([1, 5], gap="small")

# フローティングチャット: st.components.v1.html(height=0)で親DOMに注入
# → URLもページ状態も変更しない、Streamlit rerun不要

# サーキット名正規化
_dyn_norm_circuit()  # WORKSHOP/AUSTRALIA → PHILLIP ISLAND など

# pandas 2.2+ 対策: groupby.apply非推奨 → 手動ループで代替
```

### UIスタイル（Power BIスタイル）

```python
# 背景色: #FFFFFF (白), グリッド: #E5E7EB
# アクセント: #0078D4 (Microsoft Blue)
# フォント: Arial, sans-serif
# ゼロライン: line_dash="dot", line_width=1.8
```

---

### Workbench 引き継ぎ事項（2026-05-03）

TS24 Engineer Workbench v0.1 を新規追加。

| ファイル | 役割 |
|---------|------|
| `ts24_workbench.py` | PyQt6デスクトップアプリ本体 |
| `create_workbench_tables.py` | `problem_log` / `setup_decision_log` テーブル作成（べき等） |
| `requirements_workbench.txt` | PyQt6 / pyqtgraph / pandas |
| `TS24_Workbench.command` | macOS起動スクリプト |

**起動手順（初回）:**
```bash
pip install PyQt6 pyqtgraph
python create_workbench_tables.py
python ts24_workbench.py
```

**波形ビューの既知事項:**
- `lap_overlay_data.json` の `lap_progress` がラン全体の連続値の場合、`_draw()` 内で自動正規化して 0.0–1.0 に変換する（X軸が 1.8 に伸びるバグを修正済み）
- Y軸は `enableAutoRange(axis="y")` で自動スケール（Speed: 0–255 km/h 正常表示）
- turn_templates.json の list / dict 両構造に対応

**書き込み先:** `ts24_unified.db` の `problem_log` / `setup_decision_log` のみ。既存テーブル変更なし。

---

## 7b. race_memory.json — 知見蓄積ファイル

> **【保持 / 将来DB化候補】** `race_memory.json` は **削除しない**（2026-06-20 Tatsuki決定 §21）。
> 知見蓄積をDB(problem_log/setup_decision_log等)へ完全移行する設計が確定するまで現行ファイルを維持。
> dashboard.py(memory_service)が参照中。以下は現行運用（DB移行までは有効）。

**このファイルはCoworkとClaude Codeの共有記憶。**

```json
{
  "version": 2,
  "circuit_insights": {
    "PORTIMAO": {
      "DA77": ["[2026-04-29] THR_ON SusF consistently 3-5mm higher when fast"],
      "JA52": []
    }
  },
  "global_insights": [],
  "setup_learnings": [],
  "conversation_summaries": []
}
```

**Claude Code への指示:** 新しいMESデータを処理したとき、以下を `race_memory.json` に追記すること。

```json
// setup_learningsに追記するフォーマット
{
  "date": "YYYY-MM-DD",
  "circuit": "PORTIMAO",
  "rider": "DA77",
  "run_no": 3,
  "insight": "New MES data processed: 12 laps, THR_ON avg 42.3mm",
  "source": "auto_processing"
}
```

---

## 8. 重要な命名・コーディング規則

### データ列名

```
THRON_SUSF_AVG   ← THR_ON定義でのフロントサスペンション平均（mm）
THRON_SUSR_AVG   ← THR_ON定義でのリアサスペンション平均（mm）
BRK_SUSF_AVG     ← Braking Entry時のフロントサス（mm）
BRK_SUSR_AVG     ← Braking Entry時のリアサス（mm）
APEX_SPD_AVG     ← APEX通過速度（km/h）
THRON_CNT        ← THR_ON検出カウント（0の場合はデータなし）
```

### サーキット名正規化ルール

```python
"WORKSHOP"   → "PHILLIP ISLAND"
"AUSTRALIA"  → "PHILLIP ISLAND"
"ASSEN"      → "ASSEN"
"CREMONA"    → "CREMONA"
"JEREZ"      → "JEREZ"
"PORTIMAO"   → "PORTIMAO"
```

### ファイル命名規則（レポート）

```
20260417-ROUND3-DA77.xlsx   ← YYYYMMDD-EVENTTYPE-RIDER
```

---

## 9. ワークフロー（新レース/テスト後）

### Step 1: データ収集（Tatsuki）
1. MESファイルを `04_MES/[RIDER]/[DATE]/` に置く
2. レポートExcelを `01_REPORTS/[RIDER]/` に置く

### Step 2: データ処理（Claude Code）
```bash
# MES再処理
python lap_suspension_stats.py       # → lap_suspension_data.json 更新
python corner_phase_analysis.py      # → corner_phase_data.json 更新
python lap_overlay_extractor.py      # → lap_overlay_data.json 更新（844ラップ×200点）

# Git push
./git_push_fix.command
```

### Step 3: 分析（Cowork Claude + Tatsuki）
- ダッシュボードを開いてフローティングチャット（🤖）で対話
- Setup Target ページでFAST/SLOW差分を確認
- race_memory.json に知見が自動蓄積される

### Step 4: ソリューション実施（Tatsuki）
- 提案されたセットアップ変更を次のセッションで試す
- 結果をレポートに記録

---

## 10. 現在の技術的課題と優先事項

### 解決済み ✅
- pandas 2.2+ `groupby.apply` 非推奨 → 手動ループで対応
- Setup Target: データソースをdynamics → LAP_SUSPENSION (THR_ON) に変更
- **WheelForce_Proxy (Level 1) 実装完了（2026-05-05）**: WF_F_APEX_N/WF_R_APEX_N/WF_F_BRK_N/WF_R_BRK_N 4列を lap_suspension_stats.py / SQLite / JSON / Excel に追加。MR=0.5 (LR=2.0 ZX-636R確定値)、春レート = runs table から per-run JOIN。
- フローティングチャット: URL変更によるページリセット問題 → DOM直接注入で解決
- APEXチャート: Power BIスタイルの散布図実装
- Δチャート: 折れ線+マーカー、サーキット間トレンド可視化

### 進行中 🔄
- フローティングチャットのFABボタン動作確認（DOM注入方式）
- race_memory.json の知見蓄積テスト

### 今後の優先課題 📋
1. **相関分析ページ:** サスペンション指標とラップタイムの相関係数可視化
2. **セットアップ変更効果検証:** 同一条件での前後比較の自動化
3. **race_memory.json活用:** Claude Codeが処理完了時に自動でinsightを追記
4. **Supabase同期の安定化:** 新レポートの自動クラウド同期

---

## 11. Claude Code への具体的な作業指示

**このプロジェクトをClaudeCodeで開くときは必ずこのファイルを最初に読め。**

### 作業前チェックリスト
- [ ] CLAUDE.md を読んだ
- [ ] `race_memory.json` に前回の知見があれば把握した
- [ ] `git status` で現在の差分を確認した

### dashboard.py を変更するとき
1. 変更前に `python -m py_compile dashboard.py` で構文チェック
2. 変更内容を `race_memory.json` の `setup_learnings` に記録
3. `git_push_fix.command` でpush（または `git add . && git commit -m "..." && git push`）

### 新しいMESデータを処理するとき
```bash
cd ~/Desktop/"Data TS24 Claude"/05_SCRIPTS
python lap_suspension_stats.py
# 完了後、race_memory.jsonに処理記録を追記
```

### Cowork Claude への引き継ぎが必要なとき
`race_memory.json` の `conversation_summaries` に以下を追記：
```json
{
  "date": "YYYY-MM-DD",
  "page": "system",
  "rider": "ALL",
  "circuit": "ALL",
  "summary": "Claude Code作業内容: [具体的な内容]"
}
```

---

## 12. Cowork Claude への作業方針

**ダッシュボードでTatsukiと分析をするときの優先順位:**

1. **現在のページのデータを見る** → フローティングチャットのコンテキストに現在ページ・サーキット・ライダーが注入される
2. **race_memory.jsonの過去知見を確認** → 同じサーキットの過去の発見を踏まえて回答
3. **具体的な数値で提案する** → 「フロントを硬くする」ではなく「THR_ON SusF の目標値を38→42mmに調整」
4. **Claude Codeへの作業依頼はTatsukiを通じて伝える** → 「次にClaude Codeを使うとき、dashboard.pyの〇〇を更新してもらってください」

### ChatGPT監査に対応するための必須ルール（2026-05-01 確定）

**全ての分析・提案において以下を必ず守ること：**

1. **根拠データを明示する** — 「ASSENのFAST上位1/3ラップ平均でAPEX_SUSF_AVG=42.1mm」のように数値ソースを示す
2. **信頼度（Confidence）を付与する** — 高/中/低 または (信頼度:高) の形式で末尾に付ける
3. **使用したAPEX定義を明示する** — 現在は「APEX定義: BRAKE_FRONT -0.6~0.3 ∩ GAS 0~6% ∩ dTPS_A -10~100 ∩ SUSP_F 20~140 ∩ SUSP_R 5~50 (2026-04-30確定版)」
4. **一時的な結果を一般化しない** — 1セッションの結果を「常に〜」と表現しない
5. **race_memory.jsonへの保存は構造化された形式で** — 曖昧な自然文ではなく、数値・条件・信頼度を含める

**禁止事項:**
- 根拠のないセットアップ提案
- APEX定義の混在使用（どの定義か明示なしに使用）
- race_memory.json への曖昧な知見保存
- 1件のデータから全体を推論すること

### [Lap Overlayを使った分析をするとき]

**必ず以下3点を答えること:**
1. **どのコーナー・どのフェーズで最大の時間差が出ているか** — コーナー番号とフェーズ（PH1-2/PH3/PH4-5）を明示し、差を ms単位で提示する
2. **その差の原因** — ブレーキ操作（ph12_duration/ph12_brake_peak）・ガス操作（ph45_duration）・サスペンション挙動（ph3_susf_avg）から推察し、根拠データを示す
3. **複数ラップで再現性があるか** — 1ラップの比較結果を「常に〜」と一般化しない。可能なら複数ラップで確認を促す

**禁止:**
- `"全体的にAが速い"` のような定性的結論のみで終わること
- `"Speed-weighted Estimated ΔTime"` の値を「実際のΔTime」として断言すること（時間軸正規化のため実際の距離位置と異なる場合がある）
- コーナー番号の裏付けなしにフェーズ差を述べること

---

## 13. 設計原則 — TS24 SET-UP TOOL

### コーナー定義の哲学

```
コーナーは「検出するもの」ではなく「定義するもの」
→ Turn定義は回路固有テンプレート(turn_templates.json)で管理
→ manual_validated: true になるまでは参考値として扱う
→ GPSベースのDistance-based ΔTime 実装後に正式版へ更新予定
```

| ファイル | 役割 |
|---------|------|
| `turn_templates.json` | 各サーキットのTurn定義テンプレート（手動検証フラグ付き） |
| `extract_turn_templates.py` | corner_phase_data.json から draft を生成するスクリプト |

**manual_validated フラグ運用:**
- `false`: ブレーキクラスター検出による自動生成draft。画面上に警告表示。
- `true`: 実走データとのコーナーマップ照合で確認済み。警告非表示。

### ΔTime命名規則（厳守）

| 用語 | 定義 | 状態 |
|------|------|------|
| **Speed-weighted Estimated ΔTime** | time-normalized速度比による推定値 | 現行実装 |
| **Distance-based ΔTime** | GPS距離軸による正式値 | 将来実装 |

**禁止:** `"ΔTime"` 単体での表記。必ず上記いずれかの正式名称を使うこと。

---

*このファイルはプロジェクトの進化とともに更新する。*
*重要な決定・変更・発見は必ずここに反映すること。*

---

## 14. ツール役割定義（2026-05-13 確定）

### 3ツールの明確な役割分担

| ツール | 対象ユーザー | 役割 | 方針 |
|-------|------------|------|------|
| **Workbench** (`ts24_workbench.py`) | エンジニア（Tatsuki） | 記録・思考・検証 | DB中心・CSV不要・波形なし |
| **Dashboard** (`dashboard.py`) | 関係者（チーム・スポンサー等） | 情報共有・結果報告 | シンプル・直感的・技術的グラフなし |
| **Cowork Claude** | エンジニア | 深い分析・解釈・提案 | DBに蓄積されたデータを対話的に分析 |

### Workbench: 波形機能の廃止決定（2026-05-13）

**決定:** `WaveformView` タブ・CSV Import 機能を Workbench から完全削除する。

**理由:**
- 波形解析は 2D Analyzer（MES専用ソフト）が担う
- Workbench の本質は「記録・思考・検証」であり、波形表示は本来の目的外
- CSV不要でWorkbenchを使えることが最重要（波形削除でこれが実現）

**廃止対象クラス/タブ:**
- `WaveformView` クラス全体
- `CsvImportTab` クラス全体
- 波形タブ（トップレベルタブから削除）

**廃止後のタブ構成:**
```
[🗺️ Run Browser] [⚡ Quick Log] [📋 Problem Log] [🔧 Setup Decision] [📈 Trend Analysis]
```

### Dashboard: シンプル化の方針

**残すもの（直感的・関係者向け）:**
- シーズン順位・ポイント推移
- ラウンド別ラップタイム結果
- 問題サマリー（セッションごとの件数）
- セットアップ変更の前後比較（シンプル数値）

**将来的に削除候補（エンジニア向けすぎる）:**
- Lap Overlay / Corner Phase Analysis / Suspension Dynamics
- Setup Target の複雑な散布図群

※ Dashboard のシンプル化は Workbench Phase 1 完了後に着手する。

---

## 15. Workbench 改善計画 v1.2（2026-05-12 Cowork Claude 設計）

**詳細仕様:** `05_SCRIPTS/workbench_update_spec_v1.2.md` を必ず読むこと。

### Fix 1: 波形グラフ X軸同期（優先度: 高）

**問題:** `WaveformView` の5つのPlotWidgetが独立。ズーム/パンが連動しない。
**解決策:** `setXLink()` で全グラフをSpeedグラフにリンク + クロスヘア縦線。

```python
# _setup_ui() 内、全PlotWidget生成後に追加
for pw in self._plot_widgets[1:]:
    pw.setXLink(self._plot_widgets[0])  # brake/gas/susf/susr → speed に同期

# クロスヘア縦線
self._vlines = []
for pw in self._plot_widgets:
    vl = pg.InfiniteLine(angle=90, movable=False,
                         pen=pg.mkPen(color='y', width=1, style=Qt.PenStyle.DashLine))
    pw.addItem(vl, ignoreBounds=True)
    self._vlines.append(vl)

self._plot_widgets[0].scene().sigMouseMoved.connect(self._on_mouse_moved)

def _on_mouse_moved(self, evt):
    pos = evt[0] if isinstance(evt, tuple) else evt
    if self._plot_widgets[0].sceneBoundingRect().contains(pos):
        mp = self._plot_widgets[0].plotItem.vb.mapSceneToView(pos)
        for vl in self._vlines:
            vl.setPos(mp.x())
```

### Fix 2: Problem Log / Setup Decision の独立Run選択（優先度: 高）

**問題:** 両タブがCSV未ロード時に Run=(未選択) → テーブル空。
**解決策:** タブ内にDBベースのCircuit + Run選択コンボを追加（全Run表示オプション付き）。

### Enhancement 3: バイク姿勢分析タブ追加（優先度: 中）

**新サブタブ `🎯 姿勢分析`** を TrendAnalysisTab に追加。

| 指標 | 計算式 | 解釈 |
|------|--------|------|
| **Pitch** | ApexSusF − ApexSusR [mm] | 負=ノーズDOWN(ターンイン良), 正=ノーズUP |
| **Heave** | (ApexSusF + ApexSusR) / 2 [mm] | バイク全体の沈み込み量 |

**4パネル構成:**
1. Pitch vs Lap Time 散布図（目標ゾーン表示）
2. Phase Space（ApexSusF vs ApexSusR）— ライダー好みクラスター可視化
3. ライダー指紋レーダーチャート（matplotlib → QLabel Pixmap）
4. Lap-by-Lap Pitch/Heave 推移（タイヤ摩耗トラッキング）

**依存ライブラリ追加:** `requirements_workbench.txt` に `scipy>=1.10.0`, `matplotlib>=3.7.0` を追記。

### 実装後の状態テーブル（更新予定）

| 機能 | 実装前 | 実装後 |
|------|--------|--------|
| 波形X軸同期 | ❌ 独立 | ✅ setXLink() |
| クロスヘアカーソル | ❌ なし | ✅ 全グラフ連動 |
| Problem LogのRun選択 | ❌ CSV依存 | ✅ DB独立 |
| Pitch/Heave分析 | ❌ なし | ✅ 姿勢分析タブ |
| レーダーチャート | ❌ なし | ✅ DA77 vs JA52 |

---

## 16. Workbench 再設計 v2.0（2026-05-13 Cowork Claude 設計）

**詳細仕様:** `05_SCRIPTS/workbench_redesign_spec_v2.0.md` を必ず読むこと。

### 基本方針の転換

**従来:** 「波形ビューアツール（CSV必須）」  
**新方針:** 「記録・思考・検証ツール（CSV不要でも使える）」

```
現場で気づいた問題 → 30秒でQuick Log（DBのみ）
               ↓
      問題 → 仮説 → セットアップ変更 → 結果 の一連を記録
               ↓
      知見（Knowledge Case）として蓄積 → 次ラウンドに活用
```

### 新規DBテーブル（3つ）

| テーブル | 役割 |
|---------|------|
| `analysis_note` | 思考・仮説・気づきの記録（問題に紐付け可） |
| `result_validation` | セットアップ変更の効果検証 |
| `knowledge_cases` | 繰り返し問題 → 解決パターンの知識化 |

**CREATE文:** `workbench_redesign_spec_v2.0.md` の Section 2 に完全定義あり。

### 新UIタブ（追加）

| タブ名 | 目的 |
|-------|------|
| 🗺️ Run Browser | DB全Runを横断閲覧・フィルタ・Run切り替え |
| ⚡ Quick Log | CSV不要で問題を30秒記録（最重要） |
| 💭 Analysis Note | 仮説・思考を紐付き記録 |
| ✅ Result Validation | 変更前後の効果検証 |
| 📚 Knowledge Base | 蓄積知見の検索・参照 |

### Phase 1 実装優先事項（Claude Code指示）

1. `create_workbench_tables.py` に3新テーブル追加（analysis_note, result_validation, knowledge_cases）
2. `ts24_workbench.py` に `RunBrowserTab` 追加（DBからRun一覧 → フィルタ → Run切り替え）
3. `ts24_workbench.py` に `QuickLogTab` 追加（Circuit/Session/Run選択 + ProblemLog記録フォーム）
4. タブ順序更新: 先頭に「Run Browser」「Quick Log」を配置

**成功基準:** CSV未ロード状態でQuick Logタブを開き、問題を30秒以内に記録できること。

### Phase 2〜3（将来実装）

- Analysis Note タブ（思考記録・問題紐付け）
- Result Validation タブ（効果検証フォーム）
- Knowledge Base タブ（知見検索）
- TrendAnalysisTab への BI統合ビュー

### Claude Code への作業指示文（コピーしてそのまま渡すこと）

```
CLAUDE.md の Section 14・15・16 を読んでから実装すること。
また 05_SCRIPTS/workbench_redesign_spec_v2.0.md と 05_SCRIPTS/workbench_update_spec_v1.2.md も参照すること。

【最重要決定】WaveformView と CsvImportTab を完全削除する（2026-05-13 確定）
  - WaveformView クラス全体を削除
  - CsvImportTab クラス全体を削除
  - 波形タブをトップレベルタブから削除
  - 波形関連のimport（pyqtgraph以外に依存するもの）を整理

実装優先順位:
  1. [削除] WaveformView / CsvImportTab の完全削除
  2. [v2.0] create_workbench_tables.py に analysis_note/result_validation/knowledge_cases を追加
  3. [v2.0] ts24_workbench.py に RunBrowserTab を新規作成（DB全Run一覧・フィルタ・Run切り替え）
  4. [v2.0] ts24_workbench.py に QuickLogTab を新規作成（CSV不要・30秒記録）
  5. [v1.2] ProblemLogTab / SetupDecisionTab に独立Run選択UIを追加（Circuit + Run コンボ）

完了後のタブ構成（この順序で）:
  [🗺️ Run Browser] [⚡ Quick Log] [📋 Problem Log] [🔧 Setup Decision] [📈 Trend Analysis]

成功基準:
  - Workbenchを起動してCSVを一切使わずにQuick Logで問題を記録できること
  - Problem LogタブがCSV未ロードでも全件表示できること

完了後チェック:
  python3 -m py_compile ts24_workbench.py
  race_memory.json の conversation_summaries に実装内容を記録
```

---

## 17. 自動化システム v1.0（2026-05-13 Cowork Claude 設計）

**詳細仕様:** `05_SCRIPTS/automation_spec_v1.0.md` を必ず読むこと。

### 構成概要

単一デーモン `ts24_watcher.py`（macOS LaunchAgent）が以下を監視:

| 監視フォルダ | ファイル種別 | 処理 |
|------------|-----------|------|
| `07_RESULTS/` | `*.pdf` | pdf_result_extractor.py → race_results テーブル |
| `01_REPORTS/**` | `*ROUND*.xlsx` | report_importer.py → DB Master + SQLite |
| `DATA 2D/**` | `*.MES` | mes_importer.py → 既存スクリプト群を順次実行 |
| `02_DATABASE/ts24_unified.db` | DB変更 | Workbench QFileSystemWatcher でリロード |

### 最重要ルール: DB Masterの既存フォーマット厳守

**既存シートのフォーマット（フォント・色・レイアウト）は一切変更しないこと。**  
データ行を追加するだけ。スタイルは必ず既存行からコピー（openpyxl copy_style 相当）。

### 新規追加のみ（変更禁止）

- **SQLite**: `race_results` テーブルを新規作成（既存テーブル変更なし）
- **DB Master**: 既存シートにデータ行を追加のみ。新シート `RACE_RESULTS` は新規作成可。

### Claude Code への作業指示文（コピーしてそのまま渡すこと）

```
CLAUDE.md の Section 17 と 05_SCRIPTS/automation_spec_v1.0.md を読んでから実装すること。

【最重要制約】TS24 DB Master.xlsx の既存シートのフォーマットは絶対に変更しないこと。
  データ行の追加は OK。スタイルは必ず既存行から copy すること。

実装優先順位:
  1. ts24_watcher.py — watchdog 監視デーモン骨格 + LaunchAgent plist 生成スクリプト
  2. report_importer.py — excel_parser.py の CLI化 + watcher からの呼び出し
  3. race_results テーブル CREATE 文を create_workbench_tables.py に追加
  4. pdf_result_extractor.py — pdfplumber で結果/セクターを抽出 → race_results テーブル
  5. mes_importer.py — 既存スクリプト群（lap_suspension_stats / parse_2d_channels / parse_2d_to_excel）を順次呼び出すオーケストレーター
  6. ts24_workbench.py に QFileSystemWatcher を追加（各タブに refresh() メソッドも追加）

完了後チェック:
  launchctl list | grep ts24  （デーモン起動確認）
  テスト: 07_RESULTS/TEST/ にPDFをコピー → watcher.log を確認
  race_memory.json の conversation_summaries に実装内容を記録
```

---

## 18. DB再構築 + Workbench進化（2026-06-18〜19 Claude Code 実施）

正本DB = `02_DATABASE/ts24_unified.db`（cutover済・Supabase/Workbench反映済）。設計書: `reports/partb_roadmap_20260619.md`, `reports/workbench_levelup_review_20260619.md`。

### 18a. データ層の修正（build_master_db.py / cutover_db.py）
- **split-lap修正**: `.LAP` ヘッダ `vals[1]` を時間ベース(=1秒あたり単位数)として読む `_lap_timebase()`。lean export=1000(ms)/238ch Dorna export=400(400Hz)。旧 /1000固定で2025 ROUND10 Aragon等が2.5倍短い偽ラップになっていた→是正(45s→114s)。
- **is_outlap 頑健化** `_recompute_is_outlap()`: ①物理下限stray除去(>200km/h相当=track_m/55.56) ②GRID/FORMATION除去 ③stray除外後run_min×1.15 ④単一ラップの上限絶対ガード(circuit P10×1.25)。best/avgは is_outlap=0のみ集計。旧「min×1.15のみ」は stray反転(MOST R2=56.2)・単一グリッドラップbest昇格(PORTIMAO)の両汚染を許していた。
- **HED Fastestフロア**: `extract_outing` で HED `Fastest lap`×0.97 未満の stray を除外。
- **受入ゲート(SPEC §8)**: `|2D session最速 − PDF best| > 1.5s = 0件` をビルド合否条件に。
- **恒久化**: runs/laps に created_at/updated_at、laps に is_outlap、`lap_suspension`(per-lap全件)を build で再生成。cutover は best_worst_pairs を保持＋旧→新run_id再マップ。
- **コメント抽出修正**: `_scanon_report` で "TEST2 DAY1"→"TEST2_DAY1"(build側canonと一致)。TESTイベントのコメント紐付け復活で **comment付きrun 80→142**(JEREZ 0→27, CREMONA 0→15等)。※TEST1はレポート無・ROUND11は2D未取込のため178には届かない。
- **NEW抽出指標(Tatsukiアイデア 2026-06-19)**: lap単位で
  - サス速度(ダンピング): `f_dive_spd/f_reb_spd/r_dive_spd/r_reb_spd`(位置微分のピークmm/s, 圧縮=Diving/伸び=Rebound)。位置balance=バネ/ジオメトリ, 速度=ダンピング で判断補完。
  - `rear_light_brk`: ブレーキ区間(BRAKE_FRONT≥5bar)で SUSP_REAR≤1mm の割合%。大=フロントのみで停止=ブレーキバランス指標。
  - **CORNER_EXIT** を lap_suspension に射影(ce_count/ce_spd_avg/ce_susF_avg/ce_susR_avg + wf_f/r_ce_n)。
- v2 PDF順位を本番 race_results へ反映(`apply_pdf_positions_v2.py` 自然キーUPSERT・COALESCEで既存値保護)→ performance.session_position 77件。
- Supabase: `sync_to_supabase.py` v3 新スキーマ(race_results/lap_times/sessions_2d/lap_times_2d)。conflict_col に **date 追加**(同一round番号がシーズン跨ぎで衝突するため。§1c参照)。

### 18b. DB Master.xlsx（build_excel_master.py）= 9シート構成
- 削除: BEST_WORST_ANALYSIS / SESSION_SUMMARY / TYRE_LOG / CHASSIS_GEO
- 再生成(DB由来): RUN_LOG / LAP_TIMES / PERFORMANCE_CORRELATION(FAST緑·SLOW赤強調) / DYNAMICS_ANALYSIS(INFO/APEX/BRAKING ENTRY/FULL BRAKING/**CORNER EXIT**/**DAMPING(F-Dive/F-Reb/R-Dive/R-Reb/RearLight%)** の6グループ・空列廃止) / PROBLEM_LIBRARY / LAP_SUSPENSION(per-lap全件)
- 保持(未再生成・要Phase3): DB_LOG / TREND_ANALYSIS(コメント/問題トレンド・旧内容) / SOLUTION_SEARCH

### 18c. Workbench（ts24_workbench.py）
- **Trend Analysis 廃止 → `CommentAnalysisTab`("💬 Comment Analysis") 新設**: ①Circuit×Tag再発頻度(3回以上=赤=コース特性の問題) ②コメント詳細(タイヤ変更/Best Lap/Tag, タイヤ言及は淡色強調) ③フィルタ(Circuit/Rider/Tag/キーワード/タイヤ関連のみ)。データ源 runs.comment+run_tags+runs.tyre/best_lap。
- "📊 Setup Trend"(SetupTrendTab) 削除。Posture を "🦾 Suspension/Posture" に改称(実体は pitch/heave + サス分析)。
- 接続先=ts24_unified.db(新データ)。Run Browser/Quick Log/Problem Log/Setup Decision/Suspension/Race/Comment が稼働。**GUIスモークテストはローカルで要実施**(ヘッドレス不可)。

### 18d. 監査・残課題
- マルチエージェント数値監査(30エージェント): 全数値整合性を検証→11確定欠陥は is_outlap ロジック1点に収束→恒久修正で一括解消。`audit_db_dump.py`(全テーブル数値ダンプ→/tmp)で再現可。
- **残(Part B 未着手)**: Phase3=TREND_ANALYSIS/SOLUTION_SEARCH のDB由来再生成 + problem_log充填(4→100+)、Setup Lookup(前回好調Setup逆引き=10x#1)、knowledge_cases自動提案(10x#2)、Temperature/Tyre-Aware Advisory(10x#3)、dashboard JSON(クラウド)再生成。詳細はタスク #5-#11 と上記reports。
- 新規スクリプト: `audit_db_dump.py`, `apply_pdf_positions_v2.py`。バックアップ: `02_DATABASE/_backup_20260618/`, `ts24_unified.old.db`。

---

## 19. ゾーン限定サス速度 + PH1-2リア0mm 抽出&UI（2026-06-20 Claude Code 実施 / Tatsuki承認設計）

**目的:** 既存ゾーンイベント(FULL_BRAKING/CORNER_EXIT)内のサス速度と PH1-2 のバイク姿勢(リア抜け)を、
セットアップ判断の根拠に使える形で抽出し、Workbench と DB Master で確認できるようにする。
従来は `f_dive_spd` 等が**ラップ全体ピークのみ**で、ゾーン限定 avg/peak と PH1-2 リア0mm時間が存在せず、
分析UIも無かった。

### 19a. 新5指標（`lap_suspension` のみに追加 / `laps`は不変）
| カラム | 定義 | ガード |
|--------|------|--------|
| `brk_f_dive_spd_avg` / `_peak` | FULL_BRAKING内 フロント圧縮方向(diving, v_f>0)速度の avg/peak [mm/s] | mask n≥5 **かつ** 圧縮サンプル n≥5、未満は NULL |
| `ce_r_spd_avg` / `_peak` | CORNER_EXIT内 リアサス速度**絶対値**(\|v_r\|)の avg/peak [mm/s] | mask n≥5、未満は NULL |
| `ph12_rear0_s` | PH1-2(代理マスク= BRAKE_FRONT≥0.3bar 進入相)で SUSP_REAR≤0mm の累積秒 [s] | 両ch存在時のみ。0秒は実測値として許容 |

- **設計確定事項(Tatsuki)**: ① n<5 は **必ずNULL**(0は「速度ゼロ」と誤読されるため厳禁)。信頼度として
  `fullbrk_count`/`ce_count` を併記。② CE Rearは v1で**絶対値**(動きの忙しさ)。将来 `ce_r_squat_spd_avg/peak`
  (圧縮方向)を別列で追加するのが理想。③ PH1-2 は当面 BRAKE≥0.3bar 代理。将来 `corner_phase_analysis.py`
  のコーナー単位PH1-2と統合。④ peak は既存 `f_dive_spd` との一貫性で `max()`。検証で p95 併記。
- **速度の性格**: グリッドR(M点)上の `np.gradient/dt`。既存 `f_dive_spd` と同一手法で**データセット内比較は正当**
  だが校正済み絶対mm/sではない(=相対ダンピング速度指数)。一人歩き禁止。
- 計算は `build_master_db.py` の `extract_outing()` に追加(`AREAS` マスク再構成 + `_vel()`/`_zone_mask()`)。
  lap dict → `extra_by_lapid` → `_build_lap_suspension(conn, extra_by_lapid)` 経由で **lap_suspension のみ**へ射影。

### 19b. 安全なDB反映（cutover不使用 / `backfill_susp_zone_speed.py` 新規）
全DB再ビルド+cutover(run_id再マップ=lap_id破壊リスク)を回避。手順:
1. `build_master_db.py --all --out /tmp/ts24_scratch.db` でスクラッチ再生成(受入ゲート0件合格・totals不変)。
2. **決定論ゲート**: scratch vs 正本の lap_suspension 既存40列を lap_id JOINで突合、`abs(diff)<1e-6`・lap_id集合一致を要求。
   `updated_at`(timestamp)と新5列は比較除外。→ **1202ラップ×40列 全一致で合格**(既存データ無改変を証明)。
3. 合格時のみ 正本 `ts24_unified.db` に5列 `ALTER ADD` + scratchから lap_id で UPDATE(1202行)。`laps`は不変。
4. **検証ログ**(NULL率/分布/peakのp95): brk_f_dive 非NULL1072(NULL10.8%, peak max/p95=1.97x健全) /
   ce_r 非NULL661(NULL45%=CE無しラップ多数, peak max/p95=4.28x→将来p95化候補) / ph12 非NULL1198(>0秒958件・
   mean0.51s・max7.45s=**退化せず**, ≤0mmのまま採用)。整合性: n<5ガードとサンプル数が完全一致(誤NULL/誤算出=0)。
- 正本DB・DB Master・対象スクリプトは作業前に `02_DATABASE/_backup_susp_speed_<TS>/` と
  `05_SCRIPTS/_backup_susp_speed_<TS>/` にバックアップ済(2026-06-20)。

### 19c. Workbench UI（`ts24_workbench.py` / `PostureAnalysisTab`）
- 既存4パネル(APEX分析)を内部 `QTabWidget` 第1タブ「📊 APEX分析（基本）」に格納し、第2タブ
  **「⚙️ Damping / Phase」**(`_build_damping_phase_tab`/`_draw_damping_phase`/`_fill_dp_table`)を増設。
- 2×2: ①Hard Brake Front Diving速度 Lap推移(avg実線/peak点線・Rider色分け) ②Corner Exit Rear|v| 散布図
  (X=ラップタイム,Y=ce_r_spd_avg,点サイズ=ce_count) ③PH1-2 Rear@0mm 累積秒 Lap推移 ④数値テーブル
  (新5指標＋`fullbrk_count`/`ce_count` 併記、NaN→"—"、n<5は淡色「参考」)。
- 既存タブ/クリックポップアップ/Circuitフィルタは無改変。Circuitフィルタは共通で両タブに作用。
- **GUIスモークテストはローカル必須**(ヘッドレス不可)。`python3 ts24_workbench.py` で Suspension/Posture →
  Damping/Phase タブ表示確認を Tatsuki が実施。

### 19d. DB Master.xlsx（`build_excel_master.py`）
- `DYNAMICS_ANALYSIS` の DAMPING グループ(per-run集計)を **5→10列**に拡張: Brk F-Dive Avg/Peak,
  CE R-Spd Avg/Peak, PH1-2 Rear@0[s]。グループ見出しspan自動拡張・既存書式(`build_clean_sheet`)踏襲・None=空セル。
- `LAP_SUSPENSION` 生ダンプシート: ヘッダが旧テンプレ `ws.max_column`(34)で頭打ち→ `r_dive_spd` 以降ヘッダ欠落
  だった既存quirkを修正(全LS_COLSをラベル・スタイルは既存ヘッダから複製) + 新5列を追加 → **46列**。9シート構成は維持。

### 19e. 残課題（将来）
- `ce_r_squat_spd_avg/peak`(CE圧縮方向)の追加 / PH1-2をコーナー単位(corner_phase_analysis統合)へ精緻化 /
  ce_r_spd_peak の p95化検討 / Supabase・Streamlit dashboard への展開(今回スコープ外)。
- 新規/変更: `build_master_db.py`(計算+schema+射影), `backfill_susp_zone_speed.py`(新規・ゲート+反映),
  `ts24_workbench.py`(Damping/Phaseタブ), `build_excel_master.py`(DAMPING列+LAP_SUSPENSIONヘッダ修正)。

---

## 20. Multi-Agent Data Quality & Auto Analysis Roadmap — Phase 0-1 着手（2026-06-20 Claude Code 実施 / Tatsuki指示書）

**指示書全文**: Tatsuki 提示の「TS24 Workbench Multi-Agent Data Quality & Auto Analysis Roadmap」。
6エージェント構成(Extraction=測る / Quality Gate=疑う / DB Integration=保存 / Case Search=探す /
Hypothesis=考える / Supervisor=止める) + **Tatsuki=決める**。AIは最終判断者ではなく、生データ品質を
落とさず過去の事実を引き出し、Tatsukiの判断を速く・深くするための補助。今回は最も安全な **Phase 0-1**
(DB品質基盤)から着手。**運用ルール: 全作業は複数エージェントで遂行・CLAUDE.mdに必ず記録・外部AI Codexが
本ファイルで進捗監視**。

### 20a. Phase 0 — 正本DB固定（確定 / 監査2エージェントで実施）
- **正本DB = `02_DATABASE/ts24_unified.db`**（3.9MB / 23テーブル / runs275・laps1202・lap_suspension1202・
  race_results792）。全スクリプト約40本のDB参照を監査 → **全て正本を正しく参照済**（os.path/`__file__`相対/
  `ROOT/SCRIPT_DIR.parent`で構築・ハードコード絶対パス無し・曖昧な相対パス無し）。
- **run_id / lap_id 命名規則（確定・CLAUDE.md権威記載）**:
  - `run_id = {YYYYMMDD}_{ROUND}_{CIRCUIT}_{SESSION}_{RIDER}_{RUN_NO}`
    例 `20250221_ROUND1_PHILLIPISLAND_RACE2_JA52_R1`（CIRCUITはスペース無し正規化・SESSION=QP/SP/RACE1/RACE2等・RUN_NO=R1..）
  - `lap_id = {run_id}_L{LAP_NO}` 例 `..._JA52_R1_L19`
  - 新run/lap生成・JOIN・UPSERTは必ずこの規則に従う（§1c の Supabase 自然キーとも整合）。
- **ts24_master.db は廃止ではなく現役の中間ファイル**: `build_master_db.py`(出力先) → `cutover_db.py`(昇格)の
  ビルドパイプライン用。**削除厳禁**。`ts24_unified.old.db`=cutover前バックアップ。
- **判明した非破壊の残課題（今回は Tatsuki 指示で触らず記録のみ）**:
  - ① ルート直下 `ts24_unified.db`(0B・参照元ゼロの孤児) と `02_DATABASE/ts24_setup.db`(0B) → **削除保留**
    （Tatsuki判断待ち。`_backup_phase0_*`退避→削除でクリーン化可能）。
  - ② `dashboard.py` の `find_db()`→`_load_sqlite()` は**旧スキーマ(sessions/session_tags/lap_times)参照の
    レガシー死コード**。本番はSupabase経由で稼働しfind_dbは通常None(=安全)。新DBに旧テーブルが無いため
    **find_dbを正本へ向ける改修は逆に破壊的**。今回は無改修（残課題）。

### 20b. Phase 1 — 解析ログ・品質ログ基盤（実装完了 / 追加のみ・既存無改変）
- 新規スクリプト **`create_quality_tables.py`**（冪等 / 実行前に `_backup_quality_tables_<TS>/` へ自動バックアップ /
  `CREATE TABLE IF NOT EXISTS`のみ=既存データ無害）で正本DBに **管理5テーブルを追加**:
  | テーブル | 役割 | 主keyの要点 |
  |---|---|---|
  | `source_file_registry` | 検出ソースファイル台帳(MES/LAP/DDD/REPORT/PDF/CSV) | file_id PK・file_path UNIQUE・sha256で変更検出・status(discovered/queued/extracted/archived) |
  | `import_queue` | Quality Gate待ち処理キュー | queue_id・status(pending/processing/awaiting_gate/done/failed/skipped)・priority |
  | `analysis_run_log` | 抽出/解析の実行記録(DB更新の根拠) | analysis_run_id=`{ISO}_{script}`・agent/script_version/rows_*/quality_status/params_json |
  | `data_quality_log` | 品質チェック結果 | check_name・scope/scope_id・observed/expected/tolerance・**result=PASS/WARNING/FAIL** |
  | `metric_version_log` | 指標定義のバージョン管理 | (metric_name,version) UNIQUE・definition/guard_rule/effective_from |
- `metric_version_log` に既存v1指標 **10件をシード**（§18 f_dive_spd系4+rear_light_brk / §19 zone速度5）。
  guard_rule に「n<5→NULL」「相対ダンピング速度指数・一人歩き禁止」等の注意を明記。
- 検証: 5/5テーブル作成・既存データ件数不変(runs275/laps1202/lap_suspension1202/race_results792)を確認。
  バックアップ=`02_DATABASE/_backup_quality_tables_20260620_074105/`。再実行は冪等(INSERT OR IGNORE)。

### 20c. 次フェーズ（未着手 / ロードマップ Phase 2-5）
- Phase 2 Extraction Pipeline: `DATA 2D/`・`01_REPORTS/`・`07_RESULTS/` 新ファイル検出→registry/queue登録→scratch DB。
- Phase 3 Quality Gate: lap数/lap_time物理範囲/PDF best vs 2D best差/決定論/NULL率/zone sample/外れ値/0-NULL意味論 →
  `data_quality_log`へ PASS/WARNING/FAIL記録。**FAILは絶対に正本へ反映しない**。
- Phase 4 DB Integration: PASS のみ run_id/lap_id JOINでUPSERT・NULLで既存上書き禁止・反映後Excel/JSON/Workbench再生成。
- Phase 5 Workbench Auto Diagnosis / Case Search Agent / Hypothesis Agent / Supervisor監査ルール。
- 新規/変更: `create_quality_tables.py`(新規)。CLAUDE.md §20 追記。

---

## 21. 作業ツリー整理・検証・ドキュメント整合（2026-06-20 Claude Code 実施 / Tatsuki指示）

新規機能を停止し、git作業ツリー整理(調査)・Workbench検証・DBレポート・CLAUDE.md旧記述整理を実施。
commit は未実施（Tatsuki確認後に候補作成=指示Step5）。**Supervisor的に「止める」案件を1件検出**（下記21a）。

### 21a. git作業ツリー監査（gitルート=`05_SCRIPTS`, branch=main, origin同期済）
- **重大: services/ domain/ components/ の削除(ステージ済)が dashboard.py と矛盾**。dashboard.py は
  HEAD・index・working tree の**全てでこれらをライブ import**（claude_client/supabase_client/memory_service/
  charts を30-40箇所で呼び出し）。3ディレクトリは**ディスク上も削除済** → working treeの dashboard.py は
  既にローカルで ModuleNotFoundError 状態（origin/mainには残るためStreamlit Cloudは稼働中）。
  **このままcommitするとデプロイ時に本番dashboardが壊れる** → コミット禁止・要方針確認。
- ステージ全体: **61ファイル・+2285/−15424** の大規模で、**中断された未完成リファクタ**。index版dashboard.pyは
  HEAD/worktreeと異なる(nav構成違い=リフォーカスをstage後にworktreeで部分差し戻し)。
- **lap_suspension_data.json = conflict(UU)**: マージ残骸(MERGE_HEAD無し)。working treeは4ラップ/30列/2.6KBの
  stale断片(stage2=692KB/stage3=1174KB/worktree=どちらでもない)。DBが正(1202ラップ46列)。**削除で解決推奨**
  (他dashboard JSONと整合・Workbenchは DB駆動でJSON不要)。ただし未確定→git未mutate。
- **削除分類(暫定)**: ✅意図的=INSTRUCTION_*.md/各種spec/.command/.bat/.sh/旧sync_*.py/create_workbench_tables.py/
  SQL群/tests/docs/password_generator.py/ts24_watcher.py/test_gps_decode.py。⚠️要確認=services/domain/components
  (dashboard依存=矛盾)・dashboard用JSON群・**race_memory.json(知見喪失リスク=要Tatsuki確認)**。
- untracked: §18/§19の新スクリプト群(build_master_db.py/cutover_db.py/sync_to_supabase.py/apply_pdf_positions_v2.py/
  audit_db_dump.py/backfill_susp_zone_speed.py/build_excel_master.py/import_*/pdf_*/reports/ 等)+本作業の
  create_quality_tables.py。これらは add候補だが §18系は dashboard 依存と切り離して扱う必要。

### 21b. Workbench GUIスモークテスト（offscreen / Python+PyQt6 6.10.0 / pyqtgraph 0.13.7）
- 絶対パス起動(実起動同条件)で**全合格**: module import / MainWindow構築 / PostureAnalysisTab.refresh /
  内部タブ`['📊 APEX分析（基本）','⚙️ Damping / Phase']`存在 / DB 1202ラップ読込(circuit列有) /
  Circuitコンボ8件(全サーキット/ARAGON/ASSEN/BALATON/JEREZ/MOST/...) / フィルタ ARAGON→ASSEN→リセットの
  再描画が無例外。**チャートの見た目の目視のみ Tatsuki がローカル実施**(ヘッドレス不可)。
- 注: relative-importロード時のみ `SCRIPT_DIR=Path(__file__).parent` が相対化しDB空読みになる人工物を確認。
  実起動(`python3 ts24_workbench.py`, Python3.9+で__file__絶対)では正常。実害なし。

### 21c. DB状態レポート（lap_suspension 新5指標 / 正本DB）— §19bと完全一致=健全
- NULL率: brk_f_dive_spd_avg/peak=**10.8%**(130/1202) / ce_r_spd_avg/peak=**45.0%**(541/1202, CE無しラップ多数) /
  ph12_rear0_s=**0.3%**(4/1202)。
- **n<5ガード違反=0件**（全4指標で NOT NULL かつ count<5 のラップ=ゼロ。誤算出なし）。
- ph12_rear0_s分布: 非NULL1198 / >0が958 / =0が240 / min0.0・mean0.511・max7.449秒（退化なし）。
- ce_r_spd_peak: max=3479.1 / p95=812.1 / **max/p95=4.28x**（少数ラップで突出 → §19e のp95化候補。一人歩き注意）。

### 21d. CLAUDE.md 旧記述整理（削除せずアノテーション=可逆 / §19・§20を正）
- 冒頭に **§0「最新の正（READ FIRST）」バナー**新設: §2-§17は旧アーキ、§18/§19/§20が正。正本DB/データフロー/
  dashboard用JSON/race_memory.json/件数 の新旧対応表。
- インライン【旧情報】マーカー: §3(ts24_setup.db/all_sessions.json)・§4.2(JSON群はgit削除済・件数旧)・
  §7b(race_memory.jsonは削除ステージ済=要確認)。

### 21e. Tatsuki方針確定 → 実行（2026-06-20）
**方針(Tatsuki)**: ①services/domain/components は**復元・保持**(dashboard live import中、完全書換まで削除禁止)。
②race_memory.json **削除しない**(将来DB化候補、設計確定まで保持)。③lap_suspension_data.json conflict は
**削除で解決しない**(dashboard参照残)。DB由来46列JSON再生成が最優先だが**未実装**のため、**HEAD版復元+conflict解消**、
CLAUDE.mdに stale/deprecated・WorkbenchはDB優先を明記。④dashboard用JSON群の削除は**今回commitに含めない**
(refocus/Supabase完全移行の別PR完了後に判断)。⑤commitは A/B/C/D に**分割**、cleanup削除は未commit。

**実行内容**:
- 復元(`git checkout HEAD --`): services/ domain/ components/ race_memory.json + dashboard用JSON5本
  (lap_suspension_data 692KB / dynamics_data / lap_overlay_data / lap_times_data / corner_phase_data)。
  **lap_suspension_data.json の conflict(UU)は HEAD版で解消**。
- dashboard.py: ステージのrefocus差分をunstage→ working tree は**HEAD一致(クリーン)**に復帰。dashboard変更は別PRへ先送り。
- cleanup系削除(INSTRUCTION_*.md/spec/.command/.bat/.sh/.sql/旧sync_*.py/tests/docs/create_workbench_tables.py/
  password_generator.py/ts24_watcher.py/test_gps_decode.py 等)は**unstageのまま=未commit**(将来別commit)。
- CLAUDE.md の §0/§4.2/§7b アノテーションを最終決定に合わせ更新(削除済→保持/deprecated)。

### 21f. コミット分割（branch `db-rebuild-quality-20260620` / 未push＝候補）
- **A. DB再構築・build系(§18)**: build_master_db.py / cutover_db.py / build_excel_master.py / export_master_to_excel.py /
  apply_pdf_positions_v2.py / audit_db_dump.py / sync_to_supabase.py / import_all_race_results.py / import_company_bsb.py /
  parse_bsb_result_pdf.py / pdf_chrono_extractor.py / pdf_result_extractor_v2.py / reconcile_2d_vs_original.py / reports/ +
  (M)build_unified_db.py / corner_phase_analysis.py / extract_turn_templates.py / lap_overlay_extractor.py /
  lap_suspension_stats.py / update_trend_analysis.py。**注**: build_master_db.py/build_excel_master.py には§19の
  ゾーン速度計算・DAMPING列も内包(新規ファイルのため分離不可、Aに含める)。
- **B. ゾーン限定サス速度 + Workbench Damping/Phase(§19)**: backfill_susp_zone_speed.py + (M)ts24_workbench.py。
- **C. 品質ログ基盤(§20)**: create_quality_tables.py。
- **D. CLAUDE.mdドキュメント更新**: CLAUDE.md (+ _CLAUDE_INDEX.md)。
- **未commit(意図的)**: cleanup削除全件 / dashboard.py(=HEAD) / 作業メモmd(CLAUDE_CODE_INSTRUCTIONS_*/CODE_INSTRUCTION_*/
  CODEX_*/TRN_*/DB_REBUILD_SPEC_v1.0.md) / parse_chrono_pdf_DRAFT.py・parse_race_pdf.py(draft) / _backup_susp_speed_*/。
- pushはTatsukiがレビューしてからCLIで実施(自動pushしない)。

---

## 22. Phase 2 Extraction Pipeline 設計書 作成（2026-06-20 / 設計のみ）

`db-rebuild-quality-20260620` の4コミットは受け入れ確定（PR#1 で main=`626abdf` にマージ済）。
受入検証: origin同期OK / 4コミットで dashboard.py 不変 / 未追跡ファイル混入なし。

次フェーズは**実装ではなく設計**から。**設計書 = `reports/phase2_extraction_pipeline_design_20260620.md`**。
- 思想:「自動で入れる」より先に「自動で疑う」。Phase 2 が自動化するのは**検出・隔離・疑いの記録まで**で、
  **正本DBには一切書かない**（書くのは管理4テーブル + scratch DB のみ）。正本反映は Phase3 Gate PASS + Tatsuki承認後。
- 収録: 監視対象(DATA 2D/01_REPORTS/07_RESULTS) / ファイル種別検出ルール(2D tier=nested/copia/loose、
  拡張子なしPDFは`%PDF`マジック判定必須) / source_file_registry運用(sha256で更新検出・冪等) /
  import_queue状態機械(pending→processing→awaiting_gate→done/failed/skipped、done はPhase4承認後のみ) /
  scratch DB生成(`/tmp`隔離・正本は読取のみ・決定論ゲートで既存値保護) / Gate単位(2D=outing/report=file/pdf=session) /
  FAIL時の扱い(正本到達禁止・隔離・data_quality_log記録・Workbench表示) / Workbench「未処理データ」タブ / 既存実装の再利用方針 /
  未決事項(Tatsuki確認6点)。
- 実態調査: 複数エージェントで DATA 2D(nested/copia/loose・HED矛盾ゲート)・01_REPORTS(YYYYMMDD-ROUNDx-RIDER.xlsx)・
  07_RESULTS(リザルト/クロノPDF・**拡張子なしPDF実在**)と既存抽出ロジック(discover_outings/report_importer/
  pdf_result_extractor_v2/受入ゲート§8)を確認し、設計を実装と矛盾しないよう整合。
- ブランチ: `phase2-extraction-design-20260620`(main基底・未push)。実装着手は Tatsuki 承認後。
- **rev.2（2026-06-20 Tatsuki承認＋7点修正）**: ①「正本DBに書かない」→**「業務テーブルに書かない／管理テーブルは許可」**
  と用語修正(§0.1で business/management を明示) ②Phase 2を **2A**(scan→registry→queue→Workbench表示のみ)/
  **2B**(scratch生成→awaiting_gate)に分割 ③2D outing の同一性は代表DDD単体でなく **manifest hash**
  (DDD/LAP/HED/主要ファイルの正規化連結hash) ④**半端コピー対策**(size/mtime安定確認・`~$`/`.tmp`/`.partial`/
  `.icloud`/`._`等除外) ⑤status に **incomplete/gated/unknown** を明示 ⑥`data_quality_log.check_name` を
  **`detect_*`(Phase2検出)/`gate_*`(Phase3正式Gate)** で分離 ⑦scratch は **FAIL時のみ短期保存**(/tmp・既定72h)。
  → **Phase 2A から実装開始。Phase 2B以降の正本業務テーブル反映は引き続き禁止。**

---

## 23. DB Master Report Helper / Similar Cases ビュー追加（2026-06-21 Codex 実施）

**目的:** `TS24 DB Master.xlsx` を単なるDB出力ではなく、イベント後Reportの Weekend Summary と過去事例比較に
使える上位ビューへ拡張する。生データ品質を落とさないため、既存の raw/data シート
(`LAP_SUSPENSION` / `DYNAMICS_ANALYSIS` 等)は根拠データとして保持し、DB由来の新規ビューを追加する方針。

### 23a. 実装内容（`build_excel_master.py`）
- 新規ビュー生成ヘルパーを追加:
  - `reset_sheet()` / `apply_table_style()` / `write_note()` / `top_items()` / `compact_text()`
- `TS24 DB Master.xlsx` に以下3シートを追加生成:
  | シート | 役割 | 行数(検証時) |
  |---|---|---:|
  | `WEEKEND_SUMMARY_HELPER` | Report Weekend Summary用。Round/Circuit/Rider別にBest Lap、問題タグ、代表コメント、サス指標、セット変更、貼り付け用Draftを集約 | 36 |
  | `SIMILAR_CASES` | 過去事例検索用。`run_tags` + `problem_log` + 2D根拠指標 + `setup_decision_log`を結合し、Confidence(HIGH/MED/LOW)を付与 | 86 |
  | `SETUP_EFFECTS` | セット変更と結果の一覧。`setup_decision_log`をReport根拠として読みやすく整理 | 7 |
- `SIMILAR_CASES` のConfidence方針:
  - `HIGH`: 同一(circuit,rider,problem_tag)事例数>=3、2D根拠あり、POSITIVE結果あり
  - `MED`: 事例数>=2、2D根拠あり
  - `LOW`: 上記未満。**断定的なセット提案に使用禁止**
- `WEEKEND_SUMMARY_HELPER` のDraft文は比較参考用。AIが最終判断を行う文言ではなく、
  「Use as comparison evidence, not an automatic setup decision.」を明記。

### 23b. 実行・検証結果
- 既存 `TS24 DB Master.xlsx` は作業前に
  `02_DATABASE/TS24 DB Master.pre_report_helper_20260621.xlsx` としてバックアップ。
- `PYTHONPYCACHEPREFIX=/tmp/ts24_pycache python3 -m py_compile build_excel_master.py` → PASS
  （通常 `py_compile` は macOS Python cache 権限で失敗するため `/tmp` cache を使用）
- `python3 build_excel_master.py` → PASS
- 生成後シート構成:
  `DB_LOG`, `WEEKEND_SUMMARY_HELPER`, `SIMILAR_CASES`, `SETUP_EFFECTS`, `TREND_ANALYSIS`,
  `SOLUTION_SEARCH`, `PROBLEM_LIBRARY`, `PERFORMANCE_CORRELATION`, `LAP_TIMES`, `RUN_LOG`,
  `DYNAMICS_ANALYSIS`, `LAP_SUSPENSION`
- 既存主要シート維持確認:
  - `DYNAMICS_ANALYSIS`: 160行 / 33列
  - `LAP_SUSPENSION`: 1204行 / 46列
  - `RUN_LOG`: 275 rows generated
  - `LAP_TIMES`: 1202 rows generated

### 23c. 注意・次課題
- 今回はExcel上位ビュー追加のみ。正本DB `02_DATABASE/ts24_unified.db` の業務データは変更していない。
- `TREND_ANALYSIS` / `SOLUTION_SEARCH` は引き続き保持シート。完全なDB由来再生成は次段階。
- `problem_log` / `setup_decision_log` はまだ件数が少ないため、現時点の `SIMILAR_CASES` は
  「Report比較参考」と「仮説候補」用途に限定する。

### 23d. 追記（2026-06-21 Codex）— Weekend Summary Helper 使用方法 / Setup effect 自動反映方針
- `WEEKEND_SUMMARY_HELPER` の上部説明欄(A2)に英語の使用方法を追記:
  1) target weekendをRound/Circuit/Riderでfilter
  2) Best Lap / Race Pos / Problem Tags / Representative Comment / Key Suspension Signalsを確認
  3) `SIMILAR_CASES` / `SETUP_EFFECTS` で根拠を開く
  4) Weekend Summary DraftはReport wording materialのみ（automatic setup decisionではない）
  5) blank cellは0ではなく「信頼できるDB値なし」
- `TS24 DB Master.xlsx` は再生成済み。`WEEKEND_SUMMARY_HELPER` 40行/15列、説明文反映を確認。
- Workbenchで記入したSetup effectは正本DBの `setup_decision_log` が源泉。
  `SETUP_EFFECTS` シートは `build_excel_master.py` 実行時に `setup_decision_log` から再生成される。
- 定期自動反映の最小リスク設計:
  - Workbenchは引き続きDBへ保存するだけ（Excelを直接編集しない）
  - `build_excel_master.py` を定期実行して `TS24 DB Master.xlsx` を再生成
  - Excelが開いている場合は保存失敗/競合の可能性があるため、ロック検知・バックアップ・ログ出力付きの
    小さな wrapper script + macOS LaunchAgent で運用するのが安全
  - 正本DBの業務データには書かない。Excelは常にDBからの派生物として扱う

---

## 24. Phase 2A Extraction Pipeline 実装（2026-06-21 Claude Code 実施）

設計書 §22 / `reports/phase2_extraction_pipeline_design_20260620.md` rev.2 に基づき **Phase 2A のみ**実装。
**業務テーブルには一切書かない**（書込は管理テーブル `source_file_registry`/`import_queue`/`data_quality_log`/
`analysis_run_log` のみ）。抽出・scratch・Gate は 2B 以降（未実装）。コミット `f25cae4`（branch `phase2a-extraction-20260620`）。

### 24a. scanner `extraction_scan.py`（新規）
- DATA 2D / 01_REPORTS / 07_RESULTS を scan → 検出 → registry 登録 → `discovered` を queue(pending) 投入 →
  検出チェックを `data_quality_log` に `detect_*` で記録 → `analysis_run_log` に1 run。冪等。
- 2D は既存 `build_master_db.py` の `discover_events/discover_outings/event_circuit/_hed_meta` を再利用（作り直さない）。
- **iCloud対策（重要）**: manifest を meta full-sha256 にすると iCloud データレス（未DL）ファイルのDL待ちで
  1イベント80秒ハング。**検出は中身を読まない stat ベース**（manifest=`name|size`、report/pdf=size由来、
  mtime は iCloud jitter のため除外）に統一 → 全 scan 約3秒。full hash は `--deep-hash` 任意。「2A=抽出しない」原則とも整合。
- 半端コピー対策: `~$`/`.tmp`/`.partial`/`.icloud`/`._` 除外、mtime経過秒で安定性判定（既定10s、不安定=incomplete保留）。
- status: `discovered/queued/incomplete/gated/unknown`。同一 event/base が複数物理パス（`_Copy`/サブフォルダ）の場合
  両方を別行登録し `detect_duplicate_base` で疑い記録。HED↔eventサーキット矛盾(copia/loose)は `gated`。
- **検証**: 検出366（2D 280/report 28/pdf 58）→ registry queued358/gated1/incomplete7、queue pending358、
  data_quality_log: detect_duplicate_base 64/detect_hed_circuit_mismatch 1/detect_incomplete 7。
  業務テーブル**完全不変**(runs275/laps1202/lap_suspension1202/race_results792)。再実行冪等(更新0/queue0)。
  gated 1件=`20251010-ROUND11-JA52/D2-AM-JA3-04`(HED=PORTIMAO≠event=ESTORIL)=既知 Portimão 誤配置を自動隔離。

### 24b. Workbench `ts24_workbench.py`「📥 Import / Quality」タブ（読み取り専用）
- `ImportQualityTab` 新設（MainWindow 第7タブ・DBウォッチャ自動refresh対象）。3サブタブ:
  ①未処理キュー ②要確認(incomplete/gated/unknown 色分け) ③検出チェック(detect_*/最新run)。管理テーブルのみ参照。
- **実機GUI目視合格**: 7タブ、キュー358行、要確認8行(gated赤+incomplete黄)、検出チェック72行。既存タブ無破壊。

### 24c. 未実装（次段階・要Tatsuki承認）
- Phase 2B(queue→scratch→awaiting_gate)、Phase 3 Gate(`gate_*`)、Phase 4 業務テーブル反映(承認後)。
- 変更: `extraction_scan.py`(新規)/`ts24_workbench.py`(Importタブ)。※build_excel_master.py / §23 は Codex 作業のため本記録の対象外。

---

## 25. 状態確認・整理 + Supabase Audit 設計（2026-06-21 Claude Code 実施 / Tatsuki指示）

Phase 2B には進まず、状態確認・整理と次作業候補の設計に限定。

### 25a. 状態確認
- branch `phase2a-extraction-20260620` / HEAD `f25cae4`。
- 管理テーブル: registry(queued358/gated1/incomplete7) / queue(pending358) / data_quality_log 72 / analysis_run_log success1。
- **業務テーブル不変を再確認**: runs275 / laps1202 / lap_suspension1202 / race_results792。
- Codex 作業分の未コミット変更を確認: `build_excel_master.py`(+336) と `CLAUDE.md §23`(DB Master Report Helper /
  WEEKEND_SUMMARY_HELPER / SIMILAR_CASES / SETUP_EFFECTS)。**Phase 2A 本体(f25cae4)とは別コミット候補**として扱い、
  Claude Code は触れない(未コミットのまま保持)。`TS24 DB Master.xlsx` は派生物=正本扱いしない。

### 25b. Supabase Audit 設計（設計のみ・未実装）
- 設計書 = `reports/supabase_audit_design_20260621.md`。コミット `5a9f9f9`。
- 目的: local `ts24_unified.db` と Supabase の **件数・自然キー差分を read-only 比較** → remote extra / missing 抽出 →
  **cleanup SQL 案を生成**（手動実行用）。**自動削除・自動 sync なし**。
- 鉄則: local は SELECT のみ / remote は GET のみ / 書込はローカル `.md`+`.sql` のみ。差分は提示し判断は Tatsuki。
- 対象4テーブル(race_results/lap_times/sessions_2d/lap_times_2d)＋自然キー(§1c)。**local 投影は `sync_to_supabase.py`
  と同一ロジック再利用**(生テーブル直比較は偽差分→禁止)。NULLS NOT DISTINCT / `date` キーを正規化。
  cleanup_proposal.sql は `IS NOT DISTINCT FROM` で DELETE 案を生成(SELECT確認→手動実行を強制)。

### 25c. 未開始（Tatsuki承認後）
- Phase 2B / Gate / 正本業務テーブル反映は引き続き未開始。
- Supabase Audit は設計のみ。実装は承認後。
- 新規/変更（本作業・私の分のみ）: `reports/supabase_audit_design_20260621.md`(新規・commit 5a9f9f9)。
  ※CLAUDE.md §23 と build_excel_master.py は Codex 作業のため本コミットに含めない。

---

## 26. DB Master Report Helper 変更コミット（2026-06-21 Codex 実施）

Tatsuki指示により、§23 の `DB Master Report Helper / Similar Cases` 変更を Phase 2A 本体とは別コミット対象として整理。

### 26a. コミット対象
- `build_excel_master.py`
  - `WEEKEND_SUMMARY_HELPER` / `SIMILAR_CASES` / `SETUP_EFFECTS` 生成を追加。
  - `WEEKEND_SUMMARY_HELPER` A2 に英語の使用方法を表示。
  - `SETUP_EFFECTS` は Workbench が保存する `setup_decision_log` を源泉として再生成。
- `CLAUDE.md`
  - §23 追記（実装内容・検証結果・運用注意）
  - §26 追記（本コミット整理）

### 26b. 検証
- `PYTHONPYCACHEPREFIX=/tmp/ts24_pycache python3 -m py_compile build_excel_master.py` → PASS
- `python3 build_excel_master.py` → PASS（§23実施時）
- 生成済み `TS24 DB Master.xlsx` の追加シート確認:
  - `WEEKEND_SUMMARY_HELPER`: 40行 / 15列
  - `SIMILAR_CASES`: 90行 / 20列
  - `SETUP_EFFECTS`: 11行 / 18列
- 正本DB `ts24_unified.db` の業務データは変更していない。ExcelはDB派生物として扱う。

### 26c. 次作業方針
- Phase 2B へ進む前に、Supabase Audit 実装（read-only diff / cleanup SQL案生成 / 自動削除禁止）を優先候補とする。
- その後、Workbenchの `Setup Decision` → `setup_decision_log` → `TS24 DB Master.xlsx` 定期再生成を、
  ロック検知・バックアップ・ログ付き wrapper + LaunchAgent として設計/実装する。

---

## 27. Obsidian LLM Wiki 運用骨格（2026-06-21 Codex 実施）

添付資料「LLM Wiki」パターンをTS24向けに再設計し、Obsidianで使えるMarkdown Vault骨格を作成。

### 27a. 作成場所

```text
08_OBSIDIAN/TS24_Engineering_Knowledge/
```

### 27b. 役割分担（確定）

| 層 | 役割 |
|---|---|
| `02_DATABASE/ts24_unified.db` | 正本DB。telemetry/setup/抽出指標のsource of truth |
| `TS24 DB Master.xlsx` | DB派生のReport/helper出力 |
| Workbench | 入力・分析UI |
| Supabase | cloud mirror。正本ではない |
| Obsidian | 判断・設計・AI handoff・監査要約・人間可読のknowledge case |
| `CLAUDE.md` | coding agent必読の最新ルール。Obsidianで置換しない |

### 27c. 作成した主要ファイル

- `README.md`
- `PROJECT_RULES.md`
- `CURRENT_STATE.md`
- `index.md`
- `log.md`
- `03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
- `04_SYSTEM_DESIGN/TS24_LLM_WIKI_OPERATING_MANUAL.md`
- `05_DB_AUDIT/DB_INVENTORY.md`
- `90_TEMPLATES/AI_HANDOFF_TEMPLATE.md`
- `90_TEMPLATES/DECISION_RECORD_TEMPLATE.md`
- `90_TEMPLATES/DB_INVENTORY_TEMPLATE.md`
- `90_TEMPLATES/SUPABASE_AUDIT_NOTE_TEMPLATE.md`
- `90_TEMPLATES/KNOWLEDGE_CASE_TEMPLATE.md`
- `90_TEMPLATES/WORKBENCH_CHANGELOG_TEMPLATE.md`

### 27d. 運用ルール

- ObsidianはDB値の正本ではない。数値判断は必ず `ts24_unified.db` / source file / commit / generated outputに戻る。
- AI handoff開始時は `CLAUDE.md` → `CURRENT_STATE.md` → `AI_HANDOFF_LATEST.md` を読む。
- Obsidian noteには可能な限り `run_id` / `lap_id` / `problem_id` / `decision_id` / commit hash / file path を記載。
- LOW confidence のknowledge caseを断定的なsetup提案に使わない。
- Obsidianは「AIチームの作戦室」。SQLiteは「事実の正本」。

### 27d-2. Codex Obsidian運用権限（2026-06-22 Tatsuki承認）

Tatsuki方針により、CodexはObsidian内で実際に活動し、TS24の運用レイヤーを維持してよい。
ただしObsidianは正本DBではなく、DB管理は以下の安全ワークフローに限定する。

```text
Observe -> Audit -> Document -> Propose -> Wait for approval -> Implement if approved
```

Codexが追加承認なしで実施してよいこと:

- Obsidianのhandoff / decision / index / log / DB inventory / audit note更新
- `ts24_unified.db` の読み取り監査
- スクリプト・レポート・Excel派生出力の読み取り確認
- audit report / cleanup proposal SQL の生成

明示承認が必要なこと:

- `ts24_unified.db` のcanonical business table書き込み
- DB行削除
- Supabase cleanup実行
- Phase 2B canonical integration開始
- metric definition変更
- dashboard JSON / derived data置換

関連Obsidian decision:

- `08_OBSIDIAN/TS24_Engineering_Knowledge/02_DECISIONS/2026-06-21_Obsidian_is_not_canonical.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/02_DECISIONS/2026-06-22_Codex_operates_via_Obsidian.md`

### 27e. PDF理論資料のObsidian取り込み（2026-06-22 Codex準備）

UWTSD / motorcycle dynamics系PDFは理論参照としてObsidianへ保存する。ただしPDF previewの一時パス
(`/var/folders/.../remote-file-preview-*`) は消えるため、抽出前に必ずVault内の安定フォルダへ置くこと。

安定保存先:

```text
08_OBSIDIAN/TS24_Engineering_Knowledge/10_RAW_SOURCE_NOTES/PDF_SOURCES/
```

追加済み:

- `10_RAW_SOURCE_NOTES/PDF_SOURCES/PDF_INGESTION_STATUS.md`
- `11_ENGINEERING_KNOWLEDGE/Motorcycle_Dynamics_Index.md`
- `11_ENGINEERING_KNOWLEDGE/Motorcycle_Dynamics_Source_Summary.md`
- `11_ENGINEERING_KNOWLEDGE/Suspension_Damping.md`
- `11_ENGINEERING_KNOWLEDGE/Suspension_Mathematics.md`
- `11_ENGINEERING_KNOWLEDGE/Chassis_Geometry_Fundamentals.md`
- `11_ENGINEERING_KNOWLEDGE/Limited_Acceleration_and_Cornering.md`
- `11_ENGINEERING_KNOWLEDGE/Tyre_Fundamentals.md`
- `11_ENGINEERING_KNOWLEDGE/TwoD_Analyzer_CalcTool_Workflow.md`
- `11_ENGINEERING_KNOWLEDGE/Setup_Reference_Source_Index.md`

PDFコピー済み:

- `Week 1.1 - Module Introduction.pdf`
- `Week 1.3 - Limited Accelerations & Basic Cornering.pdf`
- `Week 1.4 - Understanding Suspension Design.pdf`
- `Week 1.6 - Suspension & Mathematics.pdf`
- `Trackday Guide to Suspension Setup.pdf`
- `FKR-1xx-setting-library-version-1.0.pdf`
- `2025_JA52_AllSetUP.pdf`
- `AC-DOC_Analyzer_e-000.pdf`
- `AC-DOC_CalcTool.pdf`
- `AC-DOC_2D_GPSTracks.pdf`

未発見:

- `Week 1.5 - Suspension & Damping.pdf`
- `Motorcycle Dynamics 2019.pdf`

今後の追加候補:

- 未発見の `Week 1.5 - Suspension & Damping.pdf` が見つかったら `Suspension_Damping.md` を追補する。
- 未発見の `Motorcycle Dynamics 2019.pdf` が見つかったら `Motorcycle_Dynamics_Source_Summary.md` と関連ノートを追補する。

ルール:

- PDF原文を丸ごと転載しない。要約・概念・式・TS24での使い方に整理する。
- theory/referenceとして扱い、`ts24_unified.db` の実測値・Workbench記録・quality gate結果を上書きしない。
- source noteにはPDFファイル名、取り込み日、要約範囲を明記する。

---

## 28. Supabase Audit 実装（read-only）— 2026-06-22 Claude Code 実施

§25b の設計（`reports/supabase_audit_design_20260621.md`）に基づき `supabase_audit.py` を実装。
**read-only 監査のみ**：local は SELECT（SQLite を `mode=ro` URI で接続）、remote は HTTP GET のみ。
POST/PUT/PATCH/DELETE/upsert/sync を一切持たず、canonical DB / Supabase / Excel / JSON は不変。

### 28a. 新規ファイル（3点）
- `supabase_audit.py` — 監査本体（GET のみ・削除しない）
- `reports/supabase_audit_20260622.md` — 監査レポート
- `reports/cleanup_proposal_20260622.sql` — remote_extra の DELETE 案（**提案のみ・実行禁止**）

### 28b. 設計の要点
- 対象4テーブルと自然キーは §1c に準拠（race_results / lap_times / sessions_2d / lap_times_2d）。
- local 投影は `sync_to_supabase.py` と同一ロジック（源テーブル・別名・WHERE）を `AUDIT_SPECS` に複製。
  `sync_to_supabase.py` は import するとモジュール実行で実 upsert(POST) が走るため **import しない**
  （sync 側の投影 SELECT を変えたら `AUDIT_SPECS` も更新すること）。
- NULLS NOT DISTINCT を Python tuple の None 等価で再現。`date` は**比較時のみ**数字8桁へ正規化
  （local `20250221` vs Supabase `2025-02-21` の偽差分回避）。**cleanup SQL は remote の原値**を使用。
- 終了コード: 0=差分なし / 2=差分あり / 1=エラー。

### 28c. 監査結果（2026-06-22 read-only 実行）
| table | local | remote | remote_extra | missing |
|---|---:|---:|---:|---:|
| race_results | 792 | 792 | 0 | 0 |
| lap_times | 7613 | 7613 | 0 | 0 |
| sessions_2d | 246 | 259 | 13 | 0 |
| lap_times_2d | 1202 | 1213 | 11 | 0 |

- **missing は全テーブル 0**（local 正本は完全に Supabase へ反映済み）。
- **remote_extra 計24件**（Supabase のみに存在＝online 残骸。sessions_2d=JEREZ TEST1 等で round 空・date NULL の行を含む、lap_times_2d=lap_no=1 アウトラップ等）。
- cleanup SQL は提案のみ。SELECT で確認後 Tatsuki が Supabase 上で手動実行する（**自動削除・自動 sync しない**）。
- canonical business table 不変を確認（runs275 / laps1202 / lap_suspension1202 / race_results792）。

### 28d. スコープ外（未実施）
- Supabase cleanup の実行・自動 sync・Supabase スキーマ変更。
- **Phase 2B / Gate / canonical integration は未開始**（引き続き Tatsuki 承認制）。
- 新規/変更: `supabase_audit.py`（新規）, `reports/supabase_audit_20260622.md`, `reports/cleanup_proposal_20260622.sql`, CLAUDE.md §28。

---

## 29. DB Master 安全再生成ラッパー（2026-06-22 Claude Code 実施）

Workbench で記録した `setup_decision_log`（→ `SETUP_EFFECTS`）等を `TS24 DB Master.xlsx` へ反映するため、
`build_excel_master.py` を**安全に**呼ぶラッパー `refresh_db_master_safe.py` を新規実装。
`TS24 DB Master.xlsx` は DB 由来の派生物（正本ではない）。正本DB業務テーブルには書き込まない。

### 29a. `refresh_db_master_safe.py` の安全策
- 事前チェック: `ts24_unified.db` / `build_excel_master.py` / `TS24 DB Master Back UP.xlsx`(テンプレ) の存在。
- **Excel オープン検出**: `~$TS24 DB Master.xlsx` ロックファイル + `lsof`。掴まれていれば exit 2 で中止
  （`lsof` 不在環境は検出スキップ→保存失敗時に build の exit code で判別）。
- **バックアップ**: 既存 xlsx を `02_DATABASE/backups/TS24_DB_Master.pre_refresh_<ts>.xlsx` へ退避。
- **ログ**: `05_SCRIPTS/reports/db_master_refresh_<ts>.log` に全手順。
- **exit code 伝播**: `build_excel_master.py` 失敗時はその終了コードを返す。
- **事後検証**: 生成物の mtime 更新 / サイズ>0 / 主要6シート存在
  (`WEEKEND_SUMMARY_HELPER` `SIMILAR_CASES` `SETUP_EFFECTS` `RUN_LOG` `DYNAMICS_ANALYSIS` `LAP_SUSPENSION`)、
  および**正本DB件数の不変**(read-only `mode=ro` で before/after 照合)。
- 終了コード: 0=成功 / 1=事前チェック失敗 / 2=Excel使用中 / 3=事後検証失敗 / 他=build の exit code。

### 29b. 検証（2026-06-22 実行）
- `py_compile` PASS。`python3 refresh_db_master_safe.py` を1回実行 → exit 0。
- xlsx 再生成（mtime 更新・主要6シート存在）、バックアップ＋ログ生成を確認。
- 正本DB件数 不変（runs275 / laps1202 / lap_suspension1202 / race_results792）。
- Excel オープン中の中止も確認（`~$` ロック作成→ exit 2 → ロック撤去）。

### 29c. スコープ外（今回未実施・禁止遵守）
- Workbench UI 変更・LaunchAgent・自動定期実行は**作らない**（手動実行ラッパーのみ）。
- 正本DB業務テーブル書込・Supabase cleanup/sync・Phase 2B・origin push は**しない**。
- `02_DATABASE/`（xlsx・backups・DB）は `05_SCRIPTS` git リポジトリ外のため commit 非対象。
- 新規: `refresh_db_master_safe.py`。生成物（backups/*.xlsx, reports/*.log）は実行時アーティファクトで commit しない。

---

## 30. Result PDF 抽出精度監査（read-only）— 2026-06-23 Claude Code 実施

Workbench `Race Analysis` のラップデータ精度が低い件（ROUND3/RACE1 で #77 が空欄）を read-only 監査。
新規 `audit_pdf_lap_extraction.py`（SQLite `mode=ro` / DB 書込なし / PDF は `pdf_result_extractor_v2.extract_pdf()`
のみ・`write_to_db()` 不使用）。出力 `reports/pdf_lap_extraction_audit_20260623.md`。**正本DB等は一切無変更**。

### 30a. 根本原因（コード監査・確定）
- Workbench `RaceAnalysisTab` は **`pdf_lap_times` のみ参照**。ライダー一覧も
  `SELECT DISTINCT rider_num FROM pdf_lap_times`（`ts24_workbench.py` L4983-4987）→ 行が無いライダーは**選択肢に出ず空欄**。
- `pdf_result_extractor_v2.write_to_db()` はラップ明細を **`pdf_lap_times_v2`** に書く設計（L461/L504）だが、
  正本DBに `pdf_lap_times_v2` は **存在しない**（v2 の `--laps --write` は正本へ未実行）。
- `apply_pdf_positions_v2.py` は `race_results` の position/best_lap のみ UPSERT。**ラップ明細は更新しない**
  → race_results=v2反映済 / pdf_lap_times=旧抽出（不完全）の不一致。

### 30b. 監査結果（`--all` / 46 セッション）
- race_results にあって pdf_lap_times に無い **team rider(#77/#52) 欠落 = 27 セッション**、field 欠落計 **480**。
- lap 数不一致（pdf valid≠race_results.laps・共通ライダー）**258 件**、best_lap 乖離(>0.5s)**41 件**。
- 具体例 ROUND3/RACE1/#77: race_results=`D.AEGERTER pos6 18laps best97.35`、**pdf_lap_times=0 行**。
  v2 再パース=**18 laps / valid17 / best 97.350**（race_results と一致）→ v2 で取得可能、未反映なだけ。

### 30c. 推奨次作業（いずれも要 Tatsuki 承認・本監査では未実施）
1. **v2 を scratch table 化 + Gate**（推奨）: 全 RACE/QP 等を `--all-riders --laps` 抽出 → `/tmp`/scratch の
   `pdf_lap_times_v2` へ → `race_results.laps`/`best_lap_s` と突合 Gate（PASS のみ採用）。
2. **Workbench を検証済みテーブル参照に切替**（Gate 通過後・UI 変更は別タスク・要承認）。
3. 旧 `pdf_lap_times` の直接修正は非推奨（出所不明・上書きより Gate 付き再構築が安全）。

### 30d. スコープ外（禁止遵守）
- pdf_lap_times / race_results の書込・削除なし、v2 結果の正本流し込みなし、Workbench 参照先変更なし、
  Supabase cleanup/sync なし、Phase 2B 未着手、origin push なし。
- 新規: `audit_pdf_lap_extraction.py` / `reports/pdf_lap_extraction_audit_20260623.md`。

---

## 31. Result PDF v2 統合設計（P0 / 設計 + read-only 試験）— 2026-06-25 Claude Code 実施

§30 の監査を受け、Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-25）の P0 タスクとして、v2 ラップ明細を
**安全に統合する設計**と read-only 試験を実施。**正本DB書込・Workbench 参照先変更・Phase 2B・origin push なし**。
設計書 = `reports/pdf_v2_integration_design_20260625.md` / Obsidian `05_DB_AUDIT/2026-06-25_pdf_v2_integration_design.md`。

### 31a. read-only 試験（ROUND3/RACE1・新証拠）
- 旧 `pdf_lap_times` は本セッションで全ライダー 8/10/14 laps に切断（18周レース）。#77=0行、#52=8行/best97.823（誤）。
- v2 `--all-riders --dry-run`: 完走勢ほぼ全員 18 laps、best_lap は `race_results` と**完全一致**（#52→97.457 正）。
- **唯一の不一致=カバレッジ**: `race_results` の **#73(18laps/best99.252) を v2 が取りこぼし**（chrono ヘッダ正規表現の漏れ）。
  → 「v2 無条件採用」は不可。**`race_results` を真値基準にした Gate（特にカバレッジ照合 G1）が必須**。

### 31b. スキーマ・ギャップ（最重要）
- `RaceAnalysisTab` は `pdf_lap_times` の `is_outlap`/`is_pit`/`is_cancelled`（フィルタ）と `seg1..seg4`（セクター分析・
  `seg1 IS NOT NULL`）も使用。だが v2 lap dict は `lap_no/lap_time/lap_time_s/is_cancelled` のみ。
  → seg/速度/local_time/is_outlap/is_pit を欠く。**判断事項**: (A) v2 拡張で完全互換（推奨・seg/speed/localtime 行は
  v2 が既に読んでいるので収集可）／(B) NULL 許容ローンチ（軽量だがセクター分析が機能後退）。

### 31c. scratch / Gate 設計
- staging = **`pdf_lap_times_v2_staging`**（`pdf_lap_times` 互換 + 来歴列 source_file/extractor_version/generated_at/
  gate_status）。自然キー (round,session_type,rider_num,lap_no,date)=§1c 整合。まず `/tmp/ts24_pdf_v2_scratch.db` で生成・検証。
- Gate（単位=session×rider・真値=`race_results`）: G1 カバレッジ / G2 lap数差≤1 / G3 best差≤0.05s / G4 lap_no重複なし /
  G5 物理レンジ / G6 来歴必須。**FAIL は正本へ絶対不採用**、結果は行 `gate_status` + `data_quality_log`(`gate_*`) に二重記録。

### 31d. MarkItDown
- **ローカル未インストール**（`import markitdown`→ModuleNotFoundError）。fitz(PyMuPDF)1.26.5 は利用可。
- network install は要 Tatsuki 承認のため本作業では導入せず。承認時は v2 取りこぼし検出の二次テキストソース
  （正本抽出器にはしない／LLM 補完禁止）。当面 G1 カバレッジは fitz の全文照合で代替可能。

### 31e. スコープ外（禁止遵守）/ 次手順
- `--write` 不使用（`--dry-run` のみ）。staging も正本未作成。pdf_lap_times/race_results 不変。Phase 2B 未着手。push なし。
- 実装手順（承認後・別タスク）: v2拡張→scratch生成→Gate→FAIL原因調査(#73)→承認→正本 staging 反映→Workbench 参照切替。
- 新規: `reports/pdf_v2_integration_design_20260625.md`。

---

## 32. Result PDF v2 extractor 拡張 + scratch Gate 実装（2026-06-25 Claude Code 実施）

§31 設計の Tatsuki 採用方針（**スキーマ A=v2拡張で `pdf_lap_times` 互換** / MarkItDown 不採用 /
#73 は Gate隔離＋正規表現補修優先 / 正本反映と Workbench 切替はまだ）を受け、**正本DB外（`/tmp` scratch）の
read-only 検証まで**を実装。**正本DB業務テーブルは before==after で不変を機械検証**。Obsidian
`00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-25 第2タスク）。

### 32a. `pdf_result_extractor_v2.py` 拡張（pdf_lap_times 互換化）
- `extract_pdf()` の lap dict に `seg1..seg4`/`speed`/`local_time`/`is_pit`/`is_outlap` を追加（既存
  `lap_no`/`lap_time`/`lap_time_s`/`is_cancelled` は不変＝**無回帰**。`audit_pdf_lap_extraction.py` も正常）。
- **セグメント写像 `_map_segments()`**: Chronological の読み順 `[r0,r1(=laptime同一行),r2,r3]` →
  `seg1=r2, seg2=r3, seg3=r0, seg4=r1`。**ASSEN/BALATON/JEREZ の `pdf_lap_times` と全一致で較正**。
  品質保全のため **4セグ揃い かつ sum(seg)≈lap_time(±0.05s) のラップのみ充填**、他（スタートラップ等）は
  **NULL**（誤割当・捏造を防ぐ）。`speed`/`local_time`/`is_pit`(P マーカー) は確実に取得。
  `is_outlap` は race=0 既定（FP/QP の精緻化は将来課題）。
- `pdf_lap_times_v2` CREATE と `write_to_db()` も新列対応（`EXTRACTOR_VERSION` 来歴付き）。

### 32b. `pdf_v2_scratch_gate.py`（新規・read-only / scratch + Gate）
- 正本DB `mode=ro`。`/tmp/ts24_pdf_v2_scratch.db` に **`pdf_lap_times_v2_staging`**（互換列＋来歴
  source_file/extractor_version/generated_at＋gate_status＋自然キー §1c）を生成し v2 抽出を投入。
- **Gate G1〜G6**（単位=session×rider・真値=`race_results`）: G1 coverage / G2 lap数差≤1 / G3 best差≤0.05s
  (≤0.5=WARNING) / G4 lap_no重複 / G5 physical range×[0.90,1.60] / G6 来歴必須。FAIL は採用しない。
- **真値フィルタの確定事項（新発見）**: `race_results` は同一 round ラベルで **COMPANY(=BSB) と WorldSSP が
  混在**（例 ROUND2/RACE1 = DONINGTON(BSB) + PORTIMAO(SSP)）。Result PDF は WorldSSP のため真値を
  `data_scope <> 'COMPANY'` に限定 → 偽 FAIL を 87→16 に是正。

### 32c. 検証結果（read-only / `--all` 45 PDF）
- **正本DB業務テーブル不変**: runs275/laps1202/lap_suspension1202/race_results792/pdf_lap_times7613（before==after）。
- **重点 ROUND3/RACE1**: #52 **PASS**(18 laps/best97.457一致)・#77 **PASS**(18 laps/best97.350一致＝欠落解消)・
  #73 **FAIL**（results-only＝原文 Chronological に per-lap データ無し。正規表現バグではなくソース制約のため補完しない）。
- 全体 rider 単位: PASS 425 / WARNING 805 / FAIL 16。RACE は概ね高 PASS。
  - **FAIL 16 の主因=results-only 11**（chrono 区間なし）/ 完全欠落2(ROUND6 RACE2 #63/#87)/ best差2 / lap数差1。
  - **非 RACE(SP/QP/FP/WUP) の WARNING 多数**は `is_outlap`/`is_pit` 未完全導出（out/in ラップが G5 超過）＋
    `race_results.laps` のレース距離基準と予選/練習の周回意味差。→ 非 RACE clean 化は is_outlap 導出＋
    session-type 別 Gate が次段階で必要（既知ギャップ）。
- レポート: `reports/pdf_v2_gate_20260625.md`。py_compile PASS（両スクリプト）。既存 v2 dry-run 無回帰。

### 32d. スコープ外（禁止遵守）/ 次手順
- 正本DBへの書込なし / 正本DB内 staging 作成なし / v2 `--write` を正本へ実行せず / Workbench 参照先変更なし /
  Supabase なし / Phase 2B 未着手 / MarkItDown install なし / origin push なし。
- **次（要 Tatsuki 承認・別タスク）**: ①results-only/FAIL の扱い確定（summary のみ別管理 or 除外）
  ②PASS 行のみ正本DB内 `pdf_lap_times_v2_staging` へ反映 ③Workbench 参照切替＋データ品質表示（UI 変更）
  ④非 RACE 向け is_outlap 導出 + session-type 別 Gate。
- 新規: `pdf_v2_scratch_gate.py` / `reports/pdf_v2_gate_20260625.md`。変更: `pdf_result_extractor_v2.py`。

---

## 33. Result PDF v2 正本 staging 反映 実装計画（read-only 事前確認）— 2026-06-27 Claude Code 実施

§32 の Gate 結果を受け、Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-27）の指示で
**正本反映の前段：read-only 事前確認と実装計画**を作成。**正本DB書込・table作成・Workbench 変更・push なし**。
計画書 = `reports/pdf_v2_canonical_staging_plan_20260627.md`。

### 33a. read-only 再確認
- `pdf_v2_scratch_gate.py --all` を `mode=ro` 再実行 → 業務テーブル **before==after 不変**。PASS lap 行=6756（seg充填6286）。
- **セッション種別の差**: RACE=PASS399/WARN69/FAIL3（race_results が完全分類＝Gate 有効）/
  非RACE=PASS26/WARN736。**非RACE WARNING の主因=「race_results に該当行なし」714**＝予選/練習は per-rider 真値が
  部分的（Gate の真値モデルが非RACEに不適合）。v2 の品質劣化ではない。

### 33b. PASS-only 反映計画（要承認）
- 正本DB内 **新規** `pdf_lap_times_v2_staging`（業務テーブルは ALTER せず追加のみ＝§20b と同非破壊）。
  自然キー `(round,session_type,rider_num,lap_no,date)`（§1c）/ `INSERT OR REPLACE` 冪等。
- 段階: **Step1=RACE PASS(399)**（Race Analysis 欠落を直接解消）→ Step2=RACE WARNING(実ラップ・flag付)
  → Step3=非RACE（is_outlap 導出 + session 内ゲート整備まで保留）。FAIL は不採用。
- 安全策: 事前フルバックアップ / before==after assert / ロールバック=`DROP TABLE`（業務テーブル無影響）。
  staging 反映と Workbench 切替は**別承認・別タスクに分離**（staging 作成だけでは現行挙動不変）。

### 33c. Workbench 参照切替（最小案・要承認）
- `RaceAnalysisTab` は `pdf_lap_times` を **11箇所のSQLリテラル**で参照（L4935/4937/4957/4960/4984/5132/5210/
  5283/5378/5448/5567）。使用列は seg1-4/is_outlap/is_pit/is_cancelled 等で v2 拡張と整合。
- **推奨案A**: 正本 **VIEW `race_lap_detail`**（v2-PASS を overlay、無い rider-session は旧 `pdf_lap_times` に
  フォールバック＝**非RACE 無回帰**）。Workbench はクラス定数 `RACE_LAP_SRC` を追加し 11 リテラルを置換、view へ。
- **品質表示**: フィルタ中 (round,session) の PASS/WARN/FAIL・#73=results-only・来歴(source_file/extractor_version/
  generated_at) を表示。欠落の 0 埋め/推測補完はしない（§12）。

### 33d. FAIL/WARNING 扱い
- FAIL16 不採用: results-only11（明細が原文 PDF に無い＝作らない／summary のみ別表示可）/ 完全欠落2 / best差2 / lap数差1（要調査）。
- RACE WARNING(69)=実ラップ（extra35/range外34）→ flag 付き採用可。非RACE WARNING(736)=真値モデル不適合 → 保留。

### 33e. 要 Tatsuki 承認 / スコープ外
- 承認要: ①staging 作成+PASS反映（正本書込）②VIEW 作成（正本書込）③Workbench 参照切替（UI）④Step2拡大
  ⑤Supabase/Excel/dashboard 反映要否 ⑥origin push。
- 本作業は **read-only のみ**: `/tmp` scratch 生成のみ・正本DB書込/insert なし・Workbench 未変更・push なし。
- 新規: `reports/pdf_v2_canonical_staging_plan_20260627.md`。

---

## 34. Result PDF v2 staging 反映スクリプト（既定 dry-run）— 2026-06-27 着手/2026-06-28 実行 Claude Code

§33 計画に基づき、Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-27）の指示で **反映スクリプトを実装し dry-run のみ実行**。
**`--apply` は実行せず・正本DBへの書込/ table作成/ VIEW作成/ Workbench 変更なし**。

### 34a. `apply_pdf_v2_staging.py`（新規）
- **既定 dry-run**（`--apply` 無し）。dry-run は正本DBを `mode=ro` でしか開かない。
- 対象初期値: `session_type IN ('RACE1','RACE2')` かつ `gate_status='PASS'`（RACE 先行）。入力=`/tmp/ts24_pdf_v2_scratch.db`。
- SQL 生成を純関数に分離（`ddl_staging()` / `insert_sql()` / `ddl_view()`）→ レビュー用 `.sql` に出力。
  **VIEW `race_lap_detail` は SQL 出力のみ**で、apply パスでも作らない（別承認）。
- `--apply` パス（**本タスク未実行**・承認後 Tatsuki 実行用）: 事前フルバックアップ
  （`02_DATABASE/_backup_pdf_v2_staging_<TS>/`）→ `CREATE TABLE IF NOT EXISTS` + UNIQUE INDEX →
  PASS 行 `INSERT OR REPLACE` → **業務テーブル before==after assert（違反で rollback）** → commit。

### 34b. dry-run 結果（2026-06-28 実行・正本DB `mode=ro`）
- 投入予定 **6616 lap 行 / 399 rider-session**（RACE のみ・PASS のみ）。seg 充填 6165（93.2%、スタートラップ等は NULL=正常）。
- 投入前検証 **全 clean**: 自然キー重複0 / date NULL0 / lap_time_s NULL0 / 来歴欠落0 / 物理レンジ外0。
- **正本DB業務テーブル before==after 不変**、staging/view は正本に未作成（0）。
- ROUND6/RACE2 のみ rows30/riders2/seg0（PASS が2名のみ＝§32 の #63/#87 完全欠落の裏返し。要留意）。
- 出力: `reports/pdf_v2_staging_dry_run_20260627.md` / `reports/pdf_v2_staging_ddl_20260627.sql` /
  （gate 再生成）`reports/pdf_v2_gate_20260628.md`。py_compile PASS。

### 34c. スコープ外（禁止遵守）/ 承認後の手順
- `--apply` 未実行 / 正本DB table作成・insert・update・delete なし / VIEW 作成なし / Workbench 変更なし /
  Supabase なし / Excel・dashboard 再生成なし / Phase 2B 未着手 / origin push なし。
- 承認後（Tatsuki 実行）: ① `python3 apply_pdf_v2_staging.py --apply`（RACE PASS を正本 staging へ・業務不変 assert）
  ②（別承認）VIEW `race_lap_detail` 作成 → Workbench を `RACE_LAP_SRC=race_lap_detail` へ切替＋品質表示。
- 新規: `apply_pdf_v2_staging.py` / `reports/pdf_v2_staging_dry_run_20260627.md` / `reports/pdf_v2_staging_ddl_20260627.sql`。

---

## 35. ROUND7 (MISANO) 非2Dデータ反映計画 + 新システム検証 — 2026-06-28 Claude Code 実施

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-28）の指示で、ROUND7 の Report/Original/Result PDF（**2D は無し＝対象外**）を
DB へ反映する **dry-run 計画と新システム検証**を実施。**正本DB書込・Supabase・Excel/dashboard 再生成・push なし**。
計画書 = `reports/round7_non_2d_db_update_plan_20260628.md`。

### 35a. 棚卸し・2D 不在
- ROUND7 6 PDF + `20260612-ROUND7-JA52.xlsx` + `Data_Base_TS24_ORIGINAL.xlsx`（全て 2026-06-28 更新）を hash 記録。
- **`DATA 2D/` 最新は ROUND6（20260529）。ROUND7 の 2D data は無い** → `runs`/`laps`/`lap_suspension` と 2D 由来指標は反映対象外。

### 35b. ★MISANO レイアウト差を検出 → `pdf_result_extractor_v2.py` を安全側に修正
- MISANO の Chronological は ASSEN と版が異なり、① 速度がローカルタイム同一行（`240,0 14:04'...`）② セグメント読み順が
  ラップ間で不安定。修正前は **speed 欠落 + seg 誤割当リスク**だった。
- 修正: 速度を両レイアウトで取得。**PDF 単位レイアウト判定**（`_SPEED_LOCALTIME` 検出＝MISANO 系 → `seg_trust=False` で
  seg1..seg4 を NULL）。lap_no/lap_time/best/is_cancelled/is_pit/speed は両系で取得。
- 再検証（seg_sum_bad=0・無回帰）: ASSEN/BALATON/JEREZ=seg 充填維持（ASSEN #77 は PDF 単位判定で 17 に復帰）、
  MISANO=speed 取得・seg 安全 NULL。

### 35c. 検証（Gate `--all` 51 PDF）/ ROUND7 の扱い
- **正本DB業務テーブル before==after 不変**。集計 PASS425 / WARNING1006 / FAIL16。
  **既存ラウンド無回帰**（PASS425・FAIL16 不変、+201 WARNING は全て ROUND7）。
- ROUND7 6 PDF は例外なく解析（RACE 33 riders/各約570 lap 行）。だが **`race_results` に ROUND7=0 行（真値なし）** のため
  Gate は ROUND7 を全 WARNING（extra）に。**apply dry-run の RACE PASS には ROUND7 は含まれない**（ROUND7 PASS=0）。
  → **ROUND7 は先に Result PDF → `race_results` を反映**して初めて lap 明細 Gate が機能する。

### 35d. 反映可否（2D 不在）/ 順序
- 可: `race_results`（Result PDF・最優先）→ その後 pdf lap 明細 staging（MISANO は seg NULL・lap/best/speed 有効）。
  管理テーブル(registry/queue)は非破壊で可。
- 不可: `runs`/`laps`/`lap_suspension`/2D 由来指標（2D 到着後）。`problem_log`/`setup_decision_log` と Original setup は
  run_id（2D）依存のため保留・照合参照のみ。
- 順序: 管理テーブル → race_results(§1c 自然キー UPSERT) → lap 明細 staging → DB Master 安全再生成 → Supabase 監査(提案のみ)。各 dry-run→承認→apply。

### 35e. スコープ外（禁止遵守）/ 要承認
- 正本DB書込なし / 2D 取込なし / 2D 由来値作成なし / Supabase なし / Excel・dashboard 再生成なし / Phase 2B なし / push なし。
- 変更コード: `pdf_result_extractor_v2.py`（MISANO 対応・read-only 抽出器）のみ。新規: `reports/round7_non_2d_db_update_plan_20260628.md`。
- 要 Tatsuki 承認: ①ROUND7 race_results 反映 ②ROUND7 lap 明細 staging 反映 ③DB Master 再生成 ④Supabase ⑤registry/queue 更新 ⑥push。

---

## 36. ROUND7 race_results 反映 dry-run + MISANO 取消検出修正 + Multi-agent check — 2026-06-29 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29）の指示で、ROUND7 `race_results` 反映の **dry-run 準備**と
**複数エージェント組織運用の自己点検**を実施。**正本DB write なし**（`--apply` 未実行）。
レポート = `reports/round7_race_results_apply_dry_run_20260629.md`。

### 36a. `apply_round7_race_results.py`（新規・既定 dry-run）
- ROUND7 6 PDF → `race_results` 候補生成。**既存慣行に整合**: RACE1/RACE2=フルフィールド、FP/QP/WUP=TS24 チーム(#77/#52)のみ
  （既存 race_results 実データの分布に一致。`--full-nonrace` で全員に変更可）。
- 自然キー（ローカル UPSERT）= **(round, session_type, rider_num)**（`apply_pdf_positions_v2.py` と同一）。
- `--apply`（**未実行**・承認後 Tatsuki 用）: 事前フルバックアップ → 自然キー UPSERT(COALESCE) →
  **runs/laps/lap_suspension/pdf_lap_times 不変 assert（違反で rollback）**・race_results は候補数だけ増加。

### 36b. dry-run 結果（正本DB `mode=ro`）
- 候補 **74 行**（RACE1 33 / RACE2 33 / FP 2 / QP 2 / WUP1 2 / WUP2 2）。
- Quality Gate **全 clean**: 自然キー重複0 / 既存衝突0（ROUND7=0 行確認）/ 必須キー NULL0 / best NULL0 / 物理レンジ外0 / 型不正0。
- **正本DB業務テーブル before==after 不変**。

### 36c. ★Quality Gate が MISANO 取消検出漏れを発見 → 修正
- RACE best/laps 整合チェックで **2件 mismatch**（#94=0.21s, #22=0.018s）を検出。原因 = MISANO は取消マーカー `C` が
  **速度+ローカルタイム行の先頭**（`C 231,8 14:30'54.853`）に付き、従来パーサが行頭 `C` を検出できず取消ラップを valid 扱い。
- **race_results 候補はヘッダ best（権威値）を使うため元から正しい**が、lap 明細品質の問題。`pdf_result_extractor_v2.py` の
  ローカルタイム分岐で **行頭の C/P フラグと速度を抽出**するよう修正 → MISANO RACE1/RACE2 の best 不整合 **2→0**。
- 再検証: ASSEN(#77 canc1/#5 canc2)・BALATON 無回帰、Gate `--all` PASS425/WARN1006/FAIL16（**不変**）、staging dry-run 6616 不変。

### 36d. Multi-agent operating check（§1/§20・PROJECT_RULES・decision 照合）
- Codex/Handoff・Claude Code/Implementation・Extraction・Quality Gate・DB Integration・Documentation は成果物上で充足。
  Supervisor は承認境界で write 停止。Case Search/Hypothesis は反映後フェーズ（スコープ外）。Tatsuki=決める は承認待ち。

### 36e. スコープ外（禁止遵守）/ 承認後
- race_results への write なし / staging apply なし / VIEW なし / Workbench 変更なし / 2D 取込なし / Supabase なし /
  Excel・dashboard なし / Phase 2B なし / origin push なし。
- 承認後: ① `apply_round7_race_results.py --apply`（race_results 反映・非対象業務テーブル不変 assert）
  ② `pdf_v2_scratch_gate.py --all` 再実行（ROUND7 RACE が真値を得て PASS/WARNING/FAIL 判定可能に）。
- 新規: `apply_round7_race_results.py` / `reports/round7_race_results_apply_dry_run_20260629.md`。
  変更: `pdf_result_extractor_v2.py`（MISANO 取消検出）。

---

## 37. ROUND7 race_results apply 承認前最終チェック（GO待ち）— 2026-06-29 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29）の指示で、ROUND7 `race_results` write apply の
**承認前 readiness パッケージ**を作成。**`--apply` は未実行**（Tatsuki の明示GO待ち。タスク本文だけでは承認不成立）。
レポート = `reports/round7_race_results_apply_readiness_20260629.md`。

### 37a. 承認前再確認（正本DB無変更）
- HEAD `e30dd08` 確認。`py_compile`（apply_round7_race_results.py / pdf_result_extractor_v2.py）PASS。
- dry-run 再実行: 候補 **74 行**・Quality Gate 全 clean（dup/collision/null_key/null_best/bad_best/bad_type/lap_best_mismatch=0）・
  **業務テーブル before==after 不変**。apply 前件数: runs275/laps1202/lap_suspension1202/race_results792/pdf_lap_times7613、ROUND7=**0**。

### 37b. 承認パッケージ内容
- 対象=`race_results` のみ（+74 見込み・全て新規 INSERT）。非対象=runs/laps/lap_suspension/pdf_lap_times（不変 assert）。
- exact command（GO後）: `python3 apply_round7_race_results.py --apply`。
- 事前バックアップ `02_DATABASE/_backup_round7_rr_<TS>/`、rollback 手順、apply 後検証（件数 / ROUND7=74 / gate 再実行 / staging dry-run）。
- Multi-agent operating check（承認前段階）: Codex/Claude Code/Extraction/Quality Gate/DB Integration/Documentation/Supervisor は充足、
  Tatsuki=最終GO 待ちのみ。

### 37c. スコープ外（禁止遵守）
- 明示GOなしの `--apply` なし / race_results 書込なし / staging apply なし / VIEW なし / Workbench 変更なし /
  2D 取込なし / DB Master 再生成なし / Supabase なし / origin push なし。
- GO 受領時のみ `--apply` → `pdf_v2_scratch_gate.py --all` → `apply_pdf_v2_staging.py`(dry-run) を実行し記録する。
- 新規: `reports/round7_race_results_apply_readiness_20260629.md`。

### 37d. ★apply 実行（2026-06-29・Tatsuki GO 受領 → 正本DB書込実施）
- **GO**: Tatsuki が本セッションで「apply してください」と明示 → `apply_round7_race_results.py --apply` を実行。
- **結果**: insert=74 / update=0。バックアップ `02_DATABASE/_backup_round7_rr_20260629_150354/`。
  **`race_results` 792→866（+74）/ runs・laps・lap_suspension・pdf_lap_times 不変**（assert 合格）。ROUND7 race_results=74。
- **Gate 再実行**: 全体 PASS **425→489** / WARNING **1006→942** / FAIL **16不変**。ROUND7 が真値獲得し
  RACE1=30 PASS/3 WARN/0 FAIL・RACE2=32 PASS/1 WARN/0 FAIL。**#77/#52 RACE は PASS**。
- **staging dry-run**: 投入予定 6616→**7710 行**（ROUND7 RACE PASS=1094 が候補入り）・検証全 clean・業務テーブル不変。
- **これは初の正本業務テーブル書込（race_results）**。以降の lap 明細 staging apply / DB Master 再生成 / Supabase /
  Workbench 切替 / push は引き続き別承認。記録: 本§ / `reports/round7_race_results_apply_readiness_20260629.md` / Obsidian。

---

## 38. Result PDF v2 staging apply 承認前最終チェック（ROUND7 反映後・GO待ち）— 2026-06-29 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29）の指示で、ROUND7 `race_results` 反映後の最新状態で
**`pdf_lap_times_v2_staging` への apply 承認前 readiness パッケージ**を作成。**`apply_pdf_v2_staging.py --apply` は未実行**（GO待ち）。
レポート = `reports/pdf_v2_staging_apply_readiness_20260629.md`。

### 38a. 承認前再確認（正本DB無変更）
- HEAD `ff643c4`。py_compile（apply_pdf_v2_staging / pdf_v2_scratch_gate / pdf_result_extractor_v2）PASS。
- 正本DB: `race_results` 866（ROUND7=74）。**`pdf_lap_times_v2_staging` は正本に未作成（=0）→ 新規作成 apply**（既存衝突・置換なし）。VIEW も未作成。
- Gate `--all` 再実行: PASS489/WARNING942/FAIL16・業務テーブル before==after 不変。

### 38b. apply 対象 / 検証（dry-run 実測）
- 対象 = 新規 `pdf_lap_times_v2_staging`、`RACE1/RACE2` × `gate_status='PASS'` の lap 明細。
  **7710 lap 行 / 461 rider-session**（うち ROUND7 由来 **1094 行**・seg 充填 6165）。
- 投入前検査 **全 clean**: 自然キー重複0 / date NULL0 / lap_time_s NULL0 / 来歴 NULL0 / 物理レンジ外0 / 業務テーブル不変。
  MISANO(ROUND7) は seg=NULL（安全・Workbench セクター分析で `seg1 IS NOT NULL` により自然除外）。

### 38c. apply 方針（GO 後）/ rollback / 検証
- command: `python3 apply_pdf_v2_staging.py --apply`（事前フルバックアップ `02_DATABASE/_backup_pdf_v2_staging_<TS>/` →
  CREATE + UNIQUE INDEX → INSERT OR REPLACE → 既存業務テーブル不変 assert → commit）。
- rollback: 新規テーブルゆえ `DROP TABLE pdf_lap_times_v2_staging`、またはバックアップから差し戻し。
- apply 後検証: staging 件数=7710 / ROUND7 RACE=1094 / 重複0・NULL0 / 既存業務テーブル不変 / gate 再実行。

### 38d. スコープ外（禁止遵守）/ 要承認
- `--apply` なし / VIEW なし / Workbench 変更なし / DB Master 再生成なし / Supabase なし / 2D 補完なし / push なし。
- **重要**: この staging apply 自体は **Workbench 表示を変えない**（VIEW 作成と参照切替は別承認）。
- 次の別承認: ①VIEW `race_lap_detail` 作成 ②Workbench 参照切替 ③品質表示 ④DB Master 再生成 ⑤Supabase ⑥push。
- 新規: `reports/pdf_v2_staging_apply_readiness_20260629.md`。

### 38e. ★staging apply 実行（2026-06-29・Tatsuki GO 受領 → 正本DB内に新規 staging 作成）
- **GO**: Tatsuki が本セッションで「GO の承認します」と明示 → `apply_pdf_v2_staging.py --apply` 実行。
- **結果**: 正本DB内に **新規 `pdf_lap_times_v2_staging` を作成・7710 行 INSERT**（ROUND7 RACE PASS=1094 含む）。
  バックアップ `02_DATABASE/_backup_pdf_v2_staging_20260629_153524/`。
- **検証**: staging 件数=7710 / ROUND7=1094 / 自然キー重複0 / date・lap_time_s・source NULL0。
  **既存業務テーブル不変**（runs275/laps1202/lap_suspension1202/race_results866/pdf_lap_times7613・assert 合格）。
  Gate `--all` 再実行 PASS489/WARNING942/FAIL16 安定。
- **Workbench 表示は不変**: VIEW `race_lap_detail` 未作成、`RaceAnalysisTab` は `pdf_lap_times` 参照のまま（`ts24_workbench.py` 未変更）。
  staging は追加されたが、まだ誰も参照していない（参照切替は別承認）。
- 記録: 本§ / `reports/pdf_v2_staging_apply_20260629.md` / Obsidian。
- **次の別承認（未実施）**: VIEW 作成 / Workbench 参照切替＋品質表示 / DB Master 再生成 / Supabase / origin push。
