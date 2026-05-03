# CLAUDE.md — TS24 Project Team Shared Context
**Project:** TS24 SET-UP TOOL / Puccetti Racing WorldSSP Suspension Management System
**Last Updated:** 2026-05-03
**Read this file at the start of every session — Claude Code, Cowork Claude, and ChatGPT both.**

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
│   ├── ts24_setup.db                ← SQLite（sessions / tags / race_results）
│   └── all_sessions.json            ← セッションJSONキャッシュ
├── 03_TEMPLATES/                    ← イベントレポートテンプレート
├── 04_REFERENCE/
│   ├── TS24_Knowledge_Base.md       ← サスペンション理論・ZX-636知識（必読）
│   └── TS24_System_Architecture.md ← システム設計書
├── 05_SCRIPTS/                      ← Claude Codeが主管するディレクトリ
│   ├── CLAUDE.md                    ← このファイル（必読）
│   ├── dashboard.py                 ← Streamlitダッシュボード（本体）
│   ├── parse_2d_channels.py         ← MESデータ解析（APEX検出アルゴリズム）
│   ├── lap_suspension_stats.py      ← ラップサスペンション統計生成
│   ├── lap_suspension_data.json     ← 615行・34列（Streamlit Cloud用）
│   ├── dynamics_data.json           ← DYNAMICS_ANALYSIS（Streamlit Cloud用）
│   ├── lap_times_data.json          ← ラップタイムデータ
│   ├── race_memory.json             ← 【重要】AI分析知見の蓄積ファイル
│   ├── git_push_fix.command         ← GitHubプッシュスクリプト（手動実行）
│   ├── run_full_analysis.command    ← 全データ再処理スクリプト
│   ├── ts24_workbench.py            ← 【NEW】PyQt6 Engineer Workbench（ローカルデスクトップアプリ）
│   ├── create_workbench_tables.py   ← 【NEW】problem_log / setup_decision_log テーブル作成スクリプト
│   └── requirements_workbench.txt  ← 【NEW】Workbench依存パッケージ（PyQt6, pyqtgraph, pandas）
└── 04_MES/                          ← MES生データ（2Dロガー出力）
    └── [RIDER]/[DATE]/              ← ライダー別・日付別
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

| ファイル | レコード数 | 主要列 | 更新タイミング |
|---------|-----------|--------|---------------|
| `lap_suspension_data.json` | 844行・26列 | APEX_CNT, APEX_SPD_AVG, APEX_SUSF_AVG, APEX_SUSR_AVG, BRK_CNT, BRK_SUSF_AVG, BRK_SUSR_AVG, FULLBRK_CNT, FULLBRK_SUSF, FULLBRK_SUSR, LAP_SUSF_MEAN, LAP_SUSF_MIN, LAP_SUSF_MAX, LAP_SUSR_MEAN | MES再処理時 |
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
created_at TEXT, updated_at TEXT
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

**目的:** ラップデータを見ながら Problem / Setup Decision をローカルDBに記録する作業台。
**Streamlit Dashboard とは独立した別アプリ。** Streamlit Cloudに影響しない。

### 起動方法
```bash
cd ~/Desktop/"Data TS24 Claude"/05_SCRIPTS
python3 ts24_workbench.py
# または
./TS24_Workbench.command  # まだ未作成 → Claude Codeが作成すること
```

### 初回セットアップ（テーブル未作成の場合）
```bash
python3 create_workbench_tables.py
```

### UI構成
```
左パネル (QTreeWidget)              右パネル (QTabWidget)
├── ASSEN                           ├── Tab1: Waveform View
│   ├── FP                          │   └── Speed / Brake / Gas (pyqtgraph)
│   │   ├── DA77                    │       Turn markers (DashLine)
│   │   │   ├── R1                  ├── Tab2: Problem Log
│   │   │   └── R2                  │   └── リスト表示 + 追加フォーム
│   └── QP                          └── Tab3: Setup Decision Log
│       └── ...                         └── リスト表示 + 追加フォーム
```

### データ読み取り構造
```python
# run_id 形式: {round}_{circuit}_{session}_{rider}_R{run_no}
# 例: UNK_ASSEN_FP_DA77_R1

# lap_overlay_data.json との紐付け（run_id フィールド不在のため）
# → circuit + session_type + rider + run_no でマッチング
# → rounds テーブルなし → round は "UNK" フォールバック

# runs テーブルの正しい列名
# session (not session_type), perf_best_lap (not best_lap_s)
```

### 現在の実装状態 (2026-05-03)
- ✅ 左パネル: Circuit → Session → Rider → Run 階層表示
- ✅ Tab1 Waveform: Speed/Brake/Gas pyqtgraph描画、Turn markers
- ✅ Tab2 Problem Log: リスト + 追加フォーム → SQLite保存
- ✅ Tab3 Setup Decision: リスト + 追加フォーム → SQLite保存
- 🔄 **要確認**: Speed Y軸 0-255 km/h表示・X軸 0-1.0固定（修正済み、未テスト）
- ⬜ TS24_Workbench.command ランチャーが未作成

### Claude Code への引き継ぎ事項
1. `python3 ts24_workbench.py` でWorkbenchを起動し、Speed Chartのスケールを確認する
2. Speed Y軸が 0-1 のままなら以下を `draw()` メソッドに追加（既にあるはず）:
   ```python
   for p in (self._p_speed, self._p_brake, self._p_gas):
       p.setXRange(0.0, 1.0, padding=0.01)
       p.enableAutoRange(axis="y")
   ```
3. `turn_templates.json` のアクセスは `.get(circuit, {}).get("turns", [])` で行うこと（dictではなくlist）
4. 問題なければ `TS24_Workbench.command` ランチャーを作成して push する

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

## 7. race_memory.json — 知見蓄積ファイル

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
