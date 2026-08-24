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

---

## 39. VIEW race_lap_detail + Workbench 参照切替 承認前チェック（write/UI変更なし）— 2026-06-29 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29）の指示で、staging apply 後の状態で **VIEW 作成 + Workbench
参照切替の承認前 readiness** を作成。**正本DBへの VIEW 作成・`ts24_workbench.py` 編集・UI 変更は未実施**。
レポート = `reports/race_lap_detail_view_workbench_readiness_20260629.md`。

### 39a. scratch 検証（正本DBのコピー `/tmp/ts24_view_test.db` で overlay VIEW を作成・正本は不変）
- VIEW = `pdf_v2_staging_ddl_20260627.sql` (3)（v2 PASS を UNION ALL legacy(NOT EXISTS) で overlay）。
- 結果: `race_lap_detail` = **12763 行**（v2 7710 + legacy 5053）・自然キー重複 **0**。
- **RACE は v2 優先**: ROUND3/RACE1 #52 旧8→VIEW18・#77 旧0→VIEW18（切断/欠落の解消）。
- **非RACE は legacy フォールバック・無回帰**: ROUND3/SP 旧235→VIEW235（空にならない）。
- **ROUND7 RACE #77/#52** = VIEW に v2 18 laps で表示。
- 列互換 OK（RaceAnalysisTab が使う round/session/rider/lap_no/lap_time_s/seg1-4/is_outlap/is_pit/is_cancelled を VIEW が提供。MISANO は seg=NULL）。

### 39b. Workbench 変更案（最小差分・未編集）
- `RaceAnalysisTab` に定数 `RACE_LAP_SRC`（既定 `"pdf_lap_times"` → 承認後 `"race_lap_detail"`）追加、
  `pdf_lap_times` リテラル **11 箇所**を `{self.RACE_LAP_SRC}` 化（クエリ論理不変・テーブル名差替のみ）。
- 品質表示の最小案: ヘッダ 1 行（v2 PASS/legacy 件数・欠落/FAIL）＋行詳細に source_tag/gate_status/source_file/extractor_version。

### 39c. rollback / 次承認
- rollback: `DROP VIEW race_lap_detail` / `RACE_LAP_SRC` を `pdf_lap_times` に戻す。VIEW はデータ無影響。
- 次の別承認: ①VIEW 作成 ②Workbench 参照切替 ③品質表示 ④DB Master 再生成 ⑤Supabase ⑥push。
- **2段階分離可能**: VIEW 作成だけでは表示不変、`RACE_LAP_SRC` 切替で初めて反映。
- 本作業: 正本DB・`ts24_workbench.py` とも不変。scratch(`/tmp`)検証のみ。新規: `reports/race_lap_detail_view_workbench_readiness_20260629.md`。

---

## 40. ★VIEW race_lap_detail 作成 + Workbench 参照切替 実行（2026-06-29・Tatsuki GO 受領）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29「実行ゲート」）。Tatsuki が本セッションで「GO認証します」と明示GO
（=`VIEW + Workbench switch GO`）→ 実行。レポート = `reports/race_lap_detail_view_workbench_apply_20260629.md`。

### 40a. VIEW 作成（正本DB）
- 事前バックアップ `02_DATABASE/_backup_view_workbench_20260629_155958/`。
- `race_lap_detail`（`pdf_v2_staging_ddl_20260627.sql` (3)・v2 PASS overlay + legacy NOT EXISTS フォールバック）作成。
- 検証: total=**12763**（v2 7710 + legacy 5053）・自然キー重複0・ROUND7/RACE1 #77/#52=18・非RACE ROUND3/SP=235（空でない）・
  **業務テーブル不変**（runs275/laps1202/lap_suspension1202/race_results866/pdf_lap_times7613）。

### 40b. Workbench `RaceAnalysisTab` 最小差分（`ts24_workbench.py`）
- クラス定数 **`RACE_LAP_SRC = "race_lap_detail"`** 追加（rollback: `"pdf_lap_times"`）。
- `pdf_lap_times` 直接参照 **11 箇所**を `{self.RACE_LAP_SRC}` へ置換（論理不変・参照先のみ）。SQL の `FROM pdf_lap_times` 残存=0。
- 最小品質表示: bar2 に `_lbl_quality` 追加、`_refresh_charts`→`_update_quality()` で現フィルタの source_tag(v2/legacy)/件数/
  rider数/extractor_version を 1 行表示（欠落を 0 埋めしない）。

### 40c. 検証
- `py_compile` PASS。**offscreen スモークテスト**（`QT_QPA_PLATFORM=offscreen`）: `RaceAnalysisTab` 構築 OK、
  ROUND7/RACE1 で `_refresh_charts` 例外なし・品質表示 `lap source: v2 528行/30名 [pdf_result_extractor_v2]`。
  **ROUND3/RACE1 #77 = 18 laps（旧 0 の欠落解消）**・セクター seg(NOT NULL)=17、ROUND7 #77=18（MISANO seg=NULL で
  セクター分析は自然除外・例外なし）、非RACE は legacy で空でない。
- 注: #77/#52 は team rider で `JA52`/`DA77` チェックボックス管理（field combo とは別系統＝既存仕様）。
- **GUI 目視（最終）は Tatsuki ローカル**（`python3 ts24_workbench.py`・ヘッドレス不可）。

### 40d. rollback / スコープ外
- rollback: `DROP VIEW race_lap_detail` / `RACE_LAP_SRC` を `pdf_lap_times` に戻す。staging は触らない。
- 未実施（別承認）: DB Master 再生成 / Supabase audit・sync / origin push。
- 新規: `reports/race_lap_detail_view_workbench_apply_20260629.md`。変更: `ts24_workbench.py`。正本DBに VIEW 追加（業務テーブル不変）。

---

## 41. DB Master 再生成 承認前チェック（race_lap_detail 反映後・write なし）— 2026-06-29 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29）の指示で、DB Master 再生成の **承認前 readiness** を作成。
**DB Master 再生成・Excel 書込は未実施**（`refresh_db_master_safe.py` に dry-run 無し＝実行せず read-only 確認のみ）。
レポート = `reports/db_master_refresh_readiness_20260629.md`。

### 41a. ★影響分析（最重要・確定）
- `build_excel_master.py` は **`race_results`/`pdf_lap_times`/`race_lap_detail`/`pdf_lap_times_v2_staging` を一切読まない**
  （grep 各0）。DB Master の実ソース = `runs`/`laps`/`lap_suspension`/`performance`（2D 由来）+ `run_tags`/`problem_log`/
  `setup_decision_log`（Workbench）。
- **ROUND7 は 2D 由来テーブルに 0 行**（runs/performance とも ROUND7=0）。
  → **DB Master を再生成しても ROUND7 race_results / v2 lap 明細 / `race_lap_detail` / Workbench 表示改善は反映されない**。
- **結論**: 本 Result PDF v2 / ROUND7 ラインの作業に **DB Master 再生成は不要**。再生成は Workbench `setup_decision_log` 等の
  最新化を Excel に反映したい場合に意味がある。ROUND7 を Excel に載せたいなら `build_excel_master.py` に
  race_results 由来シート新設の別タスクが必要。

### 41b. 安全策・rollback（GO 後の再生成時）
- `refresh_db_master_safe.py`: 対象 `02_DATABASE/TS24 DB Master.xlsx`、事前バックアップ `02_DATABASE/backups/`、
  Excel オープン検出（`~$`＋`lsof`→exit 2 中止）、正本DB は SELECT のみ、事後検証（主要6シート＋業務テーブル件数不変）。
- rollback: `backups/TS24_DB_Master.pre_refresh_<ts>.xlsx` を戻す。
- 未実施（別承認）: DB Master 再生成（GO 文言 `DB Master refresh GO`）/ race_results シート新設（別タスク）/ Supabase / push。
- 新規: `reports/db_master_refresh_readiness_20260629.md`。

---

## 42. Workbench 3フェーズ Suspension Run Compare UI 追加（既存DB列のみ・DB書込なし）— 2026-07-01 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-01）/ ノート `2026-07-01 What still missing on Workbench` の要望で、
`PostureAnalysisTab`（🦾 Suspension/Posture）に **Braking / Apex / Exit の3フェーズ Suspension Run Compare UI（MVP）** を追加。
**既存 DB 列のみ使用**。DB schema変更・正本DB書込・派生再計算・2D再処理・Supabase・origin push は**なし**。
レポート = `reports/workbench_phase_run_compare_ui_20260701.md`。

### 42a. 実装（`ts24_workbench.py`）
- 新ヘルパークラス **`PhaseRunCompareWidget`**（`PostureAnalysisTab` を肥大化させず分離）。親の DataFrame を
  `set_dataframe()` で共有（DB 二重読込なし）。import に `QListWidget, QListWidgetItem` 追加。
- 内部サブタブに **`🔧 3フェーズ Run比較`** を増設（既存 `📊 APEX分析（基本）` / `⚙️ Damping / Phase` は不変）。
  `_load_data` 成功時に `self._phase_cmp.set_dataframe(self._df)` を呼ぶ（try/except 保護）。外側 Circuit コンボ（`_update_all`）とは独立。
- 独自フィルタ: Circuit / Rider / Session（連動再構築・選択保持）/ Run 複数選択リスト（全選択・全解除・既定先頭4）/
  Phase(All/Braking/Apex/Exit) / Metric(F&R / F / R Position・Pitch=F−R・Heave=(F+R)/2)。
- グラフ2×2: ①Position 推移（X=lap_no・点=lap実測+線=Run trend線形近似・色=Run・F実線●/R破線▲・All時はApex表示）
  ②Phase Summary（X=Run・平均F/R・Braking赤/Apex青/Exit緑）③Suspension Speed（**利用可能な Braking F=`brk_f_dive_spd_*` /
  Exit R=`ce_r_spd_*` のみ** avg実線/peak破線、未整備は `not available yet`）④数値テーブル（Run/Lap/Phase 別・F/R/Pitch/Heave・
  速度は `n/a`(未整備)/`—`(NULL) 区別・先頭2000行）。
- データ定義: Braking=`brk_susF/R_avg` / Apex=`apex_susF/R_avg` / Exit=`ce_susF/R_avg`、Pitch=F−R、Heave=(F+R)/2。
  物理限界(F130/R70mm)超・lap_time 60–300s 外は除外。

### 42b. ★データ制約の扱い（重要）
- **3フェーズ×F/R のサス速度は DB 未整備**。実在は Braking F / Exit R のみ → 速度グラフはこの2つのみ表示。
- `brk_spd_avg`/`apex_spd_avg`/`ce_spd_avg` は**車速(km/h)** → **サス速度として代用表示しない**。未整備は UI 注記/`n/a` で明示。

### 42c. 検証
- `py_compile` PASS。**offscreen スモークテスト全項目 PASS**: 内部3サブタブ / Circuit8・Rider2・Session7 /
  ARAGON 20Run・既定4選択 / テーブル14列・Apex42行→All126行（3×）/ 全選択519行・全解除0行 / Circuit切替(ASSEN17/全157) /
  Exit注記(利用可=Braking F,Exit R) / **既存無回帰**（refresh OK・Damping/Phase 1081行・MainWindow 7タブ）。
- GUI 目視（最終）は Tatsuki ローカル（`python3 ts24_workbench.py`）。

### 42d. スコープ外（禁止遵守）/ 次
- 正本DB schema変更 / `lap_suspension` 新列 / サス速度の推測補完 / 2D再処理 / DB Master再生成 / Supabase / origin push は**なし**。
- 次候補（要承認）: 3フェーズ×F/R suspension speed 派生列の設計・dry-run（2D raw から phase別 dive/rebound speed 定義を先に確定）。
- 変更: `ts24_workbench.py`。新規: `reports/workbench_phase_run_compare_ui_20260701.md`。

---

## 43. 3フェーズ×F/R Suspension Speed 指標設計 + scratch feasibility（write/ロジック変更なし）— 2026-07-01 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-01）の指示で、Workbench `3フェーズ Run比較` の `not available yet`（Braking R / Apex F/R / Exit F の
サス速度）を埋めるための **3フェーズ×F/R Suspension Speed 指標を設計し scratch/read-only で feasibility 確認**。
**正本DB schema変更・本番 `build_master_db.py` ロジック変更・2D再処理・正本DB書込なし**。設計 report のみ。
レポート = `reports/phase_susp_speed_metric_design_20260701.md`。多エージェント設計レビュー（物理/データ/品質/UI）＋6主張の敵対的検証で **ENDORSE WITH CHANGES**。

### 43a. scratch feasibility（read-only・正本DB `mode=ro`）
- 本番 `build_master_db.py` を **import のみ**（低レベル parse・`AREAS`・`_vel`/`_zone_mask` 再利用）で、ARAGON/ASSEN/JEREZ×DA77/JA52 の **70 outing/475 lap** に
  「3フェーズ×F/R×{dive,reb,abs}×{avg,peak}」を再計算。scratch script はセッション scratchpad（非コミット）。
- **決定論**: 既存4列（`brk_f_dive_spd_avg/peak`, `ce_r_spd_avg/peak`）を同一パスで再計算し本番 `extract_outing` と **1900ペア突合→不一致0（PASS）**。
  正本DB照合 scratch値カバー率 **98.9%/98.6%**。→ マトリクスは本番と同一 grid/velocity/mask 基盤（他18セルは構成担保・full rebuild で再ゲート要）。
- ゾーン n>=5 成立: Braking 95% / Apex 99% / Exit 64%（Exit 希薄は CORNER_EXIT 本質・欠陥でない）。
- **★peak(max) は Apex/Exit で外れ値支配**（max/p95 最大7.24×・`apex_f_dive` max=7011mm/s=非物理スパイク）。Braking-F は1.6×で良性。

### 43b. 推奨設計（6補正込み）
- 列 = **26列 family**: **22新規**（`brk_f_reb`/`brk_r_dive`/`brk_r_reb`/`apex_f_dive`/`apex_f_reb`/`apex_r_dive`/`apex_r_reb`/
  `ce_f_dive`/`ce_f_reb`/`ce_r_dive`/`ce_r_reb` × avg/peak）＋**2凍結**（`brk_f_dive_spd_*`・byte一致・peak=max）＋**2 abs別名**（`ce_r_spd_*`・`superseded_by` directional）。
- 方向 dive/reb 主（圧縮=コンプ・伸び=リバウンド クリッカー対応）。ただし**相対ダンピング速度指数**（非校正・車速km/h と混同禁止）。
- **peak = 新22列は p95（max ではない）**／既存2 peak と abs別名は max のまま（reducer を列ごとに記録し誤比較防止）。
- **null 二段ガード分割**: avg=n>=5 / **peak(p95)=n>=10**（n=5 で p95 が max へ退化するため）。0 は「速度ゼロ」を意味しない（NULL 厳守）。
- **abs は distinct 統計**（`ce_r_abs 51.7 < ce_r_dive 62.4/ce_r_reb 63.2`）＝冗長でない。v1 は既存 ce_r 別名のみ、他5セルへの abs 追加は v2（Apex 活動量）へ。
- **低解釈セル明示**: `ce_f_dive`（立上り前輪は伸び側）・`brk_r_dive`（制動リアは伸び切り）は計算するが UI で低解釈と注記し本命 `ce_f_reb`/`brk_r_reb` へ誘導。

### 43c. Quality Gate / UI / rollout（設計のみ）
- Gate（`data_quality_log`/`metric_version_log`）: 既存46列不変(BLOCKING)・0≠NULL・zone-sample・range（avg/peak 別）・unit(relative mm/s・km/h禁止)・
  CE null-rate band は **full-DB ~45% 基準**（sample 37.5% ではない）。`backfill_susp_zone_speed.py` の `NEW_COLS` を5→22拡張し **full rebuild へ決定論ゲート再実行**。
- UI: `PhaseRunCompareWidget._PHASE_SPD` を dive-only MVP で埋め、`col in rs.columns` ガードで DB反映前に安全マージ可。km/h 車速と別軸・構造NULL を `not available yet` と区別。
- rollout（GO後・別タスク）: `extract_outing` per-lap ブロック拡張（=本番ロジック変更）+ SCHEMA/`_build_lap_suspension` 22列 + 拡張決定論ゲート + ALTER/UPDATE。rollback=DROP COLUMN/backup。

### 43d. Tatsuki 承認事項 / スコープ外
- open questions: ①peak n>=10 の可否 ②abs 範囲(v1) ③Exit-R 初日 abs維持 ④UI Reb 即時可視化 ⑤位置前処理（**非平滑化推奨**＝byte-compat保持）⑥rollout GO(full DB)。
- 次ゲート文言 = `Phase suspension speed design GO`。
- 未実施: schema変更 / `lap_suspension` 新列 / 本番ロジック変更 / 2D再処理 / DB Master / Supabase / origin push。
- 新規: `reports/phase_susp_speed_metric_design_20260701.md`（+ scratchpad scratch script・非コミット）。

---

## 44. ★Phase Suspension Speed 派生列 apply（Tatsuki GO 受領 → 正本DB反映）— 2026-07-01 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-01 実行ゲート）。**Tatsuki が本セッションで「私の方からのGO承認します」と明示GO**
（=`Phase suspension speed design GO`）→ §43 設計 + Tatsuki Braking sketch を正本DBへ反映。
**正本DB `lap_suspension` に 3フェーズ×F/R×方向 サス速度 22新列を「追加のみ」で反映**（既存データ byte 一致・業務テーブル不変）。
レポート = `reports/phase_susp_speed_apply_20260701.md`。**2回目の正本業務テーブル書込（schema 変更を伴う初のケース・追加のみ）**。

### 44a. 実装（本番ロジック拡張・追加のみ）
- `build_master_db.py`: `extract_outing` に per-lap `phase_spd_matrix`（22値）算出を追加。既存 `vf/vr/fb_mask/ce_mask` 再利用＋`mc_mask=MID_CORNER`。
  `_dir_stat`: dive=v>0 / reb=-v(v<0)、**avg=mean(方向n>=5) / peak=p95(方向n>=10)**、未満NULL。**既存 `brk_f_dive_spd_*` 凍結・`ce_r_spd_*`(abs) 不変**。
  定数 `PHASE_SPD_NEW_COLS`(22)/`PEAK_NMIN=10`。`SCHEMA` へ f-string 注入・`_build_lap_suspension(+matrix_by_lapid)` は末尾付与（named INSERT・placeholder 算出）・`build_all` で matrix 収集。
- 新規 `apply_phase_susp_speed.py`（既定 dry-run）: 決定論ゲート（既存45列 lap_id JOIN・`abs<1e-6`・集合一致）→ `--apply` で backup→ALTER 22→UPDATE(新列のみ)→before==after assert(既存列sha256/業務件数)→commit/rollback。
- `create_quality_tables.py`: `metric_version_log` に22列シード（guard_rule に n>=5/n>=10・peak=p95(新)/max(既存)・相対指数・車速混同禁止・低解釈セル明記）。管理テーブルのみ。
- `ts24_workbench.py`: `PhaseRunCompareWidget._PHASE_SPD` を 6 slot 充填（**Braking F=brk_f_dive(既存) / Braking R=brk_r_reb(本命) / Apex F/R=dive / Exit F=ce_f_reb(本命) / Exit R=ce_r(abs 旧互換)**）。`_update_note` を col-guard 化＋relative-index/本命/構造NULL 注記。`_draw_speed` は既存 col-guard で無回帰。

### 44b. 実行結果（正本DB反映）
- full-DB scratch rebuild（受入ゲート 0件）→ **決定論ゲート PASS（既存45列×1202 lap 不一致0・lap_id 集合一致）**。
- apply: バックアップ `02_DATABASE/_backup_phase_susp_speed_20260701_234644/`・**ALTER 22 + UPDATE 1202**。
  業務テーブル before==after: **runs275/laps1202/lap_suspension1202/race_results866/pdf_lap_times7613**（不変 assert 合格）。
- 検証: `lap_suspension` 69列/1202行・22新列存在・**zero-leak 0**・**n-condition 0**・凍結列不変（brk_f_dive1072/ce_r661）・`metric_version_log` 32行。
  **★最終 integrity**: pre-apply backup vs 現正本で既存全列（凍結4速度列含む）**mismatch 0**＝追加のみ・既存 byte 一致を実証。
- 分布: Braking ~11% null / Apex 0.3% / Exit ~46%（本質的希薄）。p95 が peak 外れ値を抑制（apex_f_dive peak max3336→p95 549）。
  WARNING（非ブロッキング）: `apex_f_dive_spd_avg` max801（busy MID_CORNER lap・実信号）。
- Workbench: py_compile PASS・**offscreen smoke PASS**（Speed slot 6/6・`not available yet` 解消・Braking table F/R spd 数値化・既存タブ無回帰 Damping1081/MainWindow7）。**GUI 目視は Tatsuki ローカル**。

### 44c. rollback / スコープ外
- rollback: DB=バックアップ復元 / Code=revert（Workbench は col-guard で新列無くても起動可）。
- 未実施（別承認）: Supabase cleanup/sync・DB Master 再生成・origin push・新2D取込・大規模UI改修。
- 変更: `build_master_db.py`/`ts24_workbench.py`/`create_quality_tables.py`。新規: `apply_phase_susp_speed.py`/`reports/phase_susp_speed_apply_20260701.md`。正本DB: lap_suspension +22列・metric_version_log +22行。

---

## 45. Workbench Create Suspension Report PPTX MVP — 依存不足で readiness 停止（write なし）— 2026-07-02 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02）の指示で、Workbench に `Create Report` を追加し
サスペンションデータを PowerPoint `.pptx` で出力する MVP を実装する予定だった。**依存確認の結果、必須の
`python-pptx` と `matplotlib` が両方とも未インストール**のため、タスク規定（依存不足時はネットワーク install せず停止）に従い
**実装せず readiness report を作成して停止**。**正本DB・コード・Excel は無変更**（Obsidian/CLAUDE 記録のみ）。
レポート = `reports/workbench_suspension_report_readiness_20260702.md`。

### 45a. 依存確認（システム Python・venv 無し）
- ❌ `python-pptx`（未）/ ❌ `matplotlib`（未）/ ✅ `numpy 2.0.2` / ✅ `pandas 2.3.3` / ✅ `PyQt6 6.10.2` / ✅ `pyqtgraph 0.13.7`。
- `requirements_workbench.txt` にも両者は未記載。**2つの必須依存欠落 → 停止条件に合致**。ネットワーク install は承認境界（§27d-2）。

### 45b. read-only で確認した設計根拠（正本DB無変更）
- `lap_suspension` 1202行/**69列**・タスク §6 指定18列（brk/apex/ce の position + §44 の 22速度列）**全て実在**。
- **`lap_suspension` は per-lap 非正規化で `run_id/lap_id/rider/circuit/session/round/run_no/lap_no/lap_time_s/fullbrk_count/ce_count` を自己内包**
  → MVP は `SELECT * FROM lap_suspension` のみで完結し **`laps`/`runs` JOIN は不要**（race_lap_detail も不要）。
- Workbench `PhaseRunCompareWidget`（🔧 3フェーズ Run比較・L3059）は `Create Report` から再利用できる状態を保持:
  `_base_df()`（フィルタ済 DataFrame）/ `_checked_run_ids()`（選択 Run）/ `_PHASE_POS`・`_PHASE_SPD`・`_PHASE_COLORS`。
- `05_SCRIPTS/reports/pptx/` は未作成（実装時に生成）。既存 report helper / pptx 生成コードは無し。

### 45c. 最小設計（承認 + install 後の実装青写真・report に詳細）
- 新規 `suspension_report.py`（純関数群 + `build_pptx`/`make_chart_png` に分離・**pptx/matplotlib は import guard**で
  未導入時 `ReportUnavailableError`→Workbench で message box・アプリを落とさない）。DB は `mode=ro` read-only。
- Workbench: `PhaseRunCompareWidget` フィルタバーに `📄 Create Report` ボタン1個追加、`_base_df()`+`_checked_run_ids()` を使用。
  Run 未選択は message box、生成失敗は例外捕捉→message box。既存タブ無回帰の最小差分。
- スライド10枚（Title/Session Summary/Braking・Apex・Exit の Position/Speed ×3/Run Compare Table/Data Quality）。
  matplotlib `Agg`・Braking/Apex/Exit 色一貫・avg 主線/p95 補助線・**relative damping-speed index 注記・車速 km/h 非混同・NULL と not available を区別**。
  出力 = `reports/pptx/suspension_report_<circuit>_<rider>_<session>_<TS>.pptx`（timestamp・上書きなし）。

### 45d. 必要 dependency / 次ゲート
- 承認後 install: `python-pptx>=0.6.23` / `matplotlib>=3.7.0`（`requirements_workbench.txt` へ追記案あり）。
- 代替（非推奨）: チャートは `pyqtgraph.ImageExporter` で matplotlib 無しでも可だが、pptx 本体は python-pptx 必須（手組み OOXML は過剰）。
- **次ゲート（Tatsuki 承認）**: 「python-pptx / matplotlib を install してよい」の明示承認 → §45c 設計で実装 →
  `reports/workbench_suspension_report_mvp_20260702.md` 作成。
- rollback: コード・正本DB 無変更のため不要。
- スコープ外（禁止遵守）: ネットワーク install / Workbench 改修 / helper 追加 / pptx 生成 / DB schema 変更 / 正本DB 書込 /
  Supabase / DB Master 再生成 / origin push / 新2D取込。
- 新規: `reports/workbench_suspension_report_readiness_20260702.md`。変更: `CLAUDE.md` §45。

---

## 46. Local DB Master / Online DB 同期差分確認（Phase A・read-only audit）— 2026-07-02 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02）の指示で、正本DB / DB Master / Supabase の **read-only 差分確認（Phase A・GO不要）** を実施。
監査エージェント2並列（①正本DB+Excel ②Supabase）。**結果=差分あり → Phase B の `DB full sync GO` 確認へ**。書込は audit レポートのみ。
レポート = `reports/db_master_online_sync_audit_20260702.md`（+ `supabase_audit_20260702.md` / `cleanup_proposal_20260702.sql` 自動生成）。

### 46a. 監査結果（実測）
- **正本DB は健全**: runs275/laps1202/lap_suspension1202(**69列・22新列 22/22**)/race_results866(**ROUND7=74**)/pdf_lap_times7613/
  v2_staging7710/race_lap_detail(VIEW)12763/metric_version_log32 — §38/§40/§44 記録と完全一致。
- **Supabase 差分（exit 2）**: `race_results` **missing=74（全て ROUND7/MISANO＝§37d apply 後 sync 未実行が原因・削除不要 upsert で解消）**。
  remote_extra=**24（2026-06-22 と同一残骸**・sessions_2d 13 + lap_times_2d 11・cleanup 提案のみ再生成）。lap_times/他は一致。
- **DB Master.xlsx は stale**: mtime 2026-06-22・LAP_SUSPENSION **46列＝22新列 0/22**・RACE_RESULTS 相当シート無し・ROUND7 行無し。

### 46b. ★構造的制約（再確認・確定）
- `build_excel_master.py` は race_results/pdf_lap_times/v2_staging/race_lap_detail を**読まない**（§41a 同）→ 再生成しても ROUND7/v2 系は載らない（新シート設計=別タスク）。
- `LAP_SUSPENSION` シートは固定 `LS_COLS`（46列）→ **再生成だけでは22新列は載らない**。`LS_COLS` 22列拡張（§19d 34→46 の前例と同型・追加のみ）が必要。
- **Supabase 同期対象は4テーブルのみ**（race_results/lap_times/sessions_2d/lap_times_2d）。`lap_suspension`/`pdf_lap_times_v2_staging`/`race_lap_detail` は設計上同期対象外（欠陥ではない・online 化は新テーブル+自然キー UNIQUE の別タスク）。

### 46c. GO 後の同期計画（report §5）
① backup → ② `sync_to_supabase.py`（upsert・missing74 解消・DELETE なし）→ ③ `supabase_audit.py` 再実行（missing=0 確認）→
④（**別判断・GO に cleanup 明示時のみ**）remote_extra 24 DELETE（`cleanup_proposal_20260702.sql`・Tatsuki SELECT 確認後）→
⑤ `LS_COLS` 22列拡張 + `refresh_db_master_safe.py` 再生成 → ⑥ 検証（正本DB不変・Workbench smoke）。
GO 文言=**`DB full sync GO`**。origin push / 新2D / ORIGINAL.xlsx 上書き / DB Master 新シート設計は別承認。

### 46d. スコープ / 運用メモ
- Phase A で正本DB・Excel・Supabase とも無変更（remote は GET のみ）。
- 運用: Tatsuki 指示（2026-07-02）により、Codex 経由タスクは**サブエージェント並列委任**で実施（Token 節約・難所のみメインモデル対応）。承認境界は不変。
- 新規: `reports/db_master_online_sync_audit_20260702.md` / `reports/supabase_audit_20260702.md` / `reports/cleanup_proposal_20260702.sql`。変更: `CLAUDE.md` §46。

### 46e. ★Phase C 実行（2026-07-02・Tatsuki `DB full sync GO` 受領・cleanup は含まない選択）
- **GO**: Tatsuki が本セッションで `DB full sync GO` を明示（AskUserQuestion 回答。「GO + cleanup も含む」ではない方）。同時に PPTX MVP は「今回は見送り」＝GO未受領で未実行。
- **Supabase sync**（`sync_to_supabase.py` exit 0）: race_results 866/lap_times 7613/sessions_2d 246/lap_times_2d 1202 を upsert（DELETE なし）。
  再audit: **race_results missing 74→0（ROUND7 反映）**・全テーブル missing=0・remote_extra=24 は保留のまま（cleanup 未実行・`cleanup_proposal_20260702.sql` 提案維持）。
- **正本DB完全不変を実証**: before==after を件数+size+mtime+**sha256 一致**で確認。照合用 `02_DATABASE/_backup_db_sync_20260702/`。
- **DB Master 再生成**: `build_excel_master.py` `LS_COLS` 46→**68**（§44 の22方向別サス速度列を挿入のみ・py_compile PASS・全68列 PRAGMA 照合0欠落）→
  `refresh_db_master_safe.py` exit 0。検証: **LAP_SUSPENSION 68列/1204行・22新列 22/22**・12シート不変・RUN_LOG278/LAP_TIMES1204/DYNAMICS160 同等・
  バックアップ `backups/TS24_DB_Master.pre_refresh_20260702-121635.xlsx`・xlsx 580,125→710,672 bytes。
  race_results/ROUND7/v2 系シートは設計どおり未反映（新シート設計=別タスク）。
- **Workbench 無回帰**: py_compile PASS・offscreen `MainWindow(db)` 構築 OK・7タブ維持（Workbench は Excel 非参照）。
- rollback: Excel=pre_refresh 差戻し / LS_COLS=3行 revert / Supabase=追加方向のみ。レポート = `reports/db_master_online_sync_apply_20260702.md`。
- **残課題（別承認）**: remote_extra 24 cleanup（SQL 固定済み・Tatsuki SELECT 確認後）/ race_results 由来 DB Master 新シート設計 / origin push（`build_excel_master.py` 変更未コミット含む）/ PPTX MVP（GO 待ち）。
- 変更: `build_excel_master.py`（LS_COLS 挿入のみ）。Supabase: race_results +74。正本DB: 不変。

---

## 47. Workbench Create Report v2 設計（Phase A・read-only・GO待ち）— 2026-07-02 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02）+ ノート [[2026-07-02　Report Create System]] の Tatsuki 改善指摘6点を受け、
Report v2 の**設計のみ**（Phase A・GO不要）を実施。**依存 `python-pptx`/`matplotlib` は依然未インストール → 実装せず設計書を作成し Phase B で停止**。
正本DB・コード・Excel 無変更（`build_excel_master.py` の未コミット LS_COLS 拡張＝§46e には**一切触れない**）。
設計書 = `reports/workbench_report_v2_design_20260702.md`。

### 47a. Tatsuki 指摘6点（Report Create System）
①グラフ内ラベルがプロットに被る ②Lap time が `MM:SS,00` 形式でない ③表が分かりにくい（ヘッダ説明不足・エリア色分け無し）
④`0%` の意味不明（null/coverage/missing 区別なし）⑤Run 総合比較に寄り **Lap by lap 分析が不足** ⑥視覚訴求が弱い。

### 47b. サンプル v1 分析（inspect.ndjson）
`sample_suspension_report_JEREZ_DA77_TEST1_DAY1_20260702.pptx` = 10スライド・**ネイティブ PPTX チャート**（bar/line 7）+ テーブル2
（S9 Run Compare 8×8 / S10 Data Quality「Null rate 0%」7×3）。

### 47c. v2 設計の中核
- **★チャートエンジンを matplotlib `Agg` 画像へ移行**（ネイティブ chart から）: ラベル/凡例の座標精密制御・small multiples・`M:SS,CC` 軸フォーマッタ・
  エリア色帯を自在化し指摘①⑤⑥を根本解決。表はネイティブ table（セル塗りで色分け）。
- **Lap time フォーマッタ** `format_lap_time`（`M:SS,CC` 欧州式カンマ・センチ秒・繰上ガード。例 103.739→`1:43,74`）。既存 `_fmt_lap` とは別関数（上書きしない）。
- **ラベル衝突回避**: data label をプロット内に置かず表/コールアウトへ・凡例 `bbox_to_anchor` で外・最大6run/グラフ（超過は注記・silent切り捨て禁止）。
- **テーブル改善**: ヘッダ2行化（グループ＋単位）・Braking薄赤/Apex薄青/Exit薄緑のセル塗り・上部に `idx=relative damping-speed index` 等の説明行。
- **`0%` 明確化**: Missing/Null・Coverage・Structural n/a を分離明示（`Missing 0% (all N laps populated)`・Exit希薄は `n/a (structural: sparse CORNER_EXIT)`）。
- **カラー**: Braking `#C0392B`/Apex `#0078D4`/Exit `#2E9E4F`（`_PHASE_COLORS` と一致・全所で統一）。

### 47d. スライド構成 v2（~15枚・ページ増可）
Title/Scope → **Data Quality & Coverage** → Run Overview → Run Comparison Summary → Braking/Apex/Exit Phase Summary ×3 →
**Lap-by-lap: lap time progression / phase position progression / phase suspension speed progression** → **Run detail pages（選択 run 毎 small multiples）** →
Run Compare Table（color-coded）→ Data limits。
- Lap by lap: X=`lap_no`・series（lap time/best差/phase F/R pos/方向別 speed）・best=run内 valid(60–300s) 最小（`laps.is_outlap` JOIN で強化可）・
  **138/158 run が3周以上**（最大35周）で成立・n/a と NULL と 0 を区別。

### 47e. 接続/モジュール/検証/rollback（Phase C・GO後）
- `PhaseRunCompareWidget` に `📄 Create Report v2` ボタン（`_base_df()`/`_checked_run_ids()` 再利用・非クラッシュ）。
- 新規 `suspension_report.py`（純関数 + matplotlib/python-pptx import guard・DB `mode=ro`・`lap_suspension` 主ソース・schema 変更禁止）。
- 出力 `reports/pptx/suspension_report_v2_<circuit>_<rider>_<session>_<TS>.pptx`。検証: py_compile/slide数≥12/PPTX→PNG目視5点/offscreen smoke。
- rollback: 新規ファイル削除・ボタン revert・deps uninstall。正本DB/Excel/Supabase 無変更。

### 47f. Phase B ゲート / スコープ外
- 次アクション: Tatsuki へ **`Report v2 implementation GO`** を確認 → GO時のみ Phase C（install→実装→サンプル→検証→`reports/workbench_report_v2_apply_20260702.md`）。
- スコープ外（禁止遵守）: GO前の install/Workbench 編集/PPTX 正式生成 / 正本DB schema・行更新 / Supabase / DB Master 再生成 / origin push / 新2D / remote_extra 24 cleanup / 未コミット `build_excel_master.py` への干渉。
- 新規: `reports/workbench_report_v2_design_20260702.md`。変更: `CLAUDE.md` §47。

---

## 48. ★Workbench Create Report v2 実装（Tatsuki `Report v2 implementation GO` 受領）— 2026-07-02 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02 実装ゲート）。**Tatsuki が本セッションで `Report v2 implementation GO` を明示** → §47 設計を実装。
**依存導入（初のネットワーク install・GO承認済）→ `suspension_report.py` 実装 → Workbench ボタン → サンプル18スライド生成 → 検証 PASS**。
**正本DB read-only・schema/行 変更なし。** レポート = `reports/workbench_report_v2_apply_20260702.md`。

### 48a. 依存 / モジュール
- install: **python-pptx 1.0.2 / matplotlib 3.9.4**（`requirements_workbench.txt` に2行追記）。Agg/pptx 疎通 OK・既存 numpy/pandas と非競合。
- 新規 `suspension_report.py`: DB `mode=ro`（`lap_suspension` 主ソース + `laps.is_outlap` JOIN）・matplotlib Agg・python-pptx・**import guard**（`ReportUnavailableError`）。
  純関数（`format_lap_time`/`session_summary`/`phase_run_stats`/`lap_series`/`data_quality` 等）+ チャート5種 + `build_report_v2` + CLI。

### 48b. Tatsuki 指摘6点への対応（検証済み）
①ラベル被り→**matplotlib Agg・凡例プロット外・値は棒外/表** ②Lap time→`format_lap_time`（`M:SS,CC`・103.739→`1:43,74`・軸/表/ラベル）
③表→**ヘッダ2行+単位+Braking薄赤/Apex薄青/Exit薄緑セル塗り+説明行** ④0%→Data Quality を **`N/N populated · Missing 0%`+Structural(Exit sparse)** 明示・`0≠missing`
⑤**Lap by lap 専用3ページ（time/position/speed progression）+ Run detail 6ページ** ⑥Braking赤/Apex青/Exit緑 統一・small multiples・★=run best。

### 48c. Workbench（`ts24_workbench.py` 最小差分）
- `PhaseRunCompareWidget` フィルタバーに **`📄 Create Report v2`** ボタン + `_on_create_report()`（`_base_df()`+`_checked_run_ids()` 再利用）。
- Run 未選択→warning、import 失敗/`ReportUnavailableError`/例外→critical message box（**アプリを落とさない**）。生成中はボタン無効化。既存タブ無回帰。

### 48d. 検証
- py_compile（両ファイル）PASS。`format_lap_time` unit（繰上/None 含む）PASS。
- サンプル `reports/pptx/suspension_report_v2_JEREZ_DA77_TEST1_DAY1_20260702_v2demo.pptx`（**1.60MB / 18スライド / 16:9**・7 run）。
- チャート4種を Read 目視（ラベル被りなし・M:SS,CC 軸・色分け・★best・凡例外側）+ 表抽出（Missing 0% 明示・単位付き2行ヘッダ）PASS。
- offscreen smoke: MainWindow **7タブ**・`_btn_report` 存在・`_on_create_report` callable・既存無回帰 PASS。**GUI 目視は Tatsuki ローカル**。
- データ整合: Braking R≈0.9mm は rear-light（§18/§19）の実データ＝列マッピング正。

### 48e. old(v1) vs new(v2) / rollback / スコープ外
- v1（Codex サンプル10スライド・ネイティブ chart・生秒・1行ヘッダ・「Null rate 0%」曖昧・lap-by-lap 無）→ v2（18スライド・matplotlib・M:SS,CC・色分け表・Missing 明示・lap-by-lap 充実）。
- rollback: 新規ファイル削除 / ボタン revert / requirements 2行 revert / `pip uninstall`。正本DB/Excel/Supabase 無変更。
- **未実施（別承認）**: 正本DB write / Supabase / DB Master 再生成 / **origin push（`suspension_report.py`/`ts24_workbench.py`/`requirements_workbench.txt` 未コミット）** / 新2D / remote_extra 24 cleanup。
- 新規: `suspension_report.py` / `reports/workbench_report_v2_apply_20260702.md` / サンプル pptx。変更: `ts24_workbench.py` / `requirements_workbench.txt` / `CLAUDE.md` §48。

### 48f. 提出サンプル + PDF エクスポート追加（2026-07-02）
- **提出物**: `reports/pptx/suspension_report_v2_JEREZ_DA77_TEST1_DAY1_20260702_sample.pptx`（18スライド）+ **単一 PDF**（`..._sample.pdf`・17ページ・1.86MB）。
- **`suspension_report.py` に PDF 出力を追加**（`build_report_pdf()` / CLI `--pdf` / `_text_page`・`_table_page`・`_quality_page`・`_compare_page`・`_png_uniform`）:
  全スライドを画像化し **PIL で1 PDF に統合**（macOS Preview で開ける）。Data Quality/Run Compare テーブルも matplotlib 描画（フェーズ色・単位・Run は R1.. 短縮でクリップ回避）。LibreOffice 不要。
- 「`sample_preview_20260702` が開けない」= それは**フォルダ**（PNG 群）。1ファイルは **`..._sample.pdf`** を使う。テーブル2枚を Read 目視で確認（`66/66 populated · Missing 0%`・フェーズ列色）。py_compile PASS。
- **Workbench ボタンも PPTX + PDF 両方を出力するよう改善**（`_on_create_report` が `build_report_v2` 後に `build_report_pdf` も呼ぶ・PDF 失敗は PPTX 成功を妨げない）。offscreen smoke で 7タブ・ボタン・両関数 callable を再確認 PASS。
- Compare テーブルの Run 列は **`R1..` 短縮**でクリップ回避（PDF/matplotlib 版）・フェーズ列ヘッダに色（`_table_page` に `header_fills`/`col_widths` 追加）。

---

## 49. Report v2 polish — Cover 英語化 + チーム提出用デザイン（2026-07-02 Claude Code）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02「Report v2 polish」）。**GO 不要の bugfix/polish**（install/schema/write なし）。
Tatsuki 実機テストで **cover に日本語 `全` 混入**（`ARAGON | 全 / RACE2`）+ cover 簡素の指摘 → 修正。**`suspension_report.py` のみ変更**（Workbench UI 日本語は維持）。
レポート = `reports/workbench_report_v2_polish_20260702.md`。

### 49a. 原因 / 修正
- 原因: PhaseRunCompareWidget の combo sentinel `"全"` を scope として PPTX に verbatim 流入（cover + filename）。
- **scope 英語正規化**: `ALL_SENTINELS` + `_resolve_scope(scope, df)`（all→`All riders`/`All circuits`/`All sessions`・1値なら実値・2-3値は `All riders (DA77, JA52)` 列挙）。出力は英語のみ。
- **Cover 刷新**: `chart_cover()`（matplotlib 画像1枚を PPTX/PDF 共用）= navy アクセント + Title `TS24 Suspension Performance Report` + Subtitle + **KPI 4カード**（Runs/Laps/Best/Median・`M:SS,CC`）+ **Scope カード**（Circuit/Session/Rider/Generated 人間可読）+ **Phase legend**（Braking赤/Apex青/Exit緑）。PPTX は全面画像（`_add_cover_slide`）。
- **ファイル名 ASCII 化**: `_ascii_token()`（英数 + `_ -`・CJK 除去）。`全`→`ALL`（例 `..._ARAGON_ALL_RACE2_...`）・`TEST1_DAY1` は `_` 保持。`_save` に `tight=False`（cover 全面）追加。

### 49b. 検証
- py_compile（suspension_report / ts24_workbench）PASS。
- 再生成: `reports/pptx/suspension_report_v2_ARAGON_ALL_RACE2_20260702_polish.pptx/.pdf`（All riders (DA77, JA52)/RACE2）+ JEREZ sample を新 cover で再生成（filename 維持）。
- **CJK チェック全スライド**: ARAGON=14スライド **0** / JEREZ=18スライド **0**・cover=スライド1 画像（native text 0）。Cover 目視（Read）で英語・KPI/Scope/legend・`全` 無しを確認。単一 rider(JEREZ/DA77)は cover Rider=`DA77`。
- offscreen smoke 7タブ・ボタン・`chart_cover`/`_resolve_scope` callable PASS。既存ページ無回帰。
- 旧 `..._ARAGON_全_RACE2_20260702_153934.*`（Tatsuki テスト出力）は superseded（未削除）。
- 変更: `suspension_report.py`。新規: `reports/workbench_report_v2_polish_20260702.md` / サンプル pptx+pdf。未実施（別承認）: DB write/Supabase/DB Master/origin push/新2D/remote_extra cleanup。

---

## 50. Race Weekend Live Workflow 設計（2026-07-06 Claude Code・Phase A・read-only）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-06）+ Tatsuki ノート [[2026-07-06 TS24 New Workflow]]（`04_SYSTEM_DESIGN/` へ移動済み）+
手書きスケッチ `IMG_1057 1.heic`（sips で PNG 変換し転記）。**GO 不要の設計タスク**（正本DB/コード/Excel 無変更）。
レポート = `reports/race_weekend_live_workflow_design_20260706.md` / Obsidian 要約 = `04_SYSTEM_DESIGN/2026-07-06_TS24_Race_Weekend_Live_Workflow.md`。

### 50a. 要件と設計骨子
- 要件: 各セッション後に 2D data のみ先に抽出し Workbench/Report v2 を Race Weekend 中に使えるようにする（SpecSheet/Original/Result PDF はイベント後に統合）。
- 骨子（5ステージ）: ①Session Intake（📥 タブ新ボタン → 既存 `extraction_scan.py`・管理テーブルのみ）
  ②Session Extraction（新 `session_extract_staging.py`・dry-run 既定・`extract_outing` 等本番関数再利用・
  **provisional 3テーブル** `runs/laps/lap_suspension_provisional`・`PROV_` run_id・setup 空欄・業務テーブル before==after assert）
  ③Workbench overlay（`PostureAnalysisTab._load_data` L3930 の 1 SQL を final+provisional UNION へ・⏳ prov マーク・FileWatcher 自動 refresh）
  ④Report v2 `provisional` モード（cover リボン + filename トークン）
  ⑤Post-event final 化（従来 full rebuild + 決定論ゲートに provisional 突合を追加 → cutover → provisional クリア）。
- 方式比較: A 現行 batch / **B 手動ボタン式 session-first（推奨・採用候補）** / C folder watch（将来）。B の根拠 = 安全性（iCloud 部分同期・HED 誤配置の実績リスクを人間確認で遮断）+ 既存パターン最整合。

### 50b. 設計中の発見
- タスク文の `scan_phase2a_sources.py` は存在せず、Phase 2A スキャナ実体は **`extraction_scan.py`**。
- **ts24-report-import スキル Step 3（`build_unified_db.py`・Excel→DB 逆方向）が現行正本方向（§18/§20a）と矛盾** → Task 7 で改訂/廃止予定。
- import_queue 358 行全 pending（2B consumer 未実装）。session-first import を最小 2B consumer として位置付け（§20c/§22 整合）。
- 実装タスク分割 = Task 2-8（レポート §5）。**次ゲート = `Race weekend workflow implementation GO`**。
  未実施（GO 後も各別承認）: 新2D本取込 / schema 変更 / Supabase / DB Master / origin push / Original 上書き。

---

## 51. Race Weekend workflow Phase B-1 — Workbench Session Scan 基盤（2026-07-06 Claude Code・GO受領・apply済）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-06 Phase B-1）。**`Race weekend workflow implementation GO` を同セッションで受領**。
設計 = §50 Task 2。レポート = `reports/race_weekend_session_scan_apply_20260706.md`。**変更 = `ts24_workbench.py` のみ**（`extraction_scan.py` 無変更・二重実装なし）。

### 51a. 実装 / 検証
- `ImportQualityTab` に **`🔍 Session Scan` ボタン**（`_run_scan()`）: `sys.executable extraction_scan.py` を subprocess 同期実行
  （timeout 600s・WaitCursor・非クラッシュガード）。stdout/stderr → `reports/session_scan_<TS>.log`。exit≠0 は warning ダイアログ（末尾10行+ログパス）。
  成功時 `refresh()` + `_scan_summary()`（stdout 解析 → 管理テーブル フォールバック）を常設ラベル+ダイアログ表示。
  表示に **「Scan only / no 2D extraction yet（スキャンのみ・2D抽出はまだ行いません）」** を必ず含む。
- 検証: py_compile PASS / offscreen smoke（7タブ無回帰・ボタン/handler 存在）PASS /
  **実 scan 1回で業務6テーブル before==after 完全一致**（runs275/laps1202/lap_suspension1202/race_results866/pdf_lap_times7613/v2_staging7710）。
- 管理テーブル更新（許可範囲）: registry 366→372（新規6・更新26）/ queue 358→364（全pending）/ quality_log 72→440 /
  analysis_run_log +1（`20260706T135020_extraction_scan` success）。scanner 自前バックアップ `_backup_extraction_scan_20260706_135020/`。
- rollback = UI 追加ブロック除去のみ（DB 不要）。**GUI 最終目視は Tatsuki ローカル**。
- 未実施（別承認）: Task 3 `session_extract_staging.py`+provisional 3テーブル / 3フェーズ overlay / Report v2 provisional /
  Supabase / DB Master / origin push / 新2D本取込。

---

## 52. Race Weekend workflow Phase B-2 — Session Extraction Staging readiness（2026-07-06 Claude Code・Phase A・read-only・GO待ち）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-06 Phase B-2）。**GO 不要の readiness**（正本DB/コード/Excel 無変更・DDL は未実行のレビュー用SQL）。
レポート = `reports/race_weekend_session_staging_readiness_20260706.md` / DDL = `reports/race_weekend_session_staging_ddl_20260706.sql`。

### 52a. 確定事項
- **本番関数再利用を固定**: `discover_outings`/`gated_outings`/`extract_outing`/`session_canon_2d` を import 再利用・2D parser 二重実装禁止。
  唯一の薄い再実装 = `_recompute_is_outlap`（laps/runs テーブル名ハードコードのため）。①②③は per-session 動作可・④circuit P10 guard は
  MISANO 正本 0 laps のため本番同様に無参照 degrade。
- **provisional 3テーブル DDL 固定**（正本 PRAGMA 実測ミラー + provenance 6列 `data_stage/intake_ts/source_manifest_hash/source_file_path/provisional_event_key/quality_status`・UNIQUE run_id/lap_id・CREATE IF NOT EXISTS 冪等）:
  runs_provisional 49+6 / laps_provisional 16+6 / lap_suspension_provisional 69+6。名前衝突なし（実測確認済）。
- **provisional で NULL のままの列 = 7列のみ**: WheelForce 6列（`wf_f/r_{apex,brk,ce}_n`・Original のバネレート必要）+ `lap_susF_min`（本番でも NULL）。
  他62列は `extract_outing()` + フォルダ名メタデータで全て成立。runs 側は setup 33列 + comment が NULL。
- **PROV_ run_id は本番挙動と整合**: Original 不在時は本番も 2D_ONLY path（全 outing 採用・時系列 R1..）のため、
  `PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}` 時系列連番は同挙動。final 化で run_no が変わり得る旨を明記。
- **Round7 JA52 実テスト対象確認**: nested 33 outing（FP5/QP7/RACE1 8/RACE2 4/WUP1 4/WUP2 5・D0- NOISE除外）・
  registry 34行（33 2d_outing + 1 report・全 queued・sha256 manifest あり）・queue 33 pending 2d_extract。
  circuit fallback = `Misano.line`/EVENT.INI → MISANO（TRACK_M 登録済）。正本 ROUND7 runs=0（重複投入リスクなし）。
  ※Report `20260612-ROUND7-JA52.xlsx` は実在（§35・イベント後保存）だが、Report 非依存テストが目的のため `.line` fallback を主経路とする。
- registry に `manifest_hash` 列は無く、manifest は `sha256` 列（name|size・§24a）→ provenance へのマップを明記。

### 52b. 次ゲート
**`Session staging implementation GO`** 受領時のみ Phase C: `session_extract_staging.py` 実装（dry-run 既定・CLI `--db/--event/--rider/--session/--source-file/--apply/--limit/--report`）→
backup → DDL 実行 → **最初の dry-run/apply は Round7 JA52 の 1 session 限定（例 FP 5 outing・全33一括禁止）** → 業務6テーブル before==after assert →
report/Obsidian 記録。Workbench overlay / Report v2 provisional / Supabase / DB Master / origin push / final化 は別承認のまま。

---

## 53. Race Weekend workflow Phase B-2 — Session Extraction Staging 実装 + FP限定 apply（2026-07-06 Claude Code・GO受領・apply済）

**`Session staging implementation GO` を同セッションで受領**。readiness = §52。レポート = `reports/race_weekend_session_staging_apply_20260706.md`
（実行ログ: `session_staging_dryrun_all/dryrun_fp/apply_fp/apply_fp_rerun_20260706.md`）。**新規 = `session_extract_staging.py` のみ**（既存ファイル無変更・commit なし）。

### 53a. 実装
- `session_extract_staging.py`（~530行・dry-run 既定・`mode=ro`）: importlib で `build_master_db.py` の
  `gated_outings`/`extract_outing`/`session_canon_2d`/circuit fallback を再利用（2D parser 二重実装ゼロ）。
  薄い再実装は per-session is_outlap（①②③・④は正本 MISANO laps=0 のため本番同様 degrade）のみ。
  CLI `--db/--event/--rider/--session/--source-file/--apply/--limit/--report` + `--include-awaiting`（冪等再実行用・readiness からの唯一の追加）。
  quality gate 8チェック `stage_*`・exit 0/1/2/3。apply = backup → §52 DDL verbatim → INSERT OR REPLACE →
  queue pending→awaiting_gate → data_quality_log/analysis_run_log → **1トランザクション内 業務6テーブル before==after assert**。

### 53b. 実行結果
- 全33 dry-run（read-only・exit 2）: insert 12（PASS 8/WARNING 4=`stage_phase22_fill` 構造的 Exit NULL・情報扱い）+
  **FAIL 7 隔離**（全て `stage_lap_count`: QP-05・R1-02..05・GRID×2 有効lap 0）+ EngineWarmup skip 14。circuit=MISANO（Report/.line 両経路一致）。
- FP dry-run（exit 0）: 5 outing → 3 PASS（4/7/4 laps・best 99.429/98.791/98.364）+ 2 skip。
- **FP apply（exit 0）**: provisional 0→**3 runs/15 laps/15 lap_suspension**・重複0・quality_status 全 PASS・
  setup 33列+comment NULL・WF 6列+lap_susF_min NULL（違反0）・is_outlap 12 valid/3 outlap。
  **業務6テーブル count 一致 + backup 比較 full-row sha256 6/6 IDENTICAL**。
  backup `02_DATABASE/_backup_session_staging_20260706_142625/`。queue: 3→awaiting_gate・2→skipped。
- 冪等再実行: 3/15/15 不変・`stage_hash_idempotent` が既存 manifest hash を検出。
- Workbench offscreen smoke 7タブ PASS（`ts24_workbench.py` 無変更＝既存 §48/§51 未コミット diff のみ）。
- リーダー独立検証: mode=ro で業務6テーブル件数・provisional 3/15/15・PROV_ run_id/PASS を再確認済み。

### 53c. rollback / 残作業
- rollback: `DROP TABLE` provisional×3 or `DELETE ... WHERE provisional_event_key='20260612-ROUND7-JA52'` + queue status 戻し（レポートに SQL 固定）。
- 未実施（各別承認）: **残り session apply（QP/RACE1/RACE2/WUP1/WUP2 = insertable 9 outing/64 laps）**/
  Task 5 Workbench overlay（⏳ prov 表示）/ Task 6 Report v2 provisional / Supabase / DB Master / origin push / final化・provisional クリア。

---

## 54. Race Weekend workflow Phase B-3 — Workbench provisional overlay readiness（2026-07-06 Claude Code・Phase A・read-only・GO待ち）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-06 Phase B-3）。**GO 不要の readiness**（コード/DB 無変更・overlay SQL は mode=ro で実DB検証のみ）。
レポート = `reports/workbench_provisional_overlay_readiness_20260706.md`。

### 54a. 確定事項
- **列互換リスクなし**: `_load_data`（L3922-3985・SQL L3930）以降の全消費側（PhaseRunCompareWidget/APEX分析/Damping/suspension_report）は
  列名参照 + `col in df.columns` ガード・固定列リスト表示のため、`data_stage`/`quality_status` 追加（71列化）は無害。
  pitch/heave 導出も provisional 行で成立（実値確認済み）。
- **overlay SQL 固定（実DB検証済み）**: provisional 側は 75列（先頭69列が final と名前・順序一致）のため **PRAGMA 生成の明示列リスト**で
  `SELECT *, 'final', NULL FROM lap_suspension UNION ALL SELECT <69列>, 'provisional', quality_status FROM lap_suspension_provisional`。
  `sqlite_master` 存在チェックで legacy SQL fallback。検証: **1217行/71列/lap_id 重複0/provisional 15行（MISANO/FP/JA52・全PASS）**・
  filter combo へ MISANO/FP 自動出現（filter コード変更不要）。
- **UI 案**: Run ラベル = `⏳ ... (prov)`（`run_id.startswith("PROV_")` 分岐）。`Data stage` filter は**初回実装では見送り**（最小差分優先）。
  APEX分析/Damping への provisional 流入は v1 では注記のみで許容（MISANO は新規サーキットで既存表示に影響なし・PASS-only）。
- **Report v2 暫定ガード判断 = 警告ダイアログ + opt-in 続行（既定 Cancel）**。hard block にしない理由: race weekend 価値の維持・データは PASS。
  現状 PROV run の report は cover/filename に provisional 表記ゼロ → 警告文で明示 + チーム提出禁止を明記。Task 6 で provisional モードへ自動切替予定。
- rollback = UI diff 3箇所の revert のみ（DB 無変更の read-only 機能）。
- Phase C 検証計画: py_compile / offscreen 7タブ / MISANO-JA52-FP で PROV_ R1..R3 表示 / final-only 無回帰 /
  **fallback 実測**（provisional 3テーブルを DROP した一時コピーDBで offscreen 起動 → legacy 1202行）/ Report v2 ガード動作。

### 54b. 次ゲート
**`Workbench provisional overlay GO`** 受領時のみ Phase C: `ts24_workbench.py` 最小差分実装（`_load_data` overlay + fallback / Run ラベル prov 分岐 /
Report v2 警告ガード）→ 検証 → `reports/workbench_provisional_overlay_apply_20260706.md`。
DB 書込なし。残 session apply / Task 6 / Supabase / DB Master / origin push / final化 は別承認のまま。

---

## 55. Race Weekend workflow Phase B-3 — Workbench provisional overlay 実装（2026-07-06 Claude Code・GO受領・apply済）

**`Workbench provisional overlay GO` を同セッションで受領**。readiness = §54。レポート = `reports/workbench_provisional_overlay_apply_20260706.md`。
**変更 = `ts24_workbench.py` のみ・3箇所・DB read-only**（書込/queue変更/追加投入なし・commit なし）。

### 55a. 実装（最小差分3箇所）
- `PostureAnalysisTab._load_data`（L3946-3973）: `sqlite_master` 存在チェック → PRAGMA 実行時生成の69列リストで
  `SELECT *, 'final', NULL FROM lap_suspension UNION ALL SELECT <69列>, 'provisional', quality_status FROM lap_suspension_provisional`。
  try/except 保護・不存在/例外時は legacy SQL fallback（タブを壊さない）。
- `PhaseRunCompareWidget._run_label`（L3556-3570）: `PROV_` prefix で `⏳ {label} (prov)`（short 形式も同一分岐）。
- `_on_create_report`（L3458-3470）: PROV run 混在時 warning（§54 文面・Yes|Cancel・**既定 Cancel**・提出禁止明記・opt-in 続行）。

### 55b. 検証（8/8 PASS）
- py_compile / offscreen 7タブ / overlay `_df`=1217行（final 1202+prov 15）・MISANO/FP combo 出現 /
  MISANO-JA52-FP で Run リスト**ちょうど3件** `PROV_...R1..R3`・ラベル `⏳ JA52 FP R1 (ROUND7) (prov)` /
  final 無回帰（JEREZ/DA77/TEST1_DAY1 = 7 run・prov なし・base_df 66行 = §48 一致）/
  **fallback 実測**（scratch コピーで provisional 3テーブル DROP → legacy 1202行・例外なし）/
  Report ガード実測（warning 1回・既定 Cancel・Cancel で生成ゼロ）/ 正本DB 業務6+provisional 3 全件数 before==after。
- rollback = 3箇所の diff revert のみ。**GUI 最終目視は Tatsuki ローカル**（🦾 → 🔧 3フェーズ Run比較 → MISANO/JA52/FP）。
- 未実施（各別承認）: 残 session apply（QP/RACE1/RACE2/WUP1/WUP2 = 9 outing/64 laps）/ Task 6 Report v2 provisional 本対応 /
  Supabase / DB Master / origin push / final化。

---

## 56. Race Weekend workflow Phase B-4 — Round7 JA52 残session apply readiness（2026-07-06 Claude Code・Phase A・read-only・GO待ち）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-06 Phase B-4）。**GO 不要の readiness**（dry-run のみ・DB 無変更を実測確認）。
レポート = `reports/round7_ja52_remaining_session_apply_readiness_20260706.md`。

### 56a. 確定事項
- 現DB実測: 業務6 = 275/1202/1202/866/7613/7710・provisional 3/15/15（FP 全PASS・重複0）・
  Round7 queue = awaiting_gate 3 / skipped 2 / pending 28。
- **session別 dry-run 再実行 = B-2 ベースラインと完全一致（drift なし）**: 全event insert 9 outing/64 laps・FAIL 7・EW skip 12。
  QP 4/14（exit 2）・WUP1 1/6（exit 0）・WUP2 2/6（exit 0）・RACE2 1/19（exit 2）・RACE1 1/19（exit 2）。
  FP は awaiting_gate のため候補に出ない（`--include-awaiting` 挙動もコード確認済）。
- **投入順固定: QP → WUP1 → WUP2 → RACE2 → RACE1**（QP で全パターンを先に検証・FAIL 5 を含む RACE1 は最後・session単位で停止/切り戻し可能）。
- 全成功時の期待値: provisional **12 runs / 79 laps / 79 lap_suspension**・queue pending 28→0（awaiting_gate +9 / failed +7 / skipped +12）。
  ※apply は FAIL→failed / EW→skipped も queue に記録するため rollback SQL は3ステータスを戻す。
- backup = `do_apply()` が各 apply 前に全DBコピーを自動作成（コード確認済）。session単位 rollback SQL をレポートに固定。

### 56b. 次ゲート
**`Round7 remaining session provisional apply GO`** 受領時のみ Phase C: session毎に dry-run → apply → 業務6不変 → 増分/dup 0/quality 確認、
予期しない差分でそのsession停止。FAIL 7 救済 / Report v2 provisional / Session Import ボタン / Supabase / DB Master / push / final化 / provisional clear は別承認。

---

## 57. Race Weekend workflow Phase B-4 — Round7 JA52 残session 段階apply（2026-07-06 Claude Code・GO受領・apply済）

**`Round7 remaining session provisional apply GO` を同セッションで受領**。readiness = §56。レポート = `reports/round7_ja52_remaining_session_apply_20260706.md`。
**コード編集・commit なし**（既存 `session_extract_staging.py` のみ使用）。

### 57a. 実行結果（QP→WUP1→WUP2→RACE2→RACE1・全5session成功・停止なし）
- 各session: 直前dry-run（readiness §2.2 完全一致）→ 自動backup → apply → 業務6不変 assert + mode=ro 再測定（5回全て 275/1202/1202/866/7613/7710）。
- delta: QP +4/+14・WUP1 +1/+6・WUP2 +2/+6・RACE2 +1/+19・RACE1 +1/+19。FAIL 隔離 計7・EW skip 計12。
  WARNING は全て `stage_phase22_fill`（構造的 Exit NULL・仕様どおり insert 対象）。
- **最終: provisional 12 runs / 79 laps / 79 lap_suspension**（quality PASS 8/WARNING 4・重複全0）。
  session別ベスト: FP 98.364 / QP 97.636 / RACE1 98.055 / RACE2 97.778 / WUP1 98.109 / WUP2 98.045。
- queue Round7 最終: pending 0 / awaiting_gate 12 / failed 7 / skipped 14（readiness 期待一致）。
- 冪等: WUP2 再apply → 候補0・不変。backups: `_backup_session_staging_20260706_{153702,155221,164033,170019,170212}/`。
- Workbench offscreen: 7タブ・DataFrame **1281行**（1202+79）・MISANO/JA52 Run リスト 12件（全6session ⏳prov）・
  JEREZ final-only 無回帰・Report v2 PROV guard 存置。リーダー独立 mode=ro 検証一致。
- rollback = readiness §rollback の session単位 DELETE + queue reset（レポート再掲）。

### 57b. 残作業（各別承認）
FAIL 7 outing 救済/再解析 / Task 6 Report v2 provisional 本対応 / Workbench Session Import ボタン（Task 4）/
Supabase / DB Master / origin push / final化・provisional clear。**GUI 最終目視は Tatsuki ローカル**（MISANO/JA52 で 12 prov runs）。

---

## 58. Workbench scatter click ValueError hotfix（2026-07-07 Claude Code・GO不要・DB無変更）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-07）。レポート = `reports/workbench_scatter_click_hotfix_20260707.md`。
**変更 = `ts24_workbench.py` `PostureAnalysisTab._on_pt_click` のみ**（メイン直接対応・エージェント不使用＝Token効率）。
- 原因: PyQtGraph `sigClicked` が numpy.ndarray を渡すと `if not points:` が ValueError。
- 修正: `points is None or len(points)==0` 判定 + `points[0].data()` を try/except ガード（SpotItem 以外は return）。connect 側無変更。
- 検証: py_compile / 再現5ケース（[]・None・ndarray(3)・ndarray(0)・SpotItem相当）ValueError ゼロ /
  offscreen 7タブ・overlay 1281行・MISANO 12 prov runs。実機クリック確認は Tatsuki。rollback = 2ブロック revert。

---

## 59. Race Weekend workflow Phase B-5 — Report v2 provisional mode readiness（2026-07-07 Claude Code・Phase A・read-only・GO待ち）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-06 B-5）。**GO 不要の readiness**（コード/DB 無変更・PPTX/PDF 生成なし）。
レポート = `reports/report_v2_provisional_mode_readiness_20260706.md`。

- **seam 固定**: `build_report_v2`/`build_report_pdf` に `provisional=False` kwarg + `chart_cover(provisional, mixed)`。
  **明示フラグ + 内部自動検出セーフティネット**（df/run_ids に `PROV_` 検出で強制 provisional・CLI `main` L1006-1032 は provisional 非対応のため auto-detect が CLI 経路を保護）。
- cover: title band 右上に **英語 ribbon `PROVISIONAL - SESSION DATA`**（CJK=0 維持・§49）+ Scope card 下に 4行注記
  （Not final DB integration / Original setup data not merged / Run numbers are provisional / For race-weekend engineering review only）。
  `chart_cover` は PPTX（L809）/PDF（L983）共用 = **単一変更点**。mixed 選択は provisional 扱い + `Mixed final + provisional runs` 注記。
- filename: `prov_tok` を `_{ts}` 直前に挿入（L849-850/L999-1000）→ `..._MISANO_JA52_FP_PROVISIONAL_<TS>`。final-only は byte 同一。
- Workbench: `_on_create_report` L3458-3470 の警告を確認ダイアログ「provisional reportとして生成しますか？」（既定 Cancel）へ置換・Yes で `provisional=True`。
- Phase C 検証計画: py_compile / sample PPTX+PDF（まず MISANO/JA52/FP）/ text抽出 `PROVISIONAL` / final-only 無 `_PROVISIONAL_` / CJK=0 / offscreen smoke / DB 件数不変。
- **次ゲート = `Report v2 provisional mode GO`**。

---

## 60. Race Weekend workflow Phase B-5 — Report v2 provisional mode 実装（2026-07-07 Claude Code・GO受領・apply済）

**`Report v2 provisional mode GO` を同セッションで受領**。readiness = §59。レポート = `reports/report_v2_provisional_mode_apply_20260706.md`。
**変更 = `suspension_report.py` + `ts24_workbench.py` のみ・DB read-only**（業務6 + provisional 3 全件数 before==after 確認済み・commit なし）。

### 60a. 実装 / 検証（8/8 PASS）
- `suspension_report.py`: `build_report_v2`/`build_report_pdf` に `provisional=False` kwarg + `_detect_provisional()` 自動検出
  （PROV_ → 強制 provisional・mixed 判定）。`chart_cover(provisional, mixed)` = アンバー ribbon **`PROVISIONAL - SESSION DATA`** +
  英語4行注記（+ mixed 注記）。filename `PROVISIONAL_` トークンを `{ts}` 直前に挿入（両 builder）。
  ※ribbon 位置は readiness 座標がタイトル/フッタと干渉したため title band 右上 y0.93 へ目視調整（readiness 許容範囲・PNG で非重複確認）。
- `ts24_workbench.py` `_on_create_report`: 旧警告 → `QMessageBox.question`（Yes|Cancel・既定 Cancel）。Yes で `provisional=True` 両 builder 呼出。final-only はダイアログなし・無変更。
- sample: `reports/pptx/suspension_report_v2_MISANO_JA52_FP_PROVISIONAL_20260707_PROVSAMPLE.pptx/.pdf`（14スライド）+
  final 無回帰 `..._JEREZ_DA77_TEST1_DAY1_20260707_FINALREG.pptx/.pdf`（18スライド・`_PROVISIONAL_` 無し・ribbon 無し）。
- 検証: py_compile / cover PNG 目視（ribbon+4注記・英語のみ）/ **CJK=0 両サンプル** / auto-detect (True,False) /
  offscreen 7タブ・PROV選択→question 1回・既定 Cancel・Cancel 生成ゼロ・Yes stub で provisional=True 伝搬・final-only ダイアログ 0 /
  **DB 件数完全不変**。rollback = 2ファイル revert + sample 削除。**GUI/サンプル最終目視は Tatsuki ローカル**。

### 60b. 残作業（各別承認）
FAIL 7 outing 救済 / Task 4 Workbench Session Import ボタン / post-event final 化・provisional クリア（Task 7-8）/
Supabase / DB Master / origin push。**Race Weekend live workflow の主要ピース（Scan→Staging→Overlay→Provisional Report）はこれで完成**。

---

## 61. Supabase v2 architecture migration readiness（2026-07-07 Claude Code・Phase A・read-only・DDL GO待ち）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-07）。Codex 設計（`reports/supabase_v2_architecture_design_20260707.md` +
`04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707.sql`）の read-only レビュー。**本番 Supabase への SQL/sync/POST 一切なし・local mode=ro のみ**。
レポート = `reports/supabase_v2_migration_readiness_20260707.md`。

### 61a. レビュー判定 = **要修正（方向性は採用可・DDL実行前に7点改訂）**
- **BLOCKING**: `v_sync_runs` の `rs.*` により run_id 列重複 → Postgres で CREATE VIEW 失敗・**単一トランザクションのため現SQLは COMMIT ごと全滅**。
- 設計修正6点: ①track_temp/air_temp/weather は per-run 列のため v2 sessions でなく runs へ ②statistic 'peak' 禁止（新22列=p95/凍結列=max を区別）
  ③phase CHECK に 'ph12' 追加 ④source_files.sha256 → manifest_hash 改名（stat manifest のため）⑤runs.source 列欠落 ⑥metric_versions テーブル追加（metric_version_log 32行の受け皿）。
- 整合OK: 自然キー §1c 衝突なし・event_id（season内包）で round シーズン跨ぎ解決・run_setup 30列は local 一致。

### 61b. mapping 要点 / ゲート分割
- result_laps: legacy と v2 staging が同一自然キー → **VIEW `race_lap_detail`（12763行）を単一供給源** + source_table 列追加。
- lap_suspension wide→long ≈ 5-6万行・**n<5 は行を作らない（0≠NULL 厳守）**。provisional は data_stage 必須 + final-only view 既定。
- ゲート: **G1 DDL実行GO**（schema改訂+projectionサンプル後）→ G2 初回 v2 sync GO（新規 `sync_to_supabase_v2.py`・既存v3不変）→
  G3 compat view 切替GO（行レベル一致証明後）→ G4 旧テーブル整理GO。rollback = `DROP SCHEMA ts24_v2 CASCADE`（正本無影響）。

---

## 62. Task 4 — Workbench Session Import (staging) ボタン実装（2026-07-07 Claude Code・apply済）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-07 Task 4 finish gate）。レポート = `reports/workbench_session_import_button_20260707.md`。
**変更 = `ts24_workbench.py` のみ**（`ImportQualityTab`・`session_extract_staging.py` subprocess 再利用・二重実装なし）。

### 62a. 実装 / 検証
- `⬇ Session Import (staging)` ボタン（L6763-6768・Session Scan の隣）+ `_run_import()`（L6908-7095）:
  dry-run subprocess → 確認ダイアログ（候補/PASS/WARN/FAIL/queue 変更予定を明示・**Apply|Cancel 既定 Cancel**）→ `--apply` → refresh + 結果表示。
  exit 1 = 「候補なし」info（apply 選択肢なし）。非0 exit = warning（末尾+ログ）。ログ `reports/session_import_{dryrun,apply}_<TS>.log`。非クラッシュガード。
- 検証全PASS: py_compile / offscreen 7タブ・両ボタン・実 dry-run・Cancel で DB 不変 / DB invariance（業務6 + provisional 12/79/79）/
  MISANO 12 prov runs・Report v2 provisional guard 無回帰。live apply は対象なしのため未実施（次 race weekend で実地）。
- **★運用上の発見**: 未フィルタ dry-run で **歴史的 pending 160 outing/1249 laps**（Round7 以前・既に final 取込済みイベント）が候補化。
  既定 Cancel で誤投入は防止されるが、**Apply すると final 済みデータの provisional 重複投入となるリスク** →
  次 race weekend 前に queue 歴史的 pending の整理（skipped 化 or イベントフィルタ既定）を別タスクで推奨（レポート §4）。

---

## 63. Supabase v2 schema revision — readiness 7点反映（2026-07-07 Claude Code・ローカルSQLのみ・本番未実行）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-07）。§61 readiness の 7 findings を反映した改訂DDLをローカル作成。
**Supabase 本番接続・実行ゼロ・原本SQL不変・正本DB read-only**。
成果物 = `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707_revised.sql` + `reports/supabase_v2_schema_revision_20260707.md`。

- **7/7 修正**: ①v_sync_runs の rs.* 廃止・run_setup 30列明示（重複列0を機械確認）②weather/temp を runs へ（sessions は代表値注記）
  ③statistic CHECK = avg/mean/min/max/p95/count/duration・'peak' 禁止（新22=p95/凍結=max 対応表）④phase CHECK に ph12
  ⑤sha256→manifest_hash（+nullable content_sha256）⑥runs.source 追加 ⑦metric_versions テーブル追加（local 32行受け皿）。
- 追加確認3点反映: result_laps = race_lap_detail 単一供給源 COMMENT + source_table 列 / n<5・n<10 は行を作らない（0≠NULL）/
  compat view は final-only 既定 + `_with_provisional` opt-in ×2。
- 逸脱（意図的）: race_results sector1-3 は 7 findings 外のため未追加（G1 前の判断事項として記録）。
- 検証: stdlib 構造チェック（47文・BEGIN/COMMIT 単一・view 重複列0・'peak' 0・ph12 有）。実 parse は G1 の Supabase staging で実施。
- **次ゲート = G1 `Supabase v2 schema GO`（DDL 実行）** → G2 初回 sync → G3 view 切替 → G4 整理（§61b どおり）。

---

## 64. Round7 full integration readiness / finalization gate（2026-07-07 Claude Code・Phase A・read-only・GO待ち）

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-07）。**GO 不要の Phase A readiness**（canonical mode=ro・scratch は /tmp のみ・書込ゼロ）。
レポート = `reports/round7_full_integration_readiness_20260707.md` / mapping = `..._mapping_20260707.csv` / plan = `..._plan_20260707.sql`。

### 64a. 測定 / source completeness
- 業務 runs/laps/lap_suspension=275/1202/1202（ROUND7=0）・race_results ROUND7=74・pdf_v2_staging ROUND7=1094 PASS・
  provisional 12/79/79（event_key `20260612-ROUND7-JA52`）・queue ROUND7 = awaiting_gate12/failed7/skipped14 + report pending1。
- source 完備: 2D 33 outing / Report xlsx / Original 13 ROUND7/MISANO 行（full setup 有）/ 6 Result PDF。

### 64b. ★scratch rebuild 検証（build_master_db `--all --out /tmp` exit 0・受入ゲート |2D−PDF|>1.5s = 0件 PASS・BLOCKER なし）
- **final = 13 runs / 77 laps ≠ provisional 12/79（clean match でない）**。差分は全て build_master_db の Original マージ仕様（全ラウンド共通）:
  ①WUP2: 2→1 run・**−2 laps**（WUP2-02 outing が Original WUP2 M=1 により drop）
  ②RACE1 & RACE2: 各 +1 run（0-lap の Original-only R2＝Original 重複行・実レース setup C106 は 2D 保持の R1 でなく R2 に載る）
  ③run_id は PROV_ prefix が外れ・setup + wheel-force `wf_*_n` 列が final で充填（provisional では NULL）・**best_lap_s は全マッチ run で一致**。
- **決定論ゲート安全**: scratch の非ROUND7 laps=1202・canonical と byte 一致（差分0）。remap されるのは既存 `NA_MISANO_RACE1/2_JA52_R1`（0-lap placeholder）2件が ROUND7 R2 へ入るのみ＝lap 損失なし。final 総計 runs 286/laps 1279。
- reconcile: Original 重複キー RACE1/RACE2×2（構造的・全サーキット共通）・WUP2 2D=2/Orig=1・RACE 2D=1/Orig=2。ROUND7-fatal な unmatched/mismatch なし。

### 64c. 推奨 = **条件付き GO**（canonical 健全・build/gate PASS・既存データ保護）
- Tatsuki が3構造事実を承認すれば GO: (1) final 13/77 ≠ provisional 12/79 (2) WUP2-02 の 2 laps drop (3) RACE Original-only R2 + setup 行割当。
- 承認可（=標準挙動として受容）→ **`Round7 final integration GO`**。否なら NO-GO（Original/build 修正が先）。
- finalization 計画（GO 後）: backup → scratch rebuild → 決定論ゲート（既存1202不変 + ROUND7 が scratch と一致）→ cutover_db.py →
  provisional clear（DELETE by provisional_event_key）→ Workbench final 表示確認（12→final 表示・重複なし）→ DB Master refresh → Supabase v3 sync+audit。
  Supabase v2 は G1 別ゲート（対象外）。rollback 各段。リーダー独立検証: canonical 275/1202/1202/866・prov 12/79/79 不変を再確認。

### 64d. ⛔ cutover 方式 data-loss 欠陥検出 → 実行停止（2026-07-07・GO 後の安全確認）
- **`Round7 final integration GO` 受領後、実行前に cutover_db.py を確認 → 重大欠陥を発見し canonical 無変更で停止**。
- cutover_db.py は master(2D再ビルド) を丸ごとスワップ + PRESERVE テーブルのみ旧DBから引継ぐ。PRESERVE = problem_log/setup_decision_log/
  problem_library/round_brief/lap_observation_log/race_results/pdf_lap_times/best_worst_pairs（§37-§44 追加より前の古い状態）。
- **cutover 実行で消失**: `pdf_lap_times_v2_staging`(7710・§38) / `race_lap_detail` VIEW(§40・**Workbench Race Analysis が RACE_LAP_SRC 依存→破損**) /
  品質・Phase2A（source_file_registry 405/import_queue 397/data_quality_log/analysis_run_log/metric_version_log 32）。
- readiness §64 は runs/laps/lap_suspension の決定論ゲートは検証したが cutover のテーブル保全は検証漏れ。
- **安全代替**: Option A = ROUND7-only targeted insert（§44 追加のみ方式・全テーブル保全・placeholder NA_ 2件のみ置換）/
  Option B = cutover_db.py PRESERVE 更新 + cutover 後に VIEW/staging 再適用。→ Tatsuki 方式判断待ち。

---

## 65. ★Round7 provisional → final 本データ化（targeted insert・Option B / Round7-only build）— 2026-07-08 Claude Code

Tatsuki 指示「システムを正しい状態に保ち Round7 provisional を本データにする最適作業」= GO 相当。§64d の targeted-insert 方式を実行。
**スコープ = DB + Workbench のみ**（final 反映 + provisional クリア）。DB Master / Supabase / origin push は対象外・別GO据え置き。
readiness = `reports/round7_targeted_insert_readiness_20260708.md` / 実行 = `reports/round7_targeted_insert_apply_20260708.md`。

### 65a. 方式 = Option B（Round7-only build）— iCloud offload 対応
- full `--all` rebuild は非Round7 1202 ラップの決定論ゲートに全 DATA 2D event フォルダを要するが、移動先ネットワークで **iCloud が
  DL を停止**（event 21フォルダ/約1.3GB dataless・0 MB/s）→ full rebuild 実行不能。Tatsuki 選択（AskUserQuestion）で **Round7 のみビルド**。
- **MISANO は ROUND7 単独サーキット** → `build_all` の cross-event state（rcs_events/pool 消費）が MISANO キーに関して Round7 内で完結。
  よって Round7 だけを同一ロジックで処理すれば Round7 行は full rebuild と byte 等価（下記 cross-source で実証）。
- コード変更（追加のみ・default 挙動不変）: `build_master_db.py` の `build_all(out_db, only_events=None)` にイベントフィルタ + CLI `--round ROUND7`。

### 65b. ビルド + 等価性検証（全 PASS）
- `build_master_db.py --all --round ROUND7 --out /tmp/ts24_r7only.db` → 受入ゲート |2D−PDF|>1.5s **0件**・Round7 **13 runs/77 laps/77 lap_suspension**。
- **cross-source ゲート**（`apply_round7_targeted_insert.py --scratch-scope round7`）:
  - **lap 2D値（lap_time_s/susf/susr/f_dive_spd/r_dive_spd）vs provisional: 77/77 完全一致**（provisional は session_extract_staging＝別コードパス由来 → 2D 抽出同一を実証）。
  - best_lap vs provisional 11/11・vs §64 --all mapping 11/11（＝前日 full rebuild と等価）・vs race_results 公式 RACE1 Δ0.006/RACE2 Δ0.015s（telemetry対公式・想定内）。
- **content ゲート**: setup(f_spr_l) 13/13・wheel-force 77行・best §64 一致・0-lap R2 2件存在。

### 65c. final 反映（canonical 書込）
- backup `02_DATABASE/_backup_round7_targeted_20260708_200025/`（WAL-safe: main+sidecar）。
- `apply_round7_targeted_insert.py --scratch-scope round7 --apply`: placeholder `NA_MISANO_RACE1/2_JA52_R1` **DELETE** + Round7 **13/77/77 INSERT**（明示列・scratch から `WHERE round='ROUND7'`）。
  事後 assert（PROTECTED COUNT 不変・totals 286/1279/1279・Round7 13/77/77・content 再検証）全通過 → COMMIT。
- **独立検証（mode=ro）**: runs **286** / laps **1279** / lap_suspension **1279**・race_results 866。Round7 13/77/77・placeholder 残 0・setup 13/13・WF 77。
  **PROTECTED 全不変**: pdf_lap_times_v2_staging 7710 / source_file_registry 405 / import_queue 397 / data_quality_log 1340 / analysis_run_log 11 /
  metric_version_log 32 / pdf_lap_times 7613 / race_lap_detail VIEW 12763・**非Round7 laps 1202 保持**。
- ハング対処: 初回 apply が `wal_checkpoint(TRUNCATE)` で iCloud ロックによりハング（2分 timeout・canonical は中断ロールバックで無変更）→ **PASSIVE checkpoint** へ変更し解消。

### 65d. provisional クリア（Workbench 二重表示回避＝正しい状態化）
- backup `02_DATABASE/_backup_round7_provclear_20260708_200609/`。
- event_key `20260612-ROUND7-JA52` を 3 provisional テーブルから DELETE: **79/79/12 → 0/0/0**・業務テーブル不変・Round7 runs=13 を assert。

### 65e. Workbench offscreen smoke（PASS）
- MainWindow **7タブ**構築 OK（overlay SQL・race_lap_detail VIEW とも finalization 後に正常）。
- overlay 総 1279 行・**provisional 0 行・PROV_ 0 件（⏳prov 重複なし）**・Round7 = **final 11 run**（テレメトリ有・`20260612_ROUND7_MISANO_*`）表示・race_lap_detail ROUND7 1094。
- **GUI 最終目視は Tatsuki ローカル**（🦾 Suspension/Posture・Race Analysis で MISANO/JA52 final 確認）。

### 65f. 受容した標準挙動 / rollback / スコープ外
- **WUP2 最速ラップ 98.045 が final から落ちる**（採用 WUP2-R1=98.160・4laps / drop WUP2-R2=98.045・2laps＝build_master_db の Original マージ top-lap 選択・全ラウンド共通）。Tatsuki 指示スコープ内として受容。
- placeholder 2件は ID 継承でなく件数整合（DELETE 2 / INSERT 13 のうち 0-lap R2 が 2）。
- rollback: final=`_backup_round7_targeted_20260708_200025/` 復元 / provisional clear=`_backup_round7_provclear_20260708_200609/` 復元。
- スコープ外（別GO）: DB Master(Excel) refresh（`refresh_db_master_safe.py`・Round7 は今 2D由来テーブルに入ったため反映され得る）/ Supabase sync / origin push。
- 変更: `build_master_db.py`（event filter 追加のみ）/ `apply_round7_targeted_insert.py`（round7 scope + cross_source_gate + PASSIVE checkpoint + WAL-safe backup + busy_timeout）。新規: `reports/round7_targeted_insert_apply_20260708.md`。

---

## 66. Report v2 feedback Phase A read-only 監査（P0 Sus_Speed = phase-window artifact）— 2026-07-08 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-08）+ 指示書 `reports/report_v2_feedback_code_instruction_20260708.md` + フィードバックノート `08_REPORT_NOTES/2026-07-08_Report_Feedback.md`。
**GO 不要の read-only 監査**（DB `mode=ro` のみ・**canonical 書込/metric定義変更/抽出ロジック変更/サイレントfilter=一切なし**・コード/Excel/Supabase 無変更・push なし）。
成果物 = `reports/report_v2_feedback_audit_20260708.md`（指示書7セクション全網羅）。マルチエージェント（Investigate 5次元 + Verify 3敵対検証・8エージェント・0エラー・0/3 反証失敗）。

### 66a. P0 Sus_Speed 逆転 = phase-window artifact（valid_under_definition・計算バグではない）
- **逆転は実在かつ systemic**: `apex_f_dive_spd_avg > brk_f_dive_spd_avg` が全DB **1111/1146=97%**・median 2.11×。全サーキット（MOST100%/JEREZ99%/PHILLIP98%/BALATON97%/ARAGON96%/ASSEN96%/**MISANO85%**＝最弱）で成立＝MISANO 固有ではない。
- **根本原因**: `FULL_BRAKING`（`BRAKE_FRONT∈[9,20]` **かつ** `SUSP_FRONT∈[90,130]`）はフォークが既に深く沈んだ準定常 dwell（phase-mean `brk_susf`≈107mm・bottom≈122mm）を密 sampling（`fullbrk_count`≈2000-3100）し、本当の高速ダイブ過渡（フォークが `SUSP_FRONT<90` で `30→90mm` へ急降下・ブレーキ ramp `<9bar` 中）を **二重に構造除外**。`MID_CORNER`（`SUSP_FRONT∈[50,100]`・活発 mid-stroke）は圧縮 v>0 の conditional mean が高い。
- **trace 再構成**（build_master_db を import・生 2D 再 resample・`vf=np.gradient/dtg`）で DB 値を byte-exact 再現（FP R1 L2=63.2/189.6 等）→ compute バグ無し。正圧縮 speed mass の **82–95% が `SUSF<90`**（マスク外）、`FULL_BRAKING` 内は 2–5% のみ。
- **決定的 discriminator**: **avg は逆転するが peak は逆転しない**（`brk_f_dive_spd_peak` mean 471.8 > `apex_f_dive_spd_peak` mean 345.4・apex>brk は 31%）→ 符号/単位/ノイズ/物理いずれでもなく **averaging window に起因**と確定。
- 排除された代替仮説（Verify 3敵対検証すべて反証失敗）: sign/unit bug（common-mode・両 phase 同一 `vf`+`v>0`）/ np.gradient ノイズ（peak も膨らむはずだが逆転せず・密 window の brk がむしろ上振れするはず）/ 物理（braking が最速 spike を保持）/ MISANO quirk（systemic・MISANO は最弱）/ report mislabel（`suspension_report.py` L48-54 と Workbench `_PHASE_SPD` L3093-3099 が一致）。
- sign 自己整合確認: 大 mm = 圧縮（`brk_susf`107>`apex_susf`75>`ce_susf`20mm・lap_max 124mm）・dive=v>0。unit=非校正 grid 微分 mm/s（相対 damping-speed index・車速 km/h と混同禁止・`SPEED_NOTE` L59）。avg=mean(n≥5)/peak=p95(n≥10)（L327-334）。

### 66b. 副次発見
- **peak reducer 非対称**: 凍結 legacy `brk_f_dive_spd_peak`=`max()`（L309）だが新22列 peak=p95（L333）→ report の cross-phase「peak」バーは max-vs-p95＝apples-to-oranges（avg 比較は両者 mean なので無影響）。
- **Öhlins 照合**: `04_REFERENCE/FKR-1xx-setting-library-version-1.0.pdf`（前フォーク）+ **発見** `04_REFERENCE/TTX36-GP-v3.6.xlsm`（Öhlins TTX36 GP rear-shock Setting library Excel＝実質「Setting Bank」）。どちらも **Force[N] vs shaft-velocity[m/s]・Compression/Rebound 別スタック**。数値 low/high-speed 閾値の明示なし。TS24 の Sus_Speed は **観測位置の travel-rate（非校正相対 index・interp grid 微分・位置センサ由来）** で Öhlins（校正済み力の伝達関数・dyno shaft）とは **別物・非直接比較**。対応するのは方向 convention のみ（dive↔Compression / reb↔Rebound）。**Öhlins low/high-speed 用語への rename は非推奨**（意味が異なる）。file 名「Ohlins Setting Bank」literal は無し・`NIX 30` workbook は不在。
- feedback 項目1（F_Sus が R_Sus を潰す視認性）= **small multiples 推奨**（dual-Y は誤読リスク・normalized は絶対 mm を隠す）。項目2（slow lap）= 決定論 **report-only** filter（`is_outlap` + session median 比外れ値）+ **page-2 開示テーブル必須**（適用 filter・除外 lap 一覧・理由）。

### 66c. 推奨（2段階・各明示GO要・実装は Phase A では未着手）
- **分類 = metric label / phase-window definition issue**（no-issue でも sign/unit/extraction defect でも report-mapping mislabel でもない）。
- **Tier1（report-only・DB/抽出 無変更・推奨先行）**: ① `brk_f_dive_spd_avg` を「ブレーキ時のダイブ速度」と提示しない・phase 窓を明示する再ラベル（例 "Braking F-Dive (deep-stroke/settled)"）② peak バーの reducer 整合（表示時 p95 化 or 注記）③ F/R position を small multiples ④ slow-lap filter + page-2 開示 ⑤ 非校正相対 index 注記維持・Öhlins 用語不採用。→ GO 文言 `Report v2 feedback report-only GO`。
- **Tier2（抽出指標追加・追加のみ・凍結列不変）**: 真の dive-in rate が必要なら、`SUSP_FRONT<90` で上昇中かつブレーキ ramp（≈0.3-9bar・`dSUSP_FRONT/dt>0`）を key にした **ブレーキ onset dive 新列**を §44 と同じ非破壊追加方式で新設。→ GO 文言 `Suspension speed extraction fix GO`。
- **非推奨**: `FULL_BRAKING` マスクの in-place 変更（凍結 legacy 列と全履歴値を silent に変える）。Phase A 中の定義変更/DB書込。

### 66d. スコープ外（禁止遵守）
- canonical 書込・provisional clear・Round7 targeted insert 変更・metric 定義変更・抽出ロジック変更・サイレント report filter・DB Master refresh・Supabase sync/DDL・origin push＝**すべて未実施**。
- 生 2D は再構成対象 MISANO outing について読取可（iCloud offload なし）・再構成は 120s ガード内。
- 新規: `reports/report_v2_feedback_audit_20260708.md`。変更: `CLAUDE.md` §66（+ Obsidian log/CURRENT_STATE/AI_HANDOFF/INBOX Result）。

---

## 67. Report v2 feedback Tier1 report-only 実装（Tatsuki `Report v2 feedback report-only GO` 受領）— 2026-07-08 Claude Code

§66 audit を受け、Tatsuki が Phase B の **Tier1（report-only）のみ**を承認（AskUserQuestion 回答＝`Report v2 feedback report-only GO`）。
**変更 = `suspension_report.py` のみ**（canonical DB / 抽出ロジック / `build_master_db.py` / `ts24_workbench.py` / DB Master / Supabase / origin push は無変更）。Tier2（抽出指標追加）は未承認＝据え置き。

### 67a. 実装（suspension_report.py・4点）
1. **Sus_Speed 再ラベル（P0 の誤解防止）**: phase-speed パネル題に窓を明示（`PHASE_SPEED_REGION`）= Braking `deep-stroke / settled` / Apex `mid-stroke` / Exit `corner-exit (sparse)`。Compare 表ヘッダも `Brk F-Dive [idx·deep]` / `Apex F-Dive [idx·mid]`。`SPEED_WINDOW_NOTE`（"MEAN velocity within each phase window … NOT the peak brake dive-in rate … do NOT read Apex>Braking as 'the front dives faster at apex'"）を phase summary / lap-by-lap speed / Data limits に表示。
2. **peak reducer 注記修正**: 旧 "peak = p95"（brk は実は凍結 MAX）→ `PEAK_NOTE`「peak 列は非表示・cross-phase 比較不可（brk=legacy MAX vs 他 p95）」。peak バーは元々未描画のため注記のみ修正。
3. **F/R position を small multiples**: `chart_phase_summary` を 1×2 → 1×3（F position / R position 独立Y / F&R speed）に分離 → feedback①（F が R を潰す）を解消（R が独立軸で可読）。
4. **slow/out-lap filter（report-only・page-2 開示）**: 新 `apply_lap_filter`（決定論・DB書込なし）= out/in ラップ（`_is_outlap==1`・列があるとき）+ session 中央値 × `SLOW_LAP_FACTOR`(1.07) 超の slow lap を除外。全除外は退化ガードで無効化。`lap_filter_note` で **Data Quality ページ（page 2）に「適用 filter・除外 lap 一覧・理由」を必ず開示**。`build_report_v2`/`build_report_pdf` に `lap_filter=True` kwarg（既定 ON・後方互換・CLI `--no-lap-filter` で無効化可）。

### 67b. 検証
- py_compile PASS。sample 生成（final MISANO JA52・全 session）= `reports/pptx/suspension_report_v2_MISANO_JA52_ALL_20260708_TIER1.pptx/.pdf`。filename が `_ALL_`（`_PROVISIONAL_` でない）＝§65 finalization 後の final data・provisional 自動検出も正常。
- PDF 目視（Read）: page2 = **12 out-lap 除外 + 開示テキスト表示** / phase summary = **F/R 別パネル独立軸で R 可読**・速度題に region / compare 表 = `[idx·deep]`/`[idx·mid]` / Data limits = 誤解防止注記 + peak 注記修正。
- 後方互換 smoke: Workbench 風 df（`_is_outlap` 無し）で `apply_lap_filter` が slow-lap 規則のみで動作（kept 65/excluded 12）・`build_report_v2` 生成 OK・filter OFF 経路 OK・offscreen MainWindow 構築 OK。**GUI 最終目視は Tatsuki ローカル**（Workbench 📄 Create Report v2・既定で filter ON + 新ラベル）。

### 67c. rollback / スコープ外
- rollback: `suspension_report.py` を revert（DB/Excel/Workbench 無変更のため他に影響なし）+ sample 削除。
- スコープ外（未実施）: **Tier2 抽出指標追加**（`Suspension speed extraction fix GO` 待ち）/ canonical DB write / `build_master_db.py` 変更 / `ts24_workbench.py` 変更 / DB Master refresh / Supabase / origin push。
- 変更: `suspension_report.py`。新規: sample pptx+pdf / `CLAUDE.md` §67（+ Obsidian log/CURRENT_STATE/AI_HANDOFF/INBOX）。

---

## 68. Round8-only provisional guard（P0・Round8 以外を Apply 不可に）— 2026-07-09 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-09 P0）+ 指示書 `reports/round8_only_provisional_guard_code_instruction_20260709.md`。
Tatsuki要求「必ずRound8のデータだけをPrevisionalで表示、Report作成」を **人手注意でなくコードで** 担保（GO gate なし＝指示が承認・forbidden で canonical write/queue/DB Master/Supabase/commit/push は禁止）。
方式 = **`--required-round` フラグ**（指示書が「cleaner」と認めた代替）+ **2層 fail-closed** + Workbench UI ガード。**変更 = `session_extract_staging.py` + `ts24_workbench.py`**（DB/queue/Excel/Supabase 無変更）。成果物 = `reports/round8_only_provisional_guard_apply_20260709.md`。

### 68a. 実装
- `session_extract_staging.py`: 新 `--required-round <ROUND>` / `enforce_apply_guard`（**Layer1**・`main` で `run_pipeline` より前）= ①`--apply` は `--event` 必須（無→`sys.exit(4)`）②`--required-round RR` と `--event` の round(`EVENT_RE`) 不一致→exit 4 / `do_apply` 冒頭に候補単位 **Layer2**（backup/DDL/INSERT の前・event 無 or round 不一致→return 4）。exit 4 を docstring に追記。
- `ts24_workbench.py` `ImportQualityTab`: `QInputDialog` import / `REQUIRED_ROUND="ROUND8"`（次ラウンドで更新）/ `_guess_event_key`（`DATA 2D` から ROUND8 event 推測して pre-fill）/ `_run_import` = subprocess 前に event 入力必須（cancel/空/非ROUND8 は拒否・DB無変更）→ dry-run/apply 両方に `--event <ev> --required-round ROUND8` 付与 → 確認ダイアログに対象 event 明示（「この event のみ・ROUND8 限定」）。

### 68b. 検証（全 PASS）
- py_compile 両ファイル PASS。CLI: `--apply`(event無)=exit4 / `--apply --event ROUND7 --required-round ROUND8`=exit4 / dry-run ROUND7 同=exit4 / `--event ROUND8 --required-round ROUND8` dry-run=exit1（候補未登録）/ `--apply` 同=exit1（書込なし）。
- Workbench offscreen（`QInputDialog`/`QMessageBox`/`subprocess.run` monkeypatch・`_run_import`）: valid ROUND8=**1 call** w/ `--event…--required-round ROUND8` / 空=**0 call**+warn / 非ROUND8=**0 call**+warn / cancel=**0 call**。`REQUIRED_ROUND=ROUND8`・`_guess_event_key`→`20260710-ROUND8-JA52`（folder 実在）。
- **無書込証明**: 業務+provisional 件数 before==after（runs286/laps1279/lap_suspension1279/race_results866・provisional 0/0/0）＝全 guard-fail で無書込を実証（Layer1 は run_pipeline 前・Layer2 は backup 前）。

### 68c. 残・rollback・スコープ外
- **実データ apply 検証は Round8 初回 session 到着後**（`20260710-ROUND8-JA52` folder は存在するが Session Scan 未登録＝queue 候補 0）。次ラウンドは `REQUIRED_ROUND`/`--required-round` を更新（ガードは削除しない）。GUI 目視は Tatsuki ローカル。
- rollback: `git checkout -- session_extract_staging.py ts24_workbench.py`。
- スコープ外（forbidden 遵守）: canonical write / historical-pending apply / Round8 final化 / queue cleanup / DB Master / Supabase / commit・push / folder watcher。
- 変更: `session_extract_staging.py` / `ts24_workbench.py`。新規: `reports/round8_only_provisional_guard_apply_20260709.md` / `CLAUDE.md §68`。

---

## 69. Round8 Session Import "No Candidates" hotfix（P0・現地復旧診断）— 2026-07-10 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-10 P0）+ 指示書 `reports/round8_session_import_no_candidates_hotfix_code_instruction_20260710.md`。
Tatsuki が Round8 2D data を保存したが Workbench `Session Import (staging)` が `新規取込候補はありません（queue pending 0）` を表示（現地で復旧手順不明のまま詰まる）。
**変更 = `ts24_workbench.py` のみ**（`ImportQualityTab`・診断改善 + 安全な Scan 復旧導線）。`extraction_scan.py`/`session_extract_staging.py` は無変更＝**Round8 guard §68 完全保持**。DB read-only（業務テーブル before==after 不変・実 Scan/Import 未実行）。成果物 = `reports/round8_session_import_no_candidates_hotfix_20260710.md`。

### 69a. Root cause
- `DATA 2D/20260710-ROUND8-JA52` はディスク実在（`FP-JA52-01/02.MES`・`.DDD`/`.LAP`/`.HED` 完備・`discover_outings`=2 outing nested）だが `source_file_registry`/`import_queue` に Round8 行 **0**。
- `session_extract_staging.py`（Session Import 実体）は **filesystem 直読でなく `import_queue` を読む** → Session Scan 前に Import すると候補0（exit 1）。＝データ欠損でもバグでもなく「未Scan（ワークフロー順序未実行）」。従来UIが復旧導線を出さなかったのが唯一の問題。

### 69b. 実装（`ImportQualityTab`・3点）
- 新規 `_looks_unstable(ev_dir)`: 半端コピー/iCloud placeholder/コピー継続中を **name+stat のみ**で検出（内容非読取＝iCloud DL 非誘発・§24a）。`.icloud`/`._`/`.~`/`.partial`/`.tmp`/`~$` + mtime<30s を計数。
- 新規 `_diagnose_zero_candidates(ev)`（read-only・管理テーブル SELECT のみ）: `(case,title,message,offer_scan)` を返す。case = `folder_missing`（folder 無）/ `not_scanned`（folder有・registry/queue 0 → Scan 誘導）/ `unstable`（未安定サイン併記）/ `no_pending`（Scan済だが pending 0 = 既取込）/ `unknown`。
- `_run_import` の exit==1 分岐を差替: 原因別メッセージ + `offer_scan=True` 時は **「Session Scan を実行」ボタン**（押下で既存 `_run_scan()`=`extraction_scan.py`・管理テーブルのみ実行 → 「Scan 後に再 Import」案内）。**auto-apply しない**（provisional 書込は従来どおり人手 Apply + event guard 経由のみ）。

### 69c. 検証（全 PASS）
- py_compile（ts24_workbench/extraction_scan/session_extract_staging）PASS。
- `extraction_scan.py --dry-run --min-age 0` → 検出 408（2D=315 Round8含む）・**DB 書込なし**（dry-run 後 registry/queue Round8=0）。
- offscreen smoke: 7タブ無回帰 / `_diagnose_zero_candidates('20260710-ROUND8-JA52')`=not_scanned・offer_scan=True / 存在しない event=folder_missing / `_looks_unstable`(実dir)=""（安定） / `_run_import`(exit1 monkeypatch): 「閉じる」→scan呼出0・「Session Scan を実行」→scan呼出1。
- **業務+provisional+Round8管理行 before==after 不変**（runs286/laps1279/lap_suspension1279/race_results866/pdf_lap_times7613・prov0/0/0・reg/queue Round8=0）。GUI 最終目視は Tatsuki ローカル。

### 69d. 現地復旧手順 / スコープ外
- 復旧: `📥 Import / Quality` → `🔍 Session Scan`（管理テーブルのみ）→ `⬇ Session Import` → event `20260710-ROUND8-JA52`（自動 pre-fill）→ dry-run 確認 → Apply（既定 Cancel）。候補0でも未Scan なら復旧導線が自動表示。
- rollback: `git checkout -- ts24_workbench.py`。
- スコープ外（forbidden 遵守・未実施）: Round8以外 import / event filter なし apply / Round8 final化 / canonical write / historical queue cleanup / DB Master refresh / Supabase / commit・push / folder watcher auto-apply。**実 Scan/Import は現地 iCloud 目視運用のため Tatsuki ローカルに委譲**（データ安定性は確認済）。
- 変更: `ts24_workbench.py`。新規: `reports/round8_session_import_no_candidates_hotfix_20260710.md` / `CLAUDE.md §69`。

---

## 70. Round8 Donington circuit 正規化 readiness（P0・final化前・read-only）— 2026-07-10 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-10 P0・§69 hotfix 後 Codex/Tatsuki が formal 化）+ 指示書 `reports/round8_donington_circuit_normalization_code_instruction_20260710.md`。§69 で私が FOR_CODEX へ申し送った circuit 正規化課題の read-only readiness。**`circuit_canon` 変更・provisional 書換・run_id/lap_id 変更・finalization 一切なし**（DB `mode=ro`・業務テーブル不変）。成果物 = `reports/round8_donington_circuit_normalization_readiness_20260710.md`。GO 文言 = `Round8 Donington normalization GO`。

### 70a. 実測（read-only）
- provisional: **2 runs/21 laps/21 lap_suspension**・circuit=**`DONINGTONPARK`**・run_id `PROV_20260710_ROUND8_DONINGTONPARK_FP_JA52_R1/R2`。業務 286/1279/1279/866 不変。
- canonical: `TRACK_M["DONINGTON"]=4023`・`DONINGTONPARK` キー無し（`.get`=None）。業務テーブルに `DONINGTONPARK` **0件**（未汚染）。race_results DONINGTON 168 行=**全 `data_scope='COMPANY'`（BSB）**。**runs/laps/lap_suspension に data_scope 列は無い**（COMPANY/WorldSSP は round+circuit で分離・data_scope は race_results のみ）。
- 根本原因: Report DAY1 CIRCUIT=`"DONINGTON PARK"` → `circuit_canon`（`build_master_db.py:71-76`）が空白除去で `DONINGTONPARK`。辞書に `BALATONPARK→BALATON` はあるが **`DONINGTONPARK→DONINGTON` が欠落**。`.line` 不在・HED=`Donington`（未使用・event_circuit は Report 優先）。

### 70b. 修正設計（GO 後・追加のみ）
- **一点修正で両経路解決**: `session_extract_staging.py:385-388` が `bmd.circuit_canon(bmd.circuit_from_report(...))` を使用＝**provisional と finalization が同一関数共有** → `build_master_db.circuit_canon` に `"DONINGTONPARK":"DONINGTON"` 追加で両方 `DONINGTON` 化。
- **circuit_canon は約7ファイルに重複**（全て BALATONPARK 有・DONINGTONPARK 無）: 必須=`build_master_db.py:71`＋`cutover_db.py:34`、一貫性=`reconcile_2d_vs_original.py`/`corner_phase_analysis.py`/`lap_overlay_extractor.py`/`lap_suspension_stats.py`/`parse_2d_channels.py`（後者群は HED 由来で既に DONINGTON・防御的追加）。将来課題=共有モジュール集約（別タスク）。
- **apply = provisional 再生成推奨**（in-place UPDATE で run_id/lap_id 書換は非推奨）: backup → Round8 provisional DELETE（event_key）→ fix 後 `session_extract_staging.py --apply --event 20260710-ROUND8-JA52 --required-round ROUND8` 冪等再取込で DONINGTON 生成。§65d と同型。
- 検証ゲート（finalize 前必須）: provisional circuit=DONINGTON・run_id に DONINGTONPARK 0・counts 2/21/21・業務不変 / `TRACK_M.get("DONINGTON")=4023` で is_outlap ④復活 / scratch `build_master_db --round ROUND8` 受入ゲート0・circuit=DONINGTON。

### 70c. 運用推奨 / スコープ外
- **Round8 finalization は本 fix + 検証完了まで実施しない**（放置で canonical に DONINGTONPARK 確定＝二重サーキット化・is_outlap ④ degrade）。fix 前に QP/RACE が届けば DONINGTONPARK になるため、**FP のみの今 fix するのが最小コスト**。追加分は fix 後に一括 re-normalization。
- 別途: Tatsuki ノート `2026-07-10　Update idea.md`（bike_geometry_master/setup_snapshots/ΔGeometry 等の将来 DB 設計案）を確認・記録（inbox タスク化されておらず実装対象外・将来設計候補）。
- スコープ外（禁止遵守・未実施）: circuit_canon 変更 / provisional 書換 / run_id・lap_id 変更 / Round8 final化 / canonical write / DB Master / Supabase / commit・push / historical queue cleanup / Round8-only guard 変更。
- 新規: `reports/round8_donington_circuit_normalization_readiness_20260710.md` / `CLAUDE.md §70`。変更なし（read-only）。

---

## 71. ★Round8 Donington circuit 正規化 apply（Tatsuki `Round8 Donington normalization GO` 受領）— 2026-07-10 Claude Code

§70 readiness を受け Tatsuki が本セッションで **`Round8 Donington normalization GO`** を明示 → 実行。**circuit_canon alias 追加（7ファイル・追加のみ）+ Round8 provisional 再生成**（`DONINGTONPARK`→`DONINGTON`）。**canonical 業務テーブル書込なし・Round8 finalization は別 GO 据え置き・commit/push なし**。成果物 = `reports/round8_donington_circuit_normalization_apply_20260710.md`。

### 71a. コード修正（追加のみ・7ファイル）
- `circuit_canon`（strip 非英数系）に `"DONINGTONPARK":"DONINGTON"` 追加: `build_master_db.py:74`（最重要＝provisional/finalization 共有）/ `cutover_db.py:39` / `reconcile_2d_vs_original.py:33`。
- `_CIRC_NORM`（空白保持系）に `"DONINGTON PARK":"DONINGTON"` + `"DONINGTONPARK":"DONINGTON"` 追加: `corner_phase_analysis.py` / `lap_overlay_extractor.py` / `lap_suspension_stats.py` / `parse_2d_channels.py`（HED 由来で従前も DONINGTON・防御的）。
- 各ファイル「対象1回・未パッチ」assert 付き置換。py_compile 8ファイル PASS。回帰 assert: `circuit_canon("DONINGTON PARK")="DONINGTON"`・他サーキット（BALATON PARK/PHILLIP/ARAGON/MISANO…）不変・`TRACK_M.get("DONINGTON")=4023`。

### 71b. provisional 再生成（regenerate 戦略・§70 §5.2）
- pre-DELETE backup `02_DATABASE/_backup_donington_norm_20260710_145654/`（db+wal+shm）。
- DELETE（`provisional_event_key='20260710-ROUND8-JA52'`）2/21/21→0/0/0（同一接続で業務不変 assert 後 commit）。
- `session_extract_staging.py --apply --event 20260710-ROUND8-JA52 --required-round ROUND8 --include-awaiting`（`--event` filter で Round8 のみ・`--include-awaiting` で既 awaiting_gate FP2 再候補・DELETE 済で manifest hash 新規→INSERT）。circuit=DONINGTON・FP-01 PASS(15lap/90.24)・FP-02 WARNING(6lap/89.96)・**業務6 before==after assert 合格**。auto-backup `_backup_session_staging_20260710_145654/`。

### 71c. 検証（全 PASS）
- provisional: business 286/1279/1279/866/7613 不変・prov 2/21/21・circuit=`DONINGTON`(2/2)・run_id `PROV_20260710_ROUND8_DONINGTON_FP_JA52_R1/R2`・**DONINGTONPARK 残骸 0**（prov+業務 run_id/lap_id 全0）。
- scratch finalization（`build_master_db --round ROUND8 --out /tmp`・canonical 無書込）: Round8 circuit=`DONINGTON`(2/2)・DONINGTONPARK 0・runs2/laps21・**受入ゲート |2D−PDF|>1.5s=0件 ✅**→finalization も DONINGTON 生成を実証。scratch 削除。
- Workbench offscreen: 7タブ・overlay 1300行（final1279+prov21）・Donington 表記=`DONINGTON` のみ・DONINGTONPARK 0行。GUI 目視は Tatsuki。
- 補足: 再import の `circuit P10 ref=None` は canonical に DONINGTON の 2D laps 未存在のため（MISANO 初回と同挙動・§64/§65）。修正の本質効果は finalization で `TRACK_M["DONINGTON"]=4023` 解決＝is_outlap ④ 有効化。

### 71d. rollback / スコープ外
- rollback: code=`git checkout --`（7ファイル）/ provisional=`_backup_donington_norm_20260710_145654/` 復元 or DELETE→旧コード再import。業務テーブル無変更。
- スコープ外（禁止遵守・未実施）: Round8 finalization（別 GO）/ canonical write / DB Master / Supabase / commit・push / historical queue cleanup / Round8-only guard 変更。
- **次（別 GO）**: Round8 finalization は後続 session 到着後に §65 型 targeted-insert で（本正規化が前提充足）。
- 変更: `build_master_db.py`/`cutover_db.py`/`reconcile_2d_vs_original.py`/`corner_phase_analysis.py`/`lap_overlay_extractor.py`/`lap_suspension_stats.py`/`parse_2d_channels.py` + `CLAUDE.md §71`。新規: `reports/round8_donington_circuit_normalization_apply_20260710.md`。DB: provisional のみ再生成。

---

## 72. Round8 QP unregistered outings hotfix（P0・outing単位診断）— 2026-07-10 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-10 19:09 P0）+ 指示書 `reports/round8_qp_unregistered_outings_hotfix_code_instruction_20260710.md`。
Tatsuki が Round8 QP data を保存したが Workbench `Session Import (staging)` が候補0（`session_import_dryrun_20260710_190918.log` = `[STAGE] 候補 0 件`）。
**変更 = `ts24_workbench.py` のみ**（`ImportQualityTab`・追加のみ）。`extraction_scan.py`/`session_extract_staging.py` 無変更＝**Round8 guard §68 完全保持**。DB read-only（before==after 完全一致・実 Scan/Import 未実行）。成果物 = `reports/round8_qp_unregistered_outings_hotfix_20260710.md`。

### 72a. Root cause
- `DATA 2D/20260710-ROUND8-JA52` にディスク実在 **5 outing**（`FP-JA52-01/02` + `QP-JA52-01/02/03`）だが、registry/queue には **FP 2D 2行 + report 1行のみ**（QP 3本未登録）。`session_extract_staging.py` は `import_queue` を読むため候補0（exit 1）が必然。
- §69 hotfix は **event 単位 count 診断**のため `registry=3 / queue=3(pending=1)` と見え、「event に既存行あり・新規 outing だけ未登録」を特定できず **unknown に落ちていた**。→ 診断を **outing 単位の突合**へ強化。

### 72b. 実装（`ImportQualityTab`・3点・追加のみ）
- 新規 `_reconcile_event_outings(ev)`: read-only outing 突合。disk = event 直下 `*.MES` フォルダ列挙（**name+stat のみ・内容非読取・iCloud DL 非誘発**・§24a 同方針）/ registry = `file_type='2d_outing' AND file_path LIKE '%<ev>%'` の `.MES` stem / queue = `target_kind='2d_extract'` の stem + pending/awaiting_gate 計数（report 等は `non_2d_pending` に分離）。戻り値 = disk/registry/queued/pending_2d/awaiting_gate_2d/missing_from_registry/missing_from_queue/non_2d_pending。
- `_diagnose_zero_candidates` に case **`missing_outings`** 追加（`no_pending`/`unknown` より前）: missing outing 名を明示 + 突合数値 + **「report 行 pending N 件は 2D 抽出候補ではありません。Report 紐付けは provisional 2D 抽出の前提条件ではありません」** + `_looks_unstable` 併記 + `offer_scan=True`（既存 §69「Session Scan を実行」ボタン→`_run_scan()`→再Import案内へ接続・**auto-apply なし**）。
- `_load()` で `🔎 検出チェック` タブ先頭に合成行 **`detect_outing_reconcile_2d`** を挿入（read-only・`data_quality_log` へ書かない）: `disk_2d=5 registry_2d=2 queue_2d=2 pending_2d=0 awaiting_gate_2d=2 missing=QP-JA52-01, QP-JA52-02, QP-JA52-03 next_action=Session Scan（report pending 1 件は 2D 候補外）`・missing あり=**FAIL 赤表示**（report pending と 2D 候補を分離表示）。

### 72c. 検証（全 PASS）
- py_compile 3ファイル（ts24_workbench/extraction_scan/session_extract_staging）PASS。
- offscreen: 7タブ無回帰 / `_reconcile_event_outings` = missing=QP-JA52-01/02/03・awaiting_gate_2d=2・non_2d_pending=1 を正確検出 / `_diagnose_zero_candidates`=`missing_outings`・offer_scan=True・msg に QP 3本+Session Scan+report非前提を明示 / 既存 `folder_missing` 無回帰 / 検出チェック行0 = `detect_outing_reconcile_2d` FAIL。
- **DB before==after 完全一致**: runs 286 / laps 1279 / lap_suspension 1279 / race_results 866 / pdf_lap_times 7613 / provisional 2/21/21 / registry 408 / queue 400。
- Round8 guard §68 無変更（`session_extract_staging.py` の `--required-round`/`enforce_apply_guard` 存置・`extraction_scan.py` 無変更）/ §69 exit==1 配線無回帰 / 変更ファイルは `ts24_workbench.py` のみ（他の未コミット差分は §46e/§65/§71 の既記録作業）。
- **raw-2D-first 確認**: 復旧経路は disk 突合→Session Scan（管理テーブルのみ）→dry-run→人手 Apply で完結し、Report 完了 / DB Master / Supabase / canonical finalization を一切前提にしない（Race weekend 必須要件・指示書準拠）。

### 72d. 現地復旧手順 / rollback / スコープ外
- 復旧（Tatsuki）: `📥 Import/Quality` → `⬇ Session Import` → event `20260710-ROUND8-JA52` → 候補0 popup が QP 3本 missing を明示 →「Session Scan を実行」→ Scan 完了後もう一度 Session Import → dry-run 確認（Round8 QP のみ）→ Apply（既定 Cancel・別確認）。**実 Scan/Import は iCloud 目視運用のため Tatsuki ローカル実行**。
- rollback: `git checkout -- ts24_workbench.py`（DB 無変更）。
- スコープ外（forbidden 遵守・未実施）: guard 弱体化 / unfiltered import / auto-apply / Round8 final化 / canonical write / Report 完了の前提化 / DB Master refresh / Supabase sync / historical queue cleanup / commit・push / folder watcher。
- 変更: `ts24_workbench.py`。新規: `reports/round8_qp_unregistered_outings_hotfix_20260710.md` / `CLAUDE.md §72`。

---

## 73. Race weekend Workbench data ops hardening（P0・fail-closed安全レイヤー）— 2026-07-10 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-10 P0）+ 指示書 `reports/race_weekend_workbench_data_ops_hardening_code_instruction_20260710.md`。
Tatsuki 要求「Race weekend の Workbench データ作業で絶対に問題が起きないよう対策」を、operator の注意力でなく **Workbench 自身の fail-closed 安全レイヤー**で担保。
**変更 = `ts24_workbench.py` のみ**（`ImportQualityTab`・約610行追加）。`extraction_scan.py`/`session_extract_staging.py` は**無変更＝§68 Round8-only guard 完全保持**。DB 書込なし（SELECT のみ・Safety Audit の書込は `.md` 1ファイルのみ）。成果物 = `reports/race_weekend_workbench_data_ops_hardening_20260710.md`（+ audit サンプル `race_weekend_workbench_safety_audit_20260710_213504.md`）。

### 73a. 背景
- Round8 FP/QP provisional は正常反映済み（**5 runs / 39 laps / 39 lap_suspension**・canonical 286/1279/1279/866/7613/7710 不変・Round8 canonical 0・PROV 汚染 0）。
- ただし安全性は「operator が `保存→Scan→Import dry-run→候補確認→Apply→overlay→Report v2 provisional` を正しく踏む」前提に依存（§62 で歴史的 pending 160 outing の誤 Apply リスク・§69/§72 で未Scan 詰まりの実績）。live workflow は raw-2D-first・offline-capable（Report 完了/DB Master/Supabase/canonical finalization を前提にしない）が非交渉要件。

### 73b. 実装（`ImportQualityTab`・指示書§1-§6）
- **§1 🏁 Race Weekend Status サブタブ**（inner QTabWidget 先頭・等幅テキスト・🛡 Safety Audit ボタン併設）: `_race_weekend_status()`/`_render_weekend_status()`/`_refresh_weekend_status()`（`_load` から refresh）。event / raw_2d_on_disk / registered_2d / queue_2d(pending/awaiting_gate/failed/skipped) / provisional by session / canonical_round8 / report_pending(**not a blocker**) / next_action を **local disk + SQLite のみ**で表示。
- **§2 `_preapply_gate(ev, dry_stdout)`**（L7322・fail-closed 8チェック・read-only）: ①ROUND8 event 再確認 ②候補 run_id 抽出（`gate <outing>: PASS|WARNING (run_id=..., laps=N)` regex・**FAIL隔離分と report pending は構造的に候補外**・候補0=FAIL＝fail-closed）③非ROUND8/非PROV_ 混入列挙 ④date+round と ev 整合（historical pending 検出）⑤disk-registry-queue 突合（missing→「先に Session Scan」）⑥候補数>disk数 検出 ⑦canonical ROUND8=0（runs/laps/lap_suspension）⑧expected delta 算出。**FAIL 1件でも critical ダイアログで全列挙し Apply 中止（subprocess 未起動・DB 無変更）**。
- **§4 PASS 時の確認ダイアログ**: 候補 session 別一覧（例 QP: 3 outing / 18 laps）+ expected provisional delta + gate 全PASS + report pending not-a-blocker 明記（**既定 Cancel**）。複数 session 混在時は追加の明示確認（**既定 No**）。
- **§3 `_post_apply_check`**（L7405・read-only）: apply 直前 `_all_counts()`（canonical 6 + provisional 3）→ apply 後に canonical unchanged / provisional delta==expected（laps==lap_suspension）/ ROUND8 only / canonical `PROV_%`=0 / canonical DONINGTONPARK=0 / report prerequisite not required を判定。全PASS=information、FAIL=**critical（apply ログ・backup パス〔stdout grep→02_DATABASE glob fallback〕・変化テーブル明示・「これ以上操作せず Code に連絡（do not continue）」）**。
- **§5** `_reconcile_event_outings` に disk/registry/queue/missing_by_session + failed_2d/skipped_2d を追加（既存キー不変＝§72 無回帰）。`_session_of_stem()` 新設。
- **§6 `_run_safety_audit()`/`_write_safety_audit()`** → `reports/race_weekend_workbench_safety_audit_<TS>.md`（7セクション: raw disk / registry・queue / provisional / canonical invariants / 最新 scan・import ログ / next action / PASS-FAIL summary。DB は SELECT のみ）。

### 73c. 検証
- 実装セルフチェック全PASS: py_compile 3ファイル / offscreen 7タブ+inner 4タブ / status 実測 / gate 模擬（ok・非ROUND8混入・historical・空stdout fail-closed）/ audit .md 生成 / DB counts before==after。監督が `_preapply_gate`/`_post_apply_check`/`_run_import` 配線をコードレビュー（fail-closed 順序・既定 Cancel/No・例外時 DB 無変更・exit 2 時も expected delta 整合）。
- **独立検証（別エージェント・read-only）全PASS**: MainWindow **7タブ**・inner **4タブ**（先頭=🏁）/ `_race_weekend_status('20260710-ROUND8-JA52')` = disk **5**（FP2/QP3）・queue awaiting_gate **5**・provisional **5 runs/39 laps**（FP 2/21・QP 3/18）・canonical_round8 **全0**・report_pending **1**・next_action `safe / waiting for new raw 2D` / gate 正常系（模擬 `PROV_20260710_ROUND8_DONINGTON_QP_JA52_R1..R3` laps 6/6/6）= **ok=True・QP 3 outing/18 laps・expected_delta(3,18,18)**、`PROV_20260612_ROUND7_MISANO_FP_JA52_R1` 混入 = **ok=False（FAIL 2件で run_id 明示）**、空 stdout = ok=False / **DB 11テーブル before==after 完全一致**（286/1279/1279/866/7613/7710・prov 5/39/39・registry 411/queue 403）/ §68 guard 保持（`extraction_scan.py` git clean・`enforce_apply_guard`/`--required-round` 存置）。

### 73d. 運用・rollback・スコープ外
- **Workbench がブロックするもの**: 非ROUND8 Apply / 非PROV_・historical pending 混入 / 未Scan Apply / report pending の 2D 候補化 / FAIL隔離分の取込 / canonical ROUND8>0 での live intake / dry-run 不明時の見切り Apply（fail-closed）/ apply 後 canonical 汚染の見逃し。**人間確認に残るもの**: iCloud 同期目視 / Scan・Import・Apply の最終クリック（既定 Cancel/No）/ 複数 session 混在の追加確認 / invariant FAIL 時の停止判断 / Report v2 provisional 確認 / Safety Audit 読解 / finalization（別 GO）。詳細 = deliverable §1/§2。
- 現地手順: Status タブ確認 → （missing 時）Session Scan → Session Import → gate 自動評価 → Apply（既定 Cancel）→ post-apply invariant → Safety Audit（session 前/離脱前）。
- rollback: `git checkout -- ts24_workbench.py`。**⚠ HEAD(5651d97) は §44 時点のため未コミットの §48〜§72 Workbench 機能もまとめて戻る** → 本タスクのみ外す場合は §73 追加ブロックの targeted revert（DB 無変更のため DB rollback 不要）。
- スコープ外（forbidden 遵守・未実施）: canonical write / Round8 final化 / provisional clear / DB Master refresh / Supabase sync / commit・push / folder watcher auto-apply / §68 guard 弱体化 / Report 完了の前提化。**GUI 最終目視は Tatsuki ローカル**。
- 変更: `ts24_workbench.py`。新規: `reports/race_weekend_workbench_data_ops_hardening_20260710.md` / `CLAUDE.md §73`。

---

## 74. Report v2 Update（数値ラベル・All Laps Phase Trend・Lap Time Distribution）— 2026-07-10 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-10 P1）+ 指示書 `reports/report_v2_update_code_instruction_20260710.md`（Tatsuki ノート `2026-07-10　Report Update` 由来）。
Report v2 の品質改善を **report-only** で実装。**変更 = `suspension_report.py` のみ**（`ts24_workbench.py` 無変更・既存 `📄 Create Report v2` ボタンはそのまま動作）。
DB は **`mode=ro` のみ**（canonical 書込 / extraction logic / metric definition / phase mask / provisional import / Race Weekend data ops / DB Master refresh / Supabase sync / commit・push = すべて無し）。成果物 = `reports/report_v2_update_20260710.md`。

### 74a. 背景（Tatsuki 要望 4 点）
①既存グラフ上で実数値を直接確認したい ②Report 選択中の**全 Run・全 Lap** をフェーズ別に 1 グラフ文脈で見てトレンドを確認したい ③明らかに飛び出た外れ値を色/マーカーで直感的に分かるようにしたい（**除外はしない**）④既存 lap-time progression に加えて **Lap time 分布図**のページが欲しい。

### 74b. 実装（`suspension_report.py`・4 点）
- **§1 数値ラベル**: 新ヘルパー `_bar_value_labels()`（棒上ラベル・Y **+10% headroom** で軸/タイトル非重複・**12 本超でフォント縮小**・**欠損=ラベル無し、0 と表示しない**）。`chart_phase_summary` 全 3 フェーズページに配線（F/R position=`x.x` mm・speed=整数 idx）。`chart_run_overview` 既存 best/median ラベルは無回帰。
- **§2 新ページ `All Laps Phase Trend & Outliers`**: 新 `chart_all_laps_phase_trend()`・phase summary 3 ページ後 / lap-by-lap 前（**slide 7**・両 builder）。1×3 フェーズパネル・X=連続 lap 連番・色=run・lap 毎マーカー・run 毎 median 破線。**page-2 filter 後の全選択 run・全 lap（新規 silent filter なし・RUN_CHART_CAP 非適用）**。metric=**Front position family のみ**（F+R 過密のためページ注記に明記・rear は phase summary 側）。外れ値 = 新 `_iqr_bounds()`（Q1/Q3±1.5×IQR per phase・有効値≥4）→ **赤リング+`R# L# value` ラベル・cap 6/panel**（`+N more flagged`）。注記「report-only visual flags; no DB/extraction change; laps NOT removed」を図内 + PPTX ノートに焼込み。
- **§3 新ページ `Lap Time Distribution`**: 新 `chart_lap_time_distribution()`・lap-time progression 直後（**slide 9**・両 builder）。run 別 **box plot + 個別 lap 点**（**決定論 jitter・RNG 不使用**）・Y 軸 `M:SS,CC`・同 IQR ルールで outlier 赤リング+ラベル（cap 6）・**gold ★ fastest** 注記。final-only / provisional-only / mixed 3 モード動作・空 run ガード。
- **§4 PPTX/PDF parity**: 両ページを `build_report_v2` と `build_report_pdf` の**同位置**に追加。新定数 `OUTLIER_IQR_K=1.5` / `OUTLIER_LABEL_CAP=6` / `TREND_OUTLIER_NOTE` / `DIST_NOTE`。

### 74c. 検証（全 PASS）
- py_compile 2 ファイル PASS。
- サンプル = provisional Round8 `reports/pptx/suspension_report_v2_DONINGTON_JA52_ALL_PROVISIONAL_20260710_RPTUPD.pptx`（18 枚）+ `.pdf`（18 頁）（FP2+QP3 run・39→filter 後 34 lap・**auto-detect で PROVISIONAL ribbon + filename token 維持**）/ final 無回帰 `..._MISANO_JA52_ALL_20260710_RPTUPD_FINALREG.pptx`（20 枚）+ `.pdf`（`_PROVISIONAL_` 無し）。
- PNG 目視: 数値ラベル・trend ページ（5 run・median 破線・赤リング `R3 L8 114.0` 等）・distribution ページ（box+点+`R2 L3 1:35,38`・fastest ★）。page-2 filter 開示維持（除外 lap 一覧 = provisional 5 / final 12 lap）。
- **全スライド CJK=0（両デッキ）** / **DB 14 テーブル before==after 完全一致**（runs286/laps1279/lap_suspension1279/race_results866/pdf_lap_times7613/v2_staging7710・prov 5/39/39・registry411/queue403 他）。

### 74d. 制限・rollback・スコープ外
- 制限: outlier ラベル cap 6/panel / 12 本超バーはフォント 6.5pt / trend ページ=Front position のみ（ページ内開示・rear は phase summary 側）/ IQR は有効値≥4 必要 / lap-time outlier は page-2 filter 後 lap で算出（開示済）/ PPTX のみの「Run detail cap」テキストページ非対称は既存のまま（スコープ外）。**GUI クリック確認（📄 Create Report v2）は Tatsuki ローカル**。
- rollback: **`suspension_report.py` は untracked のため git revert 不可、かつ §48 以降の全 Report v2 機能を内包＝単純削除不可**。本更新のみ戻す場合は該当関数（`_bar_value_labels`/`chart_all_laps_phase_trend`/`_iqr_bounds`/`chart_lap_time_distribution`/新定数 4 つ）と両 builder 配線の **targeted revert**。DB/Excel/Supabase/Workbench 無変更のため DB rollback 不要。
- スコープ外（禁止遵守・未実施）: canonical write / extraction・metric・phase mask 変更 / provisional import・Race Weekend data ops 変更 / DB Master refresh / Supabase sync / commit・push。
- 変更: `suspension_report.py`。新規: `reports/report_v2_update_20260710.md` / サンプル pptx+pdf ×2 組 / `CLAUDE.md §74`。

## 75. Race Weekend Event Control Plane readiness（P0・Phase A・read-only）— 2026-07-11 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-11 P0）+ 設計正本 `04_SYSTEM_DESIGN/2026-07-11_Race_Weekend_Event_Control_Plane.md`。
ROUND8 live 運用中のため **Phase A read-only readiness のみ**。**DB / runtime コード / queue / provisional / Workbench UI = 完全無変更**（DB は本フェーズで一切開いていない。数値は調査エージェント3件の結果を引用）。書込 = `reports/race_weekend_event_control_plane_readiness_20260711.md` / `reports/event_manifest_schema_proposal_20260711.json`（UNEXECUTED DESIGN PROPOSAL・未配線）/ Obsidian .md のみ。実装ゲート = `Event control plane implementation GO`。

### 75a. 背景

WUP1 provisional intake 成功（ROUND8 prov 6 runs/46 laps/46 lap_susp・canonical ROUND8 0/0/0）だが、Session Scan が全データ領域を走査し registry 新規20・queue pending 19 を追加。queue pending 383 のうち **ROUND8 は 11 のみ・historical 372（97%・26イベント分散）**＝全域 Scan の副作用（detect_duplicate が log の 87%=2304行）。誤 Apply は §68/§73 で防御済だが、live scan と maintenance scan の分離・イベント定義の全工程共有が必要。調査は 3 エージェント（Workflow 棚卸し / Data-integrity / Adversarial 7 シナリオ）+ supervisor 矛盾検証（3報告は相互整合・補正1点=§62「historical 160 outing」は現在 372 に増加＝各時点で正）。

### 75b. 調査結果・敵対所見

- **Workflow**: `extraction_scan.py` = event/round filter 一切なし（scan_2d:167-174 全イベント・rglob 全域・CLI に --event 無し・queue 投入:419-432 全件＝歴史的 pending の発生源）。`session_extract_staging.py` = queue 駆動・§68 二層 guard（enforce_apply_guard:634-654 / do_apply:484-494）は健在だが **--required-round default None＝CLI 単体では非有効**。`ts24_workbench.py` = **ROUND8 実効ハードコードは :6935 `REQUIRED_ROUND` の1箇所のみ**（毎ラウンド手動書換=唯一の必須コード変更）・`_run_scan`:6857 引数なし全域 scan・`_run_import`:7683-7706 は guard 常時付与。Manifest 最小手術点は3つ（scan filter+--manifest / staging main() args 充填 / Workbench REQUIRED_ROUND manifest 化）＝**§68/§73 は入力値の出所が変わるだけで無改変**。他負債: build_master_db.py:124 rider 列挙 / KNOWN_SESSIONS 固定集合。
- **Data-integrity**: event 一次表現・event 粒度 state・遷移履歴・raw_2d_root/allowed_sessions・event 単位 fingerprint 集約は既存スキーマで**全て不足 → 新テーブル event_manifest + event_state_ledger 必要**（既存 ALTER 不要・追加のみ）。`events` テーブルは report 事後生成（ROUND8 行なし）＝manifest 不適。provisional_event_key は rider 含む＝event×rider 粒度（weekend と2階層区別要）。sha256 は 2d=64hex / report=`stat:` 短縮の二形式混在。import_queue 'done' 遷移 0 件（未実装）。data_quality_log severity 表記揺れ→新テーブルは CHECK 制約。ROUND8 の source_manifest_hash ↔ registry.sha256 一致=トレーサビリティ成立。
- **Adversarial 7 シナリオ**: ①同名同サイズ差替=**UNPROTECTED**（stat fingerprint は mtime 除外・内容差替を永久に再検出せず）②event 外 .MES=PARTIAL（**nested tier は HED ゲート免除で素通り**・copia/loose は BLOCKED）③コピー途中=PARTIAL（dataless st_blocks==0 と mtime 古い truncated 検出不能）④同一 outing 再取込=PARTIAL・**★最重要: run_no バッチ相対採番→通常運用で run_id 衝突→INSERT OR REPLACE 上書き+旧 laps 孤児化**（CLI 無検出）⑤historical pending=Workbench BLOCKED / **CLI PARTIAL**（--required-round None 素通り）⑥canonical 混入=BLOCKED-事前（残穴: COUNT assert のみ・DDL 無検証 executescript）⑦中断=BLOCKED（残穴: backup WAL sidecar 非対応 staging:499-501 / scan:364-370）。
- **fail-closed 要求（優先順）**: **P0-1** active_event を DB Ledger 単一正本化・CLI 強制（REQUIRED_ROUND 二重保守廃止）/ **P0-2** run_no 決定論採番+既存 run_id 衝突×hash 不一致=FAIL+REPLACE 時旧 lap 全削除 / P1-3 全 tier HED メタ照合+期待 outing 集合 / P1-4 apply 時 content sha256 Ledger 記録 / P1-5 DDL sha256 ピン留め+content-digest assert / P2-6 dataless 検出+--min-age 0 apply 禁止 / P2-7 歴史 pending superseded 化+Safety Audit に provisional⊆active 検査。rollback 要求 = WAL-safe backup 統一・REPLACE pre-image 保存・apply 状態機械（started/committed）。

### 75c. 設計骨子

- **Event Manifest**: 人が作成・承認する JSON（`02_DATABASE/event_manifests/<event_key>.json`）+ DB ミラー `event_manifest`（Phase B 新設・追加のみ）。必須 = event_key（YYYYMMDD-ROUNDx-RIDER・派生 weekend_key）/ date / round / circuit（TRACK_M 一致必須）/ riders / raw_2d_root / allowed_sessions / status（`draft→approved→active→locked→closed` CHECK・**active 同時1件**）/ schema_version。運用 = manifest_version（locked 後は新 version のみ）/ content_hash（**初回 apply receipt に保存→以後の書換え検出**）/ approved_by・approved_at（Tatsuki）/ activated_at / fingerprint_policy（stat|content・シナリオ①対応）/ expected_outings（宣言時は集合外 gated）。ROUND8 例 = `20260710-ROUND8-JA52`・DONINGTON・JA52・FP/QP/WUP1/WUP2/RACE1/RACE2・raw_2d_root=`DATA 2D/20260710-ROUND8-JA52`（実 JSON = schema proposal 内）。
- **Event-scoped Scan**: live = `--manifest` 指定時 raw_2d_root のみ+reports/results は round 一致のみ（queue 投入も scope 内のみ＝歴史的 pending 発生源遮断）。maintenance = 引数なし現行動作を別名分離（Workbench live ボタンは --manifest 付与）。受入条件 = disk/registry/queue/dry-run 候補が **(event_key, outing_stem, fingerprint)** で 1:1・不一致は fail-closed+理由表示。移行順 = Phase B は manifest **追加入力**（§68 guard・§69/§72 診断・§73 Safety Audit 無改変併存）→複数セッション実証後 Phase C で唯一の許可源へ切替・REQUIRED_ROUND はフォールバック残置。
- **Event State Ledger**: 新テーブル `event_state_ledger`（**追記型・UPDATE 禁止**）= entry_id PK / event_key / scope（event|session|outing）/ scope_id / state（CHECK）/ prev_state / reason / actor / analysis_run_id / receipt_json / created_at。状態機械 = `discovered→registered→candidate_ready→staged→verified→reportable→finalized` + 分岐 failed/warning_accepted/skipped/superseded/quarantined（理由必須）。Apply receipt = manifest content_hash+version / expected vs actual delta / post-apply invariants / operator 決定 / backup path / dry-run・apply ログ path。apply 状態機械（apply_started→apply_committed）で中断残骸を起動時検出。境界 = reportable まで provisional・finalized は別 GO（§65 型）・DB Master/Supabase/origin push はさらに独立 GO。
- **Phase B 分割**: **B-1**（最初・最小）= create_quality_tables.py 方式で 2 テーブル新設（追加のみ・冪等・CHECK）+ ROUND8 manifest JSON 承認 + Workbench 🏁 タブ read-only 表示のみ（scan/staging 挙動変更ゼロ）→ **B-2** = extraction_scan --manifest + maintenance 分離（フォールバック=現行）→ **B-3** = staging/Workbench manifest 読込（REQUIRED_ROUND 残置・二重検証）+ **P0-2 run_no 決定論採番+衝突 FAIL** + P0-1 CLI active-event 強制 + WAL-safe backup 統一。各 B-x で変更ファイル・migration（2テーブル追加のみ・既存 ALTER なし）・後方互換（manifest 不在=現行動作）・テスト（offscreen+CLI ガード行列+DB 不変）・GUI 確認（Tatsuki）・切戻し（DROP/ファイル削除/revert・guard 無改変で安全）を明示。

### 75d. 次ゲート・スコープ外

- 次ゲート: **`Event control plane implementation GO`**（この文言まで実装・DB migration・配線は一切開始しない。ROUND8 稼働中は Phase A で停止）。
- スコープ外（forbidden 遵守・未実施）: runtime 3 スクリプト変更 / canonical・provisional・registry・queue・data_quality_log への書込・削除・migration / DB Master refresh / Supabase / commit・push / Round8 finalization / provisional clear / §68 guard 弱体化 / folder watcher・auto-apply。
- 新規: `reports/race_weekend_event_control_plane_readiness_20260711.md` / `reports/event_manifest_schema_proposal_20260711.json`（未配線）/ `CLAUDE.md §75`。コード変更: **なし**。

---

## 76. ROUND8 Live Intake P0 Operations Gate（read-only runbook）— 2026-07-11 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-11 P0 第2タスク・L86-135）。§75 readiness で確定した P0 穴（①CLI 単体 `--apply` は `--required-round` 省略可 ②同一 session 時間差 outing の batch 相対 run_no → run_id 衝突 REPLACE 上書き+孤児 lap ③nested tier の event 外 .MES 素通り ④同名同サイズ差替検出不能）を、実装 GO までの間 **運用で発火させない**ための現状監査 + 現地 Runbook。**read-only / documentation-only**（DB は `mode=ro` SELECT のみ・runtime コード / queue / provisional / Workbench UI 無変更・テスト Scan/Apply なし・書込 = 本 .md と Obsidian .md のみ）。成果物 = `reports/round8_live_intake_p0_operations_gate_20260711.md`。

### 76a. 背景

ROUND8 live provisional 運用中（WUP1 まで成功）。Workbench 経由の Apply は §68 二層 guard + §73 fail-closed（`_preapply_gate` 8チェック / `_post_apply_check` invariant / 🏁 Status / 🛡 Safety Audit）で防御済みだが、§75 で「CLI 単体は guard 非有効」「run_no バッチ相対採番の衝突は通常運用で発火し得る」「事前 gate は衝突を検出できない」が確定。B-1 以降は `Event control plane implementation GO` 待ちのため、それまで唯一の安全経路 = 既存 Workbench 導線を Runbook として固定する。

### 76b. 現状監査（mode=ro・全チェック PASS）

- provisional 3テーブル: **6 runs / 46 laps / 46 lap_suspension**（FP 2/21・QP 3/18・WUP1 1/7）= 期待完全一致。run_id 重複 0・親 run なし lap 0・laps↔lap_suspension lap_id 差分 0/0。
- provenance: 全 6 run が `provisional_event_key='20260710-ROUND8-JA52'`・circuit=DONINGTON・rider=JA52・quality PASS 5 + WARNING 1（FP_R2）・**source_manifest_hash ↔ registry.sha256 が 6/6 JOIN 一致**。
- canonical 汚染 0: runs/laps/lap_suspension/race_results の ROUND8 行 0・`PROV_%` 0・DONINGTONPARK 0。totals = 286/1279/1279/866/7613/7710 不変。
- **queue 分離（JA52 live intake に混ぜてはいけない対象を数値で確定）**: queue 422 行（pending 383 / awaiting_gate 18 / failed 7 / skipped 14）。ROUND8 = 17 行 → **JA52 2d=awaiting_gate 6（取込済・再候補化禁止）/ JA52 report_import pending 1（2D 候補外=not a blocker）/ DA77 2d pending 10（Apply 対象外）**。加えて **historical pending 372（26 イベント分散）は絶対に Apply しない**。awaiting_gate 18 の残り 12 は ROUND7 JA52（final 反映済 §65・再候補化禁止）。

### 76c. Runbook 骨子（正本 = reports/round8_live_intake_p0_operations_gate_20260711.md）

- **許可経路（これのみ）**: 📥 Import/Quality → 🔍 Session Scan → ⬇ Session Import dry-run → 候補確認 → Apply 確認（既定 Cancel）→ 🏁 Status / 🛡 Safety Audit → provisional overlay 確認。
- **禁止**: 直接 CLI `session_extract_staging.py --apply` / `--include-awaiting` / live 中の全体 maintenance scan / DB ブラウザ更新 / 複数 session 曖昧一括 Apply / DA77・report・historical 行の Apply。
- 新 session 到着時 8 ステップ（iCloud 目視 → Status → Scan → Import dry-run〔候補 run_id が既存と重複しないか目視必須〕→ Apply → post-apply invariant 全PASS → Status+Safety Audit → overlay ⏳prov）+ 復旧時保存物（scan/import ログ・Safety Audit .md・ダイアログ/Status スクリーンショット・backup パス）。
- Session Scan の全域走査副作用（他イベント registry/queue 増加）は既知・Apply 防御済み・記録のみで気にしない。
- **Apply せず停止の 5 ケース**（各: 画面表示 / 危険理由 / 停止後 = Cancel→ログ保存→Code へ連絡）: ①同一 session 追加 outing（run_no 衝突・★最重要）②Apply 候補が 1 session でない（複数 session ダイアログ=原則 No）③run_id 既存重複 or expected delta 不一致（post-apply invariant FAIL 含む）④event 外 / DA77 / report 行が候補に出現 ⑤canonical 変化表示（Status canonical_round8≠0 / canonical unchanged FAIL）。
- **★ケース1 の検出限界を明記（隠さない）**: `_preapply_gate`（ts24_workbench.py:7322-7402）は候補 run_id vs 既存 provisional run_id を照合せず、**衝突時も expected delta が +1 で一致するため事前検出は不完全**。事後は `_post_apply_check`:7425-7435 の provisional delta FAIL（actual +0 runs）で捕捉されるが上書き発生後。→ **運用ルール = 「同一 session の既存 run がある状態で同 session の新規候補が出たら Apply 前に必ず停止」**（恒久修正は B-3 P0-2）。
- 付録A = 5 ケース ↔ 検出機構の file:line 対応表（`_preapply_gate`:7322 #1-#8 / 確認ダイアログ:7778-7823〔既定 Cancel・複数 session 既定 No〕/ `_post_apply_check`:7405-7490 / `_race_weekend_status`:7219 / `_run_safety_audit`:7493）。ケース 2-5 = 既存機構で実効・ケース 1 のみ運用先回り必須。

### 76d. ゲート再掲・スコープ外

- **B-1 開始 GO = `Event control plane implementation GO`**（それまで runtime/migration/配線ゼロ）。finalization / DB Master / Supabase / origin push は Runbook 対象外・個別 GO のまま。ROUND8 closure → ROUND9 readiness タスクは **`ROUND8 weekend closed`** 待ち（未着手・触らない）。
- スコープ外（forbidden 遵守・未実施）: `extraction_scan.py`/`session_extract_staging.py`/`ts24_workbench.py`/DB schema 変更 / テスト目的の Scan・Apply・queue/provisional/DB 更新 / DB Master / Supabase / commit・push / Round8 finalization / provisional clear。
- 新規: `reports/round8_live_intake_p0_operations_gate_20260711.md` / `CLAUDE.md §76`。コード変更: **なし**。

---

## 77. Workbench APEX / Damping Run Filter（P1・read-only UIのみ・Tatsuki実装承認済）— 2026-07-11 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-11 P1）+ 指示書 `reports/workbench_apex_damping_run_filter_code_instruction_20260711.md`。
Tatsuki の「両ページで Run 単位の検索・複数選択をしたい」要求＝**read-only UI 変更の明示承認**。`🦾 Suspension/Posture` の `📊 APEX分析（基本）` と `⚙️ Damping / Phase` が Circuit だけで全 Run 混在表示だったのを、両ページ共通 **`🔎 Run Filter`** で選択 run ID だけに絞れるようにした。
**変更 = `ts24_workbench.py` の `PostureAnalysisTab` のみ**（+367/−1 行・8 ハンク・全て当該クラス内）。`extraction_scan.py`/`session_extract_staging.py` 無変更＝**§68 ROUND8 fail-closed guard 完全保持**。**DB は一切開かず**（in-memory `_df` read-only フィルタのみ・SQL/schema/書込ゼロ）。成果物 = `reports/workbench_apex_damping_run_filter_apply_20260711.md`。

### 77a. 実装（`PostureAnalysisTab`）
- **`🔎 Run Filter` 共通パネル**（新 `_build_run_filter_panel()`・内部サブタブの上に配置）: 折りたたみトグル(▾/▸) + `Rider`/`Session`/`Stage`(All/Final/Provisional) コンボ + `検索` + `全選択`/`全解除` + 状態ラベル + Run 複数選択 checkbox リスト（`QListWidget`・maxHeight 132px）。
- **階層** = 上部 Circuit（global・既存）→ Rider → Session → Data stage → 検索可能 Run。`_combo_circ.currentTextChanged` を `_update_all`→新 `_rf_on_circuit`（Circuit 変更で Rider/Session/Run 再構築→再描画）へ再配線。
- **両ページ反映** = `_filtered_df()` 末尾に `_apply_run_filter()`（Rider→Session→Stage→選択 run_id・**物理/lap-time validity の後**に適用）。`_update_all()` が APEX 4 パネル + Damping 3 プロット＋数値テーブルを**同一 `_filtered_df()`** で描くため両ページが常に同じ選択 ID を反映。
- **空選択 = 明示空状態**（`_rf_clear_plots` で全プロット+Damping 表クリア・赤ラベル「Run 未選択…全Runへは戻しません」）。**サイレントに全 Run へ戻さない**。
- **既定 = 現挙動保持**（Circuit スコープ内の有効 Run 全選択＝従来の全 lap 表示）。再読込/再構築で選択を可能な限り保持（`prev` 集合）。**Data stage 区別保持**（`data_stage` 列優先・無ければ `run_id` PROV_ prefix・provisional は `⏳ …(prov)`）。`PhaseRunCompareWidget` の選択セマンティクス踏襲（重複実装なし）。
- **3フェーズ Run比較は独立**（`_inner_tabs.currentChanged`→`_rf_on_tab_changed` で比較タブ表示中は共通 Run Filter 非表示・`PhaseRunCompareWidget` 無改変）。検索は表示切替のみ（選択保持）・全選択/全解除は検索絞込中は表示中のみ対象。

### 77b. 検証（全 PASS）
- py_compile PASS。offscreen smoke（**canonical のコピー**に対して実行・実 DB 未オープン）: 7 タブ/内部 3 タブ・Run Filter 全ウィジェット存在・既定 circuit=全 run_list 175 全選択 filtered 1200・ASSEN 17 run/102 lap・Rider DA77 62/9・Session FP 16・**空選択→0 lap（全 Run へ戻らない）**・単一 run 11 lap・3 run 16 lap・**APEX+Damping 共有**（Damping 表 16 == filtered 16）・DONINGTON Provisional 6 prov run（ラベル `⏳ … (prov)`）・Final stage 0（ROUND8 未 finalization で正）・**3フェーズ比較の選択 4 run 不変**・タブ可視性・refresh 再構築。
- **canonical/provisional/registry/queue before==after**（`mode=ro`）: 286/1279/1279/866/7613/7710・prov 6/46/46・registry 431/queue 422。**実 canonical DB SHA-256 完全一致**（`e74bdbfe…f42cda`）＝書込ゼロを実証。**GUI 目視（単一/複数/ROUND8 provisional Run 切替）は Tatsuki ローカル**。

### 77c. rollback / スコープ外
- rollback: Run Filter 追加ブロックの **targeted revert**（`_build_run_filter_panel`/`_rf_*`/`_apply_run_filter` 群 + `_setup_ui` の panel 追加・`_combo_circ` 再配線・`currentChanged` 接続 + `_filtered_df`/`_update_all`/`_load_data` の追加分）。⚠ `git checkout` は §48〜§76 未コミット機能も戻るため不可。基準スナップショット = scratchpad `ts24_workbench.py.pre_run_filter`。DB/Excel/Supabase 無変更で DB rollback 不要。
- スコープ外（禁止遵守・未実施）: `extraction_scan.py`/`session_extract_staging.py`/import queue/staging・finalization/Report 生成/metric・phase 抽出/DB schema/DB 書込（テスト含む）/DB Master/Supabase/commit・push/ROUND8 fail-closed intake controls 弱体化。
- 変更: `ts24_workbench.py`（`PostureAnalysisTab` のみ）。新規: `reports/workbench_apex_damping_run_filter_apply_20260711.md` / `CLAUDE.md §77`。

---

## 78. ★ROUND8 final DB integration（Track A・Tatsuki実行承認済 P0）— 2026-07-13 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-13 P0・**実行承認済**）+ 指示書 `reports/round8_final_integration_code_instruction_20260713.md`。
Phase 1 read-only監査 → Phase 2 canonical apply → Phase 3 Workbench検証 → v2 staging補完 を完遂。**Race2 2D/telemetryのみ保留**（唯一の欠落ソース・捏造/placeholder/Race1流用なし）。
成果物 = `reports/round8_final_integration_readiness_20260713.md`（Phase 1）/ `reports/round8_final_integration_apply_20260713.md`（Phase 2-3 + §11 v2 staging）/ `reports/pdf_v2_gate_20260713.md`。

### 78a. Phase 1監査（read-only・canonical sha256 before==after 実証）
- 全ROUND8ソース棚卸し（hash/mtime/disposition）: Report / Original（2026-07-12更新・ROUND8 JA52 9行）/ Result PDF 6本（RACE2含む）/ 両rider 2D。**Race2 .MES 両rider不在を確認**。
- ROUND8限定scratch build: 19 runs/165 laps。**provisional 137/137 lap 完全一致**（値不一致0）・全10 rider/session best が公式PDF ±0.010s・circuit=DONINGTON のみ。
- **SX汚染検出**: build_master_db が FAIL隔離済み `SX_F1`/`SX_SP`（FP-01/SP-03 の重複telemetry 21 laps）を session='SX' として取込 → apply時除外を必須化。**DA77 WUP2**（`WU2-#77-01`・7 laps・queue pending 未取込）は正当データとして取込対象化。
- **§3c 発見（NO-GO flag）**: Original の 2025 BSB Donington RACE1/RACE2 行（C104）が ROUND8 行（C106）と自然キー衝突（Original に round/date 列なし）→ scratch で JA52 RACE1 telemetry R1 に誤って C104 が付与され、正しい C106 は 0-lap ghost R2 へ。

### 78b. §3c 監督裁定（Option 2改・canonical側決定論補正）
- Original 編集は却下（§1b 原本読み取り専用）/ 誤setupのまま apply も却下。**採用 = R1 へ C106 payload（Original setup 33列）を付与し、2025重複行の副産物である 0-lap ghost R2 は挿入しない**（クリーンな Original なら build が生成したはずの姿と一致）。
- **wf_* 再計算**: C104/C106 でバネレート相違（8.75/90 vs 9.0/84）のため R1 の 20 lap_suspension 行を build_master_db と同一式・丸めで再計算（WF_F=susp×9.0 / WF_R=susp×42.0）・in-transaction assert 全20行検証。
- 既存 canonical `NA_DONINGTON_RACE1/2_JA52_R1`（2025年・round=NULL・C104）は**不変**。**Tatsuki への提案**: Original の 2025 BSB Donington 行の区別（例 CIRCUIT→DONINGTON_BSB25）を推奨（Race2 2D 到着後の finalization で同じ衝突が再発するため）。

### 78c. Phase 2 apply（新規ツール3本・全て既定dry-run・WAL-safe backup・単一transaction・失敗時rollback）
- `apply_round8_race_results.py`: **+74 → race_results 940**（RACE1 33/RACE2 33/FP・QP・WUP1・WUP2 各2・衝突0・DONINGTON物理レンジ対応）。
- `apply_round8_targeted_insert.py`: **+16 runs/+144 laps/+144 lap_suspension → 302/1423/1423**（JA52 8 runs: FP2/QP3/WUP1/WUP2/RACE1、DA77 8 runs: FP2/SP3/WUP1/WUP2/RACE1）。assert: RACE2 telemetry=0・SX=0・DONINGTONPARK=0・orphan/dup=0・laps==ls・非ROUND8行 sha256 一致・保護テーブル不変（pdf_lap_times 7613/registry/queue/quality/metric_version_log 32/race_lap_detail VIEW）・RACE1 JA52=R1のみ f_set_c='C106'。schema gate は列集合等価（§44 ALTER 由来の物理順差を許容・INSERT は明示列名）。
- `apply_round8_provisional_clear.py`: 等価ゲート（137/137 canonical 一致）後に **provisional 15/137/137 → 0/0/0**。queue: awaiting_gate 15 + pending 1（WU2-#77-01）→ done / **FAIL 4（SX×2・WU1-01/02 zero-lap）+ SP-77-03 incomplete は証跡として残置**。historical queue は無変更。
- v2 staging補完（既存承認パイプライン §32-§38）: gate `--all` = ROUND8 RACE1 PASS 31/RACE2 PASS 32・**過去ラウンド回帰0**・G5 は rider-session-best相対（89s laps 正常通過）→ `apply_pdf_v2_staging.py --apply` = **v2_staging 7710 → 8824（+1114 ROUND8）**・`race_lap_detail` 12763 → **13877**（ROUND8 1114行・team #52/#77 各19 laps/race）。
- backups: `_backup_round8_rr_20260713_010310` / `_backup_round8_targeted_20260713_010320` / `_backup_round8_provclear_20260713_010332` / `_backup_round8_v2staging_20260713_075631`（+ツール自前 `_backup_pdf_v2_staging_20260713_075640`）。DB sha256 2eedecbd…→977baad8…。rollback = 各backup復元 or `DELETE FROM pdf_lap_times_v2_staging WHERE round='ROUND8'`（レポート§11）。

### 78d. Phase 3 Workbench検証（offscreen・`ts24_workbench.py` 無変更）
- 7タブ構築OK・DONINGTON final = **16 runs/144 laps** overlay（data_stage 全'final'・⏳prov 0・PROV_ 0）。チャート表示 139/144 = in-lap 5本が FULL_BRAKING ゾーン統計NULLで標準validity filterにより非表示（**データはDB完全保持**・全ラウンド共通挙動）。
- **Race2**: Suspension/Posture に RACE2 行 0（session comboに出ない＝Race1/provisional流用経路なし・fake placeholderなし）。Race Analysis は ROUND8 選択可・RACE2 = PDF由来 562行/32名 表示（公式データ経路のみ）。
- **GUI 最終目視は Tatsuki ローカル**（`python3 ts24_workbench.py` → DONINGTON final確認・Race Analysis ROUND8）。

### 78e. スコープ外（別承認のまま）
- Supabase sync（v3 に ROUND8 delta 未反映）/ DB Master refresh / origin commit・push / 破壊的 historical queue cleanup / Race2 2D 到着後の telemetry finalization（別GO・§78b の Original 衝突注意）。
- Track B（Event Control Plane B-1〜B-3 実装）は並行タスク（fixture/scratch限定・§75設計準拠・別記録予定）。
- 新規: `apply_round8_race_results.py` / `apply_round8_targeted_insert.py` / `apply_round8_provisional_clear.py` / 報告書3本 / `CLAUDE.md §78`。既存コード変更なし（Track A分）。

---

## 79. ★Event Control Plane B-1〜B-3 実装 + production接続（Track B・Tatsuki実行承認済 P0）— 2026-07-13 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-13 P0 項目6-8・**B-1/B-2/B-3実装の明示承認**）+ §75設計。fixture/scratch DBでTrack Aと並行実装し、**受入全PASS + Track A rollback点確立後にのみ**production Workbench経路へ接続（指示項目8遵守）。
成果物 = `reports/race_weekend_event_control_plane_apply_20260713.md`（実装+テスト証跡+§7配線spec+§8 production配線）/ `reports/round9_readiness_acceptance_20260713.md`（Round9 template+13ステップactivationチェックリスト）。

### 79a. 実装（B-1→B-2→B-3）
- **B-1**: 新規 `create_event_control_tables.py`（冪等・追加のみ・CHECK制約・**active同時1件=partial UNIQUE index**・**追記型=UPDATE/DELETE拒否トリガー**）= `event_manifest` + `event_state_ledger`。新規 `event_manifest.py`（load/validate/seal/register/activate/ledger・**content_hash改ざん検出をJSON/DB行/列の3層**・版は不変・activateは明示のみ）。実マニフェスト `02_DATABASE/event_manifests/20260710-ROUND8-JA52.json` / `-DA77.json`（DA77は重複 `SP-77-03`・未知 `SX_*` を expected_outings 外＝gated宣言）+ `TEMPLATE_ROUND9.json`（**そのままではvalidation FAIL＝誤activate不能設計**）。
- **B-2**: `extraction_scan.py --manifest <json>` = live scan（manifest宣言raw rootのみ走査・未知session/宣言外stemはgated・queue投入はevent scope内のみ・`fingerprint_policy=content` で全byte hash・global self-heal skip）。**引数なし=現行維持のmaintenance scan**（help明記）。受入identity = (event_key, outing_stem, fingerprint)。
- **B-3**: `session_extract_staging.py` = ①**あらゆる `--apply` にresolvable required round必須**（明示flag→active manifest解決→どちらも無ければ **exit 4**＝P0-1閉塞）+ active manifest時は `--event`==event_key・session∈allowed_sessions ②**決定論run ID**（outing-stem末尾番号由来）: 同名同内容=冪等no-op / 同名異内容・stem差替=明示conflict FAIL（無書込）/ canonical衝突=FAIL＝**§76★ケース1（batch相対run_no衝突REPLACE上書き）の恒久修正=P0-2完了** ③WAL-safe backup（db+wal+shm）+ ledger receipt（apply_started/committed/failed・テーブル不在時は後方互換skip）。

### 79b. 検証（敵対テスト26/26 PASS・後方互換byte一致・production非干渉実証）
- 敵対suite（fixture/scratch・`/tmp/ts24_trackb_work/results.json`）: zero/multiple active・manifest改ざん（JSON+DB mirror）・event外/historical apply・unscoped CLI apply・二重取込no-op・同名異内容conflict・旧仕様なら衝突する2バッチ→R1/R2独立採番・コピー途中保留・未知session/宣言外stem gated・zero-lap FAIL隔離・クラッシュ3態様（backup前/txn中/commit後receipt前）・**Race2 PDF-without-2D→PDFのみqueue・telemetry捏造0**・global scan副作用なし・Track A後canonical衝突検出 — **全てfail-closed**。
- 回帰: 引数なし `extraction_scan --dry-run` stdout **byte一致**（変更前後）・現行style staging dry-run同一。テストsuite全体でproduction DB sha256不変を実証。

### 79c. production接続（§8・指示項目8の条件充足後）
- 管理2テーブルをproduction作成（backup `02_DATABASE/_backup_event_control_20260713_082939/`・**業務テーブル302/1423/1423/940/7613/8824不変assert**）。ROUND8マニフェスト2本をv1登録→**closed**（terminal・**activateせず=active 0**→全manifest-aware経路が後方互換fallback）。ledger監査4行。
- Workbench配線（§7 spec verbatim・backup `05_SCRIPTS/_backup_trackb_wiring_20260713_080110/`）: `_active_manifest()`/`required_round()`（**REQUIRED_ROUND literal はfallbackとして残置**・12参照置換）/ `🔍 Live Event Scan`（`--manifest` 付与・**active manifest無しはfail-closed拒否＝暗黙global scanなし**）+ 新 `🗄 Historical Maintenance Scan`（確認dialog・既定Cancel）/ 🏁 Statusにactive manifest・hash・ledger直近10・last receipt・orphan apply_started・session別 `telemetry_pending`（RACE2のみ正表示）/ importダイアログに候補stem/fingerprint12/run_id/laps+stop reasons / Safety Audit §4b追加（manifest state・provisional⊆scope・orphan=0）。**§68/§73ゲート・§77 Run Filter無改変**。
- 検証: py_compile 4本 / offscreen smoke **28/28 PASS**（7タブ・no-active-manifest状態・live scan拒否・DONINGTON final 16 runs・Run Filter回帰・Race Analysis ROUND8 1114行）/ scratch copyでのactivation解決テスト（合成ROUND9 activate→required_round()=ROUND9・productionはactive 0のまま）/ **16テーブルfull-row sha256一致**（追加は新2テーブルの2+4行のみ）。

### 79d. 運用変更・残課題・rollback
- **Round9以降**: `REQUIRED_ROUND` 手動書換は不要 → `round9_readiness_acceptance_20260713.md` の13ステップchecklistでmanifest承認→activate（Tatsuki）。activateまでは全経路が現行ROUND8 fallback（ROUND8はcanonical>0のため§73ゲートでlive intake自体block＝安全）。
- 残課題: ①Tatsuki GUI目視 ②既存bug `analysis_run_id` 秒解像度PK衝突（Track B以前から・別followup）③cosmetic: 🏁 next_actionの§73警告表示（ROUND8 finalized+fallback literal時・Round9 activateで自然解消）④dual-rider週末はper-rider順次activate運用（schema v2でweekend multi-root候補）。
- rollback: Workbench=`.pre_wiring` 復元 / DB=`_backup_event_control_*` 復元（or 新2テーブルDROP）/ scan・staging=`.pre_trackb` 復元。
- スコープ外（未実施）: Supabase / DB Master / commit・push / historical queue cleanup / canonical業務テーブル書込。
- 新規: `create_event_control_tables.py` / `event_manifest.py` / manifests 3 JSON / 報告書2本。変更: `extraction_scan.py` / `session_extract_staging.py` / `ts24_workbench.py`（後方互換・fallback内蔵）。

---

## 80. Workbench Setup Diff / Damping 分布 追加 → Codex Dynamics 監査 → 修正5件（2026-08-24 Claude Code）

T08 Front setups 意見書（NERO 30/+0.5 vs ROSSO 26/−0.5・OPZIONE A/B）の作成過程で「Workbench が答えられなかったこと」を実装 → **Codex が Motorcycle Dynamics KB で監査 → 物理的誤用 5 件を検出 → 全件修正**。
**DB 書込ゼロ・スキーマ変更なし**（SHA-256 不変・302/1423/1423/940 不変）。
成果物 = `reports/workbench_setup_diff_damping_dist_apply_20260824.md`（実装）/ `reports/fkr_damping_curve_prep_20260824.md`（FKR 解析）/ **`reports/workbench_dynamics_audit_fixes_20260824.md`（監査対応・本件の正）**。

### 80a. 追加した UI（`ts24_workbench.py` のみ・read-only）
- **🆚 Setup Diff**（Suspension/Posture 内・Run Filter 非適用）: 2 run の設定差分 27 項目 + 導出ジオメトリ + FKR 減衰力。成績デルタ併記。
- **📉 Damping 分布**（Run Filter 適用）: 12 チャンネルのラップ単位分布（median/p10/p90/max/n）。**DB は lap 単位 avg/peak しか持たない**ためサンプル分布ではない。
- **💬 Comment Analysis にセット状態併記**（既定 ON・6 列＋`F reb@0.3 [N]`）: 同一症状のフォーク構成を並べ、幾何由来かダンピング由来かを切り分ける。`Diagnosis_Principles` の固定マッピング禁止には抵触しない（共通項の提示のみ・解を出さない）。
- **ラップ詳細セットアップパネル**に `f_offset2`（HP Insert）/ `r_tos_*` / link / swing_arm / Geometry(model) / F 減衰力を追加（従来 `f_offset2` と `r_tos_*` は UI に 1 箇所も無かった）。
- 導出ジオメトリ `SetupDiffWidget.geometry_of`: `rake = 23.95 + 0.70×insert` / `trail = (R sinε − offset)/cosε`（R=301.75mm）。T08 実測 2 点較正・**ASSUMPTION**・±0.2mm は較正点への再現誤差。`f_offset2` は角度のみで A/B の「+2」線形成分を表現できない（約 0.5mm 過大評価・コメント明記）。

### 80b. ★Codex 監査の指摘 5 件 → 全件修正
1. **減衰カーブ overlay = 物理的に比較不能**（未校正の相対指数 vs 校正済み shaft velocity）→ **機能撤回**。`CURVE_OVERLAY_ENABLED=False`・`_load_curves()` は常に None・UI に `REFERENCE_REQUIRED`（front/rear sensor calibration / linkage conversion / sampling-time calibration）。既存監査 `report_v2_feedback_audit_20260708.md` の結論と一致。**私の prep §4 で「重ねてはならない」と書きながら overlay を有効にしていた自己矛盾**。
2. **peak 定義の誤表示**: `brk_f_dive_spd_peak`=**MAX**（凍結列 :309）/ 新 22 列=**p95**（:333）。UI が全て「p95」と表示 → チャンネル別に動的ラベル化 + MAX 選択時に「定義をまたいだ分布比較は不可」を明示。
3. **「単一変数＝帰属可能」が強すぎ**（TYRE/COND を交絡数から除外していた）→ バナーは**記録上の差分件数のみ**を述べ帰属を主張しない。未統制の TYRE/COND 差分を列挙。
4. **`ph12_rear0_s` を「リア荷重ゼロ」と扱わない**: 実体は `SUSP_REAR<=0mm` の滞在時間で Nr=0 を計算していない → 「PH1-2 リアサス位置≤0mm 滞在時間」に改称・接地喪失の代理として断定しない旨を明記。**⚠ Obsidian `12_TACIT_KNOWLEDGE/Diagnosis_Principles.md` 等の「リア荷重ゼロ時間」記述は未修正（Codex 領域・改称推奨）**。
5. **Pitch / Heave は車体 pitch/heave ではない**（異なるセンサー座標の差・平均）→ UI の「均等荷重」「高荷重」等の断定を削除し **position proxy** と明記。
- 補足: ジオメトリ ±0.2mm を `ASSUMPTION`・較正点再現誤差と明記。

### 80c. ⚠ 私の記述の訂正 — FKR PDF にカーブは存在する
実装報告の「FKR-1xx PDF はシムスタック部品表でありカーブを含まない」は **誤り**。**PDF 2 ページ目に Compression / Rebound の Force–Velocity グラフ**がある（C101–C106 / R101–R106 @ click 14・0–1.0 m/s・0–2000 N）。テキスト層のみ抽出しベクター図を見落とした。両レポート訂正済み。
なお Cremona Test #07 の "Diving is under control with **C106**" はこの valve code を指す。

### 80d. FKR ダンパーライブラリ = セット側の力換算として実装（用途分離）
`04_REFERENCE/FKR-1xx-setting-library-version-1.0-interactive.xlsm` の `InData` から **228 本**（C101–C106 / R101–R106 × click 6–24・shaft speed 0.001–0.5 m/s・力 N）を抽出 → `04_REFERENCE/fkr_damping_library.json`（overlay スロット `damping_curves.json` とは**意図的に別名**）。
- `FKRDamperLibrary`（read-only・線形補間・参照 0.1 / 0.3 m/s）を Setup Diff / セットアップパネル / Comment Analysis に配線。**2D テレメトリに一切触れない**ため校正問題と無関係。
- **フロントのみ**。リアショックは別体系（`r_set_c/r_set_r` = C4x/R4x）で収載なし。
- DB カバレッジ: 圧側 265/302・伸側 262/302 解決可（設定欠損 37・範囲外 3 = `R104_5`・`R105_26`×2）。
- 実測例: Donington `R104_21` = **298.5 N @0.3 m/s**（JA52 2026 季**最小**・範囲 298–486）/ Balaton R4-G1 `R104_18` = 331.5 N / Misano R7-G2 `R104_12` = 441.5 N。**ただし Donington は季最良結果**でもあるため「弱い伸側=遅い」を意味しない。

### 80e. 未対応（別作業・要式確定）
- **Front WheelForce Proxy `(F_SPR_L+F_SPR_R)/2`** — 並列バネは `k_L+k_R` のため現式は合計の半分。**DB 再計算を伴うため式確定後の別作業**（`build_master_db.py:646` / `lap_suspension_stats.py:514`）。
- **Rear WheelForce ×0.5** — `SUSP_REAR` がショック変位なら LR=2 で成立、車輪変位なら比率の二乗。センサー座標未確定 = `REFERENCE_REQUIRED`。
  **`link` のレバー比定義が入れば、リアの wheel force 換算と速度軸校正の両方が可能になる**（§80g）。
- Pitch/Heave の座標変換（リンク比・rake・wheelbase）/ 速度軸の校正（**不足入力はコース長のみ**・`fkr_damping_curve_prep_20260824.md` §4.2）/ Obsidian の `ph12_rear0_s` 記述改称。
- **sag フィールド追加**（`f_sag_static` 等）= T08 意見書 §5.2 の結論「プリロード値ではなく sag 実測値が正しい比較対象」。**正本 DB スキーマ変更のため未実施**。
- Setup Diff / Damping 分布に **Motorcycle Dynamics 専用 unit test が無い**（Quality Gate も今回の物理誤用を検出できず・Codex 指摘）。

### 80g. ★リアダンパーライブラリ TTX36-GP 反映（2026-08-24 追記）
Tatsuki 指摘により `04_REFERENCE/TTX36-GP-v3.6.xlsm`（Öhlins TTX36 GP Setting Bank・§66b で存在は既知）を解析 →
**§80e の「リアショックは別体系で解決不能」を解消**。報告書 = `reports/ttx36_rear_damping_library_20260824.md`。
- `InData` から **1209 本**抽出（圧側 21 コード C1-C9/C21-C23/C41-C49 + 伸側 18 コード R1-R9/R41-R49 × click **6-36**・
  shaft speed 0.001-**1.0** m/s〔フロント 0.5 より広い〕・力 N）→ `04_REFERENCE/ttx36_damping_library.json`。
- `DamperLibrary` 基底 + `FrontDamperLibrary`(FKR) / `RearDamperLibrary`(TTX36) へ分割（`FKRDamperLibrary` は後方互換別名）。
  Setup Diff の DAMP 群を F/R 両対応・ラップ詳細に `R 減衰力 (TTX36 dyno)`・Comment Analysis に `R reb@0.3 [N]` 列。
- カバレッジ: 圧側 240/302・伸側 241/302。**未収載 = `C21X`(25 run) / `R25`(24 run) / `C9_H20 L15`(1 run) → `—` 表示（推測で埋めない）。要 Tatsuki 確認**。
- **制約（UI 明記）**: ①速度軸 overlay は引き続き無効 ②表示は **damper shaft force で wheel force ではない**（`link` レバー比未取得）
  ③**F と R の力を直接比較しない**（別ダンパー・リンク介在）。
- シーズン実測（JA52・Rreb@0.3）: 季範囲 1477-2155 N。**ROUND8 Donington は週末通じ `C45/R47` 固定・1633-1768 N**（`R47` は R7 後半以降のみ）。
  ★**前後の非対称**: Donington はフロント伸側が季最小(298N)・リア伸側は上位域(1768N)。観察であり因果ではない。
- **T08 §5.1「Balaton 反例」の定量化**: Balaton RACE1 のリアは Donington より**圧側 −14〜−28% / 伸側 −13〜−24%**、
  TOS(120x12 vs 188x8)・link(5 vs 6) も別物 → 「高い `ph12_rear0_s` が無害」ではなく「別構成でその値に到達」を数値で確認。
- 検証: py_compile / offscreen 全タブ / front 228・rear 1209 読込 / 後方互換別名 True / **DB SHA-256 不変**。
  成果物 `reports/run_damping_force_front_rear.csv`（302 run × 前後 × 0.05/0.1/0.2/0.3 m/s）。

### 80f. スコープ外（未実施）
canonical write / スキーマ変更 / DB Master refresh / Supabase / commit・push / Round9 activate。
変更: `ts24_workbench.py`。新規: `04_REFERENCE/fkr_damping_library.json` / 報告書 3 本 / `CLAUDE.md §80`。

### 80h. Damping 分布 案A / Setup Diff 案B + グラフ・テーブル英語化（2026-08-24 Tatsuki 選定）

Tatsuki の視認性指摘（スクリーンショット 2 枚）に対し UI 案を提示し、選定結果を実装。
**変更 = `ts24_workbench.py` のみ・DB 書込ゼロ**（SHA-256 不変）。検討ページ = Artifact「Workbench View Studies」。

**方針**: <b>グラフ内・テーブル内の表記は英語に統一</b>（チームのエンジニアと共有するため）。
その外側の説明文・折りたたみ Notes・ツールチップは日本語のまま。

- **Damping 分布 = 案A（split panels）**: 同一線形軸では avg（中央値 52–56）が peak（370–466）に潰れていた →
  `_pw_avg` / `_pw_peak` の 2 パネルへ分割し**それぞれ独立スケール**。裾は **p99 でクリップ**（表示のみ・
  データ除外なし・チェックボックスで解除可）。median を破線で表示、凡例をプロット右上へ。
  `統計` コンボは撤去（両方常時表示のため不要）。パネル題に **peak の実 reducer を常時併記**
  （`Lap peak velocity (MAX)` / `(p95)`）= Tatsuki 選定。3 行あった注記は `▸ Notes` 折りたたみへ。
- **Setup Diff = 案B（grouped sections）**: 群を列から**セクション見出し**へ移し件数を併記
  （`Front  8 changed / 11` / `Rear  5 changed / 11` / `Geometry (model)  3 changed` /
  `Damper force (dyno)  8 changed`）。5 列 → **4 列**（Item / A / B / Δ）、Item のみ伸縮・A/B/Δ は固定幅で
  右側に集約。上部注記 3 行も `▸ Notes` 折りたたみへ（表示行数 13 → 20 行）。
- **英語化**: 項目名（`Fork offset` / `HP insert` / `Shock TOS len x spr` …）・`changed` / `not in library` ・
  `F comp force @0.1 m/s` / `R reb force @0.3 m/s` / `F valve code comp / reb` /
  `⚠ outside calibration range` / `Rake` / `Ground trail` / `Normal trail` ・
  バナー `Recorded FRONT/REAR changes: N items — Attribution not established …` ・
  成績デルタ `Best lap` / `Laps` / `F dive mean` / `F dive peak (MAX)` / `PH1-2 rear travel ≤0mm [s]` ・
  ラップ詳細 `F damper force (FKR dyno)` / `R damper force (TTX36 dyno)` / `comp … reb …`。
  **フェーズ名（Braking / Apex / Corner Exit）は既に英語のため変更なし。**
- 検証: py_compile / offscreen 全タブ巡回 / **テーブル内の日本語残り 0**（CJK 走査）/ 実描画キャプチャ目視 /
  **DB SHA-256 不変**（302 / 1423 / 1423 / 940）。**GUI 最終目視は Tatsuki ローカル**。
