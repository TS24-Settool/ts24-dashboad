# TS24 自動化システム仕様 v1.0
**作成者:** Cowork Claude  
**作成日:** 2026-05-13  
**実装担当:** Claude Code  

---

## 概要

4つの自動化システムを構築する。中心は `ts24_watcher.py`（常駐監視デーモン）。  
ファイルが保存されると自動的に検知し、適切な処理を実行してDB・Workbenchを最新に保つ。

```
Tatsuki がファイルを保存
        │
        ├── 07_RESULTS/*.pdf     → [System 1] PDF結果抽出 → race_results テーブル
        ├── 01_REPORTS/**/*.xlsx → [System 3] レポート取込 → DB Master 更新
        ├── DATA 2D/**/*.MES     → [System 2] 2D生データ取込 → lap_suspension + DB Master
        │
        └── ts24_unified.db が更新 → [System 4] Workbench 自動リロード
```

---

## System 0: 監視デーモン `ts24_watcher.py`（共通基盤）

### 役割
4つの監視パスを統合管理するメインデーモン。watchdog ライブラリを使用。

### 監視パス設定

```python
BASE = Path.home() / "Desktop" / "Data TS24 Claude"

WATCHES = [
    {
        "path":    BASE / "07_RESULTS",
        "pattern": r".*\.pdf$",
        "handler": "pdf_result_extractor.extract_pdf",
        "debounce_s": 5,    # PDF書き込み完了を待つ
    },
    {
        "path":    BASE / "01_REPORTS",
        "pattern": r"\d{8}-ROUND\d+-[A-Z0-9]+\.xlsx$",
        "handler": "report_importer.import_report",
        "debounce_s": 5,
    },
    {
        "path":    BASE / "DATA 2D",
        "pattern": r".*\.MES$",
        "handler": "mes_importer.import_mes",
        "debounce_s": 10,   # MESファイルは大きいので余裕を持つ
        "recursive": True,
    },
]

DB_PATH = BASE / "02_DATABASE" / "ts24_unified.db"
```

### 動作フロー

```python
class Watcher:
    def on_created(self, event):
        # 1. パターンマッチ確認
        # 2. debounce タイマーセット（同じファイルの重複処理防止）
        # 3. タイマー完了後 → handler 呼び出し
        # 4. 成功/失敗を watcher.log に記録
```

### ログ

```
BASE/05_SCRIPTS/watcher.log
形式: [2026-05-13 11:23:45] [INFO] PDF detected: 20260513-ROUND5-FP.pdf
      [2026-05-13 11:23:50] [INFO] PDF extraction complete: DA77 P12, JA52 P18
      [2026-05-13 11:24:01] [ERROR] MES import failed: FP-JA52-01.MES — <error>
```

### macOS LaunchAgent（自動起動）

`~/Library/LaunchAgents/com.ts24.watcher.plist` を生成するセットアップスクリプト:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC ...>
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ts24.watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/ts24/Desktop/Data TS24 Claude/05_SCRIPTS/ts24_watcher.py</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/ts24/Desktop/Data TS24 Claude/05_SCRIPTS/watcher.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ts24/Desktop/Data TS24 Claude/05_SCRIPTS/watcher_error.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

起動: `launchctl load ~/Library/LaunchAgents/com.ts24.watcher.plist`  
停止: `launchctl unload ~/Library/LaunchAgents/com.ts24.watcher.plist`

### 依存ライブラリ追加

`requirements_workbench.txt` に追記:
```
watchdog>=3.0.0
pdfplumber>=0.11.0
```

---

## System 1: PDF結果自動抽出 `pdf_result_extractor.py`

### 対象ファイル

```
07_RESULTS/
  ROUND4_BALATON_20260501/
    20260501-ROUND4-FP.pdf     ← 検知対象
    20260501-ROUND4-QP.pdf
    20260501-ROUND4-RACE1.pdf
    ...
```

### 監視対象ライダー設定（設定ファイル化）

```python
RIDERS = {
    "DA77": {"race_number": 77, "name_pattern": r"D\.?\s*AEGERTER|#77"},
    "JA52": {"race_number": 52, "name_pattern": r"J\.?\s*SOFUOGLU|#52"},
    # ライダー変更時はここだけ修正
}
```

**注意:** ライダー名のパターンはClaude Codeが実際のPDFテキストを確認して調整すること。

### 抽出データ（pdfplumber使用）

**ページ判定ロジック:**

| ページタイプ | 識別キーワード | 抽出内容 |
|------------|--------------|---------|
| 結果一覧 (1.2) | `"Results"` + `"Gap"` | position, best_lap, gap_to_first |
| アイデアルタイム (1.4) | `"Ideal Times"` | Seg1〜4ベスト, best_lap |
| クロノロジカル (1.5) | `"Chronological"` | ラップ別Seg1〜4 |

**結果一覧ページのパース（正規表現）:**

```python
# 例: "  25 77 D. AEGERTER  SWI Kawasaki ZX-6R 636  1'44.965  2.000  0.123  12"
pattern = re.compile(
    r"(\d+)\s+77\s+.*?(\d+'\d+\.\d+)\s+(\d+\.\d+)"
)
# groups: (position, best_lap_time, gap_to_first)
```

**アイデアルタイムページのパース:**

```python
# 例: "  25 77D. AEGERTER  SWI Kawasaki  30.612  24.033  28.490  19.677  1'42.812"
# Seg1  Seg2  Seg3  Seg4  Ideal  (5列)
pattern = re.compile(
    r"77.*?(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+'?\d+\.\d+)"
)
```

**P1セクタータイムとの差分計算:**

```python
# アイデアルタイムページの1行目 = P1のセクタータイム
p1_segs = [seg1_p1, seg2_p1, seg3_p1, seg4_p1]
rider_segs = [seg1_rider, seg2_rider, seg3_rider, seg4_rider]
gaps = [r - p for r, p in zip(rider_segs, p1_segs)]
```

### 書き込み先

#### 1. SQLite `race_results` テーブル（新規作成）

```sql
CREATE TABLE IF NOT EXISTS race_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    round           TEXT NOT NULL,       -- "ROUND4"
    circuit         TEXT NOT NULL,       -- "BALATON"
    session         TEXT NOT NULL,       -- "FP" / "QP" / "RACE1" / "RACE2" / "WUP1" / "WUP2"
    event_date      TEXT,                -- "2026-05-01"
    rider           TEXT NOT NULL,       -- "DA77" / "JA52"
    race_number     INTEGER,             -- 77 / 52
    position        INTEGER,             -- 順位
    best_lap_time   TEXT,                -- "1'44.965"
    best_lap_time_s REAL,                -- 104.965
    gap_to_first_s  REAL,                -- 2.000
    seg1_best_s     REAL,                -- ライダーのベストSeg1
    seg2_best_s     REAL,
    seg3_best_s     REAL,
    seg4_best_s     REAL,
    seg1_gap_s      REAL,                -- P1比Seg1差 (正=遅い)
    seg2_gap_s      REAL,
    seg3_gap_s      REAL,
    seg4_gap_s      REAL,
    total_laps      INTEGER,
    source_pdf      TEXT,                -- "20260501-ROUND4-FP.pdf"
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(round, session, rider)        -- 重複防止 (INSERT OR REPLACE)
);
```

#### 2. DB Master.xlsx 「RACE_RESULTS」シート（既存シートに追記 or 新規作成）

フォーマットは既存シートのスタイルに合わせること（MSPゴシック9pt・FFEBF3FB塗り）。

### ファイル名→メタデータ変換

```python
# ファイル名: "20260501-ROUND4-FP.pdf"
def parse_pdf_filename(filename):
    m = re.match(r"(\d{8})-ROUND(\d+)-(\w+)\.pdf", filename)
    date_str  = m.group(1)     # "20260501"
    round_num = m.group(2)     # "4"
    session   = m.group(3)     # "FP"
    
    circuit_map = {
        "1": "PHILLIPISLAND", "2": "PORTIMAO", "3": "ASSEN",
        "4": "BALATON", "5": "ESTORIL",  # 随時追加
    }
    return {
        "round":   f"ROUND{round_num}",
        "circuit": circuit_map.get(round_num, f"ROUND{round_num}"),
        "session": session,
        "date":    f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
    }
```

---

## System 2: 2D MES自動取込 `mes_importer.py`

### 対象ファイル

```
DATA 2D/
  R04_BALATON.26/
    DA77/
      FP-#77-01.MES   ← 検知対象
      R1-#77-01.MES
    JA52/
      FP-JA52-01.MES
```

### 処理フロー（既存スクリプトを順次呼び出す）

```python
def import_mes(mes_path: Path):
    """新しい.MESファイルが検知されたとき実行"""
    
    folder = mes_path.parent  # MESが入っているフォルダ
    
    # Step 1: ラップ別サスペンション統計 → SQLite + DB Master LAP_SUSPENSION
    subprocess.run([
        "python3", "lap_suspension_stats.py",
        "--mes", str(folder)
    ], check=True)
    
    # Step 2: APEX/BRAKE/WheelForce解析 → DB Master DYNAMICS_ANALYSIS
    subprocess.run([
        "python3", "parse_2d_channels.py",
        "--folder", str(folder)
    ], check=True)
    
    # Step 3: ラップタイム・セッションサマリー → DB Master LAP_TIMES / SESSION_SUMMARY
    subprocess.run([
        "python3", "parse_2d_to_excel.py",
        str(folder.parent)  # ROOT_FOLDER
    ], check=True)
    
    # Step 4: PERFORMANCE_CORRELATIONシート更新（存在すれば）
    subprocess.run([
        "python3", "performance_correlation.py"
    ], check=True)
    
    log(f"MES import complete: {mes_path.name}")
```

**注意事項:**
- 既存スクリプトがCLI引数を受け付けるかを確認し、必要ならば `--mes/--folder` 引数を追加すること
- 処理中に別の.MESが検知されてもキューに入れ、1件ずつ順次処理すること（並列処理禁止）
- エラー時はwatcher.logに記録してスキップ（クラッシュしない）

---

## System 3: レポート自動取込 `report_importer.py`

### 対象ファイル

```
01_REPORTS/
  DA77/
    20260501-ROUND4-DA77.xlsx   ← 検知対象
  JA52/
    20260501-ROUND4-JA52.xlsx
```

### 処理フロー

既存の `excel_parser.py` を呼び出す：

```python
def import_report(xlsx_path: Path):
    """新しいレポートExcelが検知されたとき実行"""
    
    # ts24-report-importスキルの処理をスクリプト化したものを呼び出す
    # excel_parser.py が担っている処理:
    #   - DAY1/REPORTシートから: セットアップ値, Problem Log, Setup Decision
    #   - DB Master DBページ更新
    #   - DB Master Problem Trendページ更新
    #   - SQLite runs/problem_log/setup_decision_log テーブル更新
    
    subprocess.run([
        "python3", "excel_parser.py",
        str(xlsx_path)
    ], check=True)
    
    log(f"Report import complete: {xlsx_path.name}")
```

**注意:** `excel_parser.py` がCLI引数でファイルパスを受け取れるよう修正が必要な場合は合わせて対応すること。

---

## System 4: DB→Workbench リアルタイム同期

### 実装場所: `ts24_workbench.py`

```python
from PyQt6.QtCore import QFileSystemWatcher

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ... 既存の初期化 ...
        
        # DB変更監視
        self._db_watcher = QFileSystemWatcher(self)
        self._db_watcher.addPath(str(DB_PATH))
        self._db_watcher.fileChanged.connect(self._on_db_changed)
    
    def _on_db_changed(self, path: str):
        """DBファイルが外部から更新されたとき呼ばれる"""
        # QFileSystemWatcherはファイル変更後にwatchを外すことがあるため再登録
        if path not in self._db_watcher.files():
            self._db_watcher.addPath(path)
        
        # 現在アクティブなタブのデータをリロード
        current_tab = self._tab_widget.currentWidget()
        if hasattr(current_tab, 'refresh'):
            current_tab.refresh()
        
        # ステータスバーに通知
        self.statusBar().showMessage("DB更新を検知 — データをリロードしました", 3000)
```

**各タブに `refresh()` メソッドを追加:**

```python
class RunBrowserTab(QWidget):
    def refresh(self):
        self._load_runs()  # DBから最新のRun一覧を取得して表示

class ProblemLogTab(QWidget):
    def refresh(self):
        self._refresh_table()  # テーブルをリロード
```

---

## 実装順序（優先度順）

| 優先度 | タスク | 難易度 | 前提条件 |
|--------|-------|--------|---------|
| 1 | `ts24_watcher.py` 骨格作成 + LaunchAgent設定 | 低 | watchdog インストール |
| 2 | System 3: `report_importer.py`（最も実績あり） | 低 | excel_parser.py のCLI化 |
| 3 | System 4: Workbench QFileSystemWatcher | 低 | Workbench Phase 1 完了後 |
| 4 | System 1: `pdf_result_extractor.py` + `race_results` テーブル | 中 | pdfplumber |
| 5 | System 2: `mes_importer.py`（既存スクリプト統合） | 中 | 各スクリプトのCLI確認 |

---

## 完了後チェックリスト

- [ ] `python3 -m py_compile ts24_watcher.py` エラーなし
- [ ] `launchctl list | grep ts24` でデーモン起動確認
- [ ] テスト用PDFを `07_RESULTS/TEST/` にコピー → watcher.log に検知ログ出現
- [ ] テスト用.MESを `DATA 2D/TEST/` にコピー → lap_suspension テーブルに行追加
- [ ] テスト用Reportを `01_REPORTS/DA77/` にコピー → runs テーブルに行追加
- [ ] Workbench起動中にDBを外部更新 → ステータスバーに「DB更新を検知」表示
- [ ] `race_results` テーブルにROUND4の6セッション分のデータが入っていること

---

## 注意事項

1. **エラーで止まらない**: どの処理が失敗してもデーモンは継続。エラーはwatcher.logに記録。
2. **重複処理防止**: 同じファイルのイベントが短時間に複数来ることがある。debounceで吸収。
3. **既存データの上書き**: `INSERT OR REPLACE INTO race_results` で重複を許容（再処理を想定）。
4. **パス**: スクリプトは `~/Desktop/Data TS24 Claude/05_SCRIPTS/` から実行されることを前提とする。
5. **race_results テーブル**: `create_workbench_tables.py` または新規 `create_automation_tables.py` に追加。

---

*完了後、race_memory.json の conversation_summaries に実装内容を記録すること。*
