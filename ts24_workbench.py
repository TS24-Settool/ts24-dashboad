"""
ts24_workbench.py — TS24 Engineer Workbench v2.0
=================================================
PyQt6製ローカルデスクトップアプリ。
Run Browser / Quick Log / Problem Log / Setup Decision / Trend Analysis の5タブ構成。
CSV不要。DBから直接Runを選択してProblemを記録できる。

読み取り: ts24_unified.db, lap_suspension_data.json
書き込み: ts24_unified.db (problem_log / setup_decision_log のみ)

起動: python ts24_workbench.py
      または TS24_Workbench.command をダブルクリック
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt, QFileSystemWatcher, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette, QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget, QLineEdit, QFrame, QScrollArea,
)

# ── パス設定 ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DB_PATH      = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
XL_PATH      = SCRIPT_DIR.parent / "02_DATABASE" / "TS24 DB Master.xlsx"

# ── 定数 ─────────────────────────────────────────────────────────────
PROBLEM_TAGS = [
    "chattering_brake", "front_dive", "line_loss_exit",
    "nervousness", "no_turn_in", "push_rear_exit",
    "understeer_apex", "other",
]

COMPONENTS = [
    "f_preload", "f_comp", "f_reb", "f_spr_l", "f_spr_r",
    "r_preload", "r_comp", "r_reb", "r_spr",
    "ride_hgt", "swing_arm", "f_offset",
    "tyre_front", "tyre_rear", "other",
]

PHASES       = ["PH1", "PH2", "PH3", "PH4", "PH5", "GENERAL"]
SEVERITIES   = ["HIGH", "MEDIUM", "LOW"]
SOURCES      = ["OBSERVATION", "DATA", "RIDER_REPORT"]
CHANGE_TYPES = ["FORK", "SHOCK", "GEOMETRY", "TYRE", "ENGINE", "OTHER"]
RESULT_EVALS = ["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"]


# ════════════════════════════════════════════════════════════════════
# ユーティリティ
# ════════════════════════════════════════════════════════════════════

def format_laptime(sec: float) -> str:
    """秒数を 分:秒,00 形式に変換する（表示専用）。

    例: 97.45  → "1:37,45"
        300.63 → "5:00,63"
        65.0   → "1:05,00"
    """
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:05.2f}".replace(".", ",")


def parse_laptime_seconds(value) -> float | None:
    """表示用ラップタイム値を秒数へ変換する。

    既存TS24データの秒数(float/int)と、Company report由来の "1:31.7"
    形式の両方を受け付ける。DB値は変更しない。
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass

    text = str(value).strip().replace("'", ":").replace(",", ".")
    if ":" not in text:
        return None
    try:
        minutes, seconds = text.split(":", 1)
        return float(minutes) * 60.0 + float(seconds)
    except (TypeError, ValueError):
        return None


# ════════════════════════════════════════════════════════════════════
# DB アクセス層
# ════════════════════════════════════════════════════════════════════

class WorkbenchDB:
    def __init__(self, db_path: Path, xl_path: Path | None = None):
        self.db_path = str(db_path)
        self.xl_path = str(xl_path) if xl_path else str(Path(db_path).parent / "TS24 DB Master.xlsx")
        try:
            with self._conn() as conn:
                self._migrate_problem_log(conn)
                self._migrate_lap_observation(conn)
        except Exception:
            pass

    def _migrate_lap_observation(self, conn: sqlite3.Connection):
        """lap_observation_log テーブルを作成（存在しない場合のみ）。"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lap_observation_log (
                obs_id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id           TEXT,
                lap_id           TEXT,
                lap_no           INTEGER,
                rider            TEXT,
                circuit          TEXT,
                session          TEXT,
                round            TEXT,
                lap_time_s       REAL,
                pitch            REAL,
                heave            REAL,
                apex_susf_avg    REAL,
                apex_susr_avg    REAL,
                observation_type TEXT,
                observation_tag  TEXT,
                comment          TEXT,
                confidence       TEXT,
                created_at       TEXT,
                updated_at       TEXT
            )
        """)
        conn.commit()

    def add_lap_observation(self, data: dict) -> int:
        """lap_observation_log に1件追加して obs_id を返す。"""
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO lap_observation_log
                   (run_id, lap_id, lap_no, rider, circuit, session, round,
                    lap_time_s, pitch, heave, apex_susf_avg, apex_susr_avg,
                    observation_type, observation_tag, comment, confidence,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id"),    data.get("lap_id"),
                    data.get("lap_no"),    data.get("rider"),
                    data.get("circuit"),   data.get("session"),
                    data.get("round"),     data.get("lap_time_s"),
                    data.get("pitch"),     data.get("heave"),
                    data.get("apex_susf_avg"), data.get("apex_susr_avg"),
                    data.get("observation_type"), data.get("observation_tag"),
                    data.get("comment"),   data.get("confidence"),
                    now, now,
                ),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_lap_observations(self, run_id: str | None = None,
                              rider: str | None = None,
                              obs_type: str | None = None) -> list[dict]:
        """lap_observation_log を条件付きで取得（新しい順）。"""
        with self._conn() as conn:
            where, params = [], []
            if run_id:
                where.append("run_id = ?");  params.append(run_id)
            if rider:
                where.append("rider = ?");   params.append(rider)
            if obs_type:
                where.append("observation_type = ?"); params.append(obs_type)
            sql = "SELECT * FROM lap_observation_log"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY created_at DESC"
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def _migrate_problem_log(self, conn: sqlite3.Connection):
        """problem_log テーブルに Phase 2 拡張列を追加（既存DBへの後方互換対応）。"""
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "problem_log" not in tables:
            return
        existing = {row[1] for row in conn.execute("PRAGMA table_info(problem_log)")}
        new_columns = [
            ("distance_start_m", "REAL"),
            ("distance_end_m",   "REAL"),
            ("time_start_s",     "REAL"),
            ("time_end_s",       "REAL"),
            ("data_source_file", "TEXT"),
            ("analysis_note",    "TEXT"),
        ]
        for col_name, col_type in new_columns:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE problem_log ADD COLUMN {col_name} {col_type}"
                )
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_circuits(self) -> list[str]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT DISTINCT circuit FROM runs WHERE circuit IS NOT NULL ORDER BY circuit"
            )
            return [r[0] for r in cur.fetchall()]

    def get_runs(self, circuit: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if circuit:
                cur = conn.execute(
                    """SELECT run_id, circuit, session, rider, run_no, perf_best_lap
                       FROM runs WHERE circuit = ? ORDER BY session, rider, run_no""",
                    (circuit,),
                )
            else:
                cur = conn.execute(
                    """SELECT run_id, circuit, session, rider, run_no, perf_best_lap
                       FROM runs ORDER BY circuit, session, rider, run_no"""
                )
            return [dict(r) for r in cur.fetchall()]

    def get_run(self, run_id: str) -> dict:
        """単一 run の全フィールドを返す。"""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_next_runs(self, run_id: str) -> list[dict]:
        """同一 circuit・rider の次の run 候補を返す。"""
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT circuit, rider FROM runs WHERE run_id = ?", (run_id,)
            )
            row = cur.fetchone()
            if not row:
                return []
            cur2 = conn.execute(
                """SELECT run_id, session, run_no FROM runs
                   WHERE circuit = ? AND rider = ? AND run_id != ?
                   ORDER BY session, run_no""",
                (row["circuit"], row["rider"], run_id),
            )
            return [dict(r) for r in cur2.fetchall()]

    def get_problem_logs(self, run_id: str) -> list[dict]:
        """problem_log を取得。スキーマ拡張後も安全に動作するよう SELECT * を使用。"""
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT * FROM problem_log WHERE run_id = ? ORDER BY created_at DESC",
                    (run_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            print("[WorkbenchDB] get_problem_logs error:", e)
            return []

    def add_problem_log(self, data: dict) -> int:
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO problem_log
                   (run_id, round, circuit, session, rider, run_no, lap_no,
                    corner, phase, problem_tag, description, severity, source,
                    distance_start_m, distance_end_m, time_start_s, time_end_s,
                    data_source_file, analysis_note,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id"), data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"), data.get("run_no"),
                    data.get("lap_no"), data.get("corner"), data.get("phase"),
                    data.get("problem_tag"), data.get("description"),
                    data.get("severity", "MEDIUM"), data.get("source", "OBSERVATION"),
                    data.get("distance_start_m"), data.get("distance_end_m"),
                    data.get("time_start_s"), data.get("time_end_s"),
                    data.get("data_source_file", ""), data.get("analysis_note", ""),
                    "PENDING", now, now,
                ),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def delete_problem_log(self, problem_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM problem_log WHERE problem_id = ?", (problem_id,))
            conn.commit()

    def save_comment(self, run_id: str, comment: str) -> None:
        """runs.comment を更新する。"""
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE runs SET comment = ?, updated_at = ? WHERE run_id = ?",
                (comment.strip(), now, run_id),
            )
            conn.commit()

    def get_setup_decisions(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute(
                """SELECT * FROM setup_decision_log WHERE run_id_from = ?
                   ORDER BY created_at DESC""",
                (run_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_all_setup_decisions(self) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute(
                """SELECT * FROM setup_decision_log
                   ORDER BY created_at DESC"""
            )
            return [dict(r) for r in cur.fetchall()]

    def add_setup_decision(self, data: dict) -> int:
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO setup_decision_log
                   (run_id_from, run_id_to, round, circuit, session, rider,
                    change_type, component, from_value, to_value,
                    rationale, expected_effect, actual_effect, result_eval,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id_from"), data.get("run_id_to"),
                    data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"),
                    data.get("change_type"), data.get("component"),
                    data.get("from_value"), data.get("to_value"),
                    data.get("rationale"), data.get("expected_effect"),
                    data.get("actual_effect"), data.get("result_eval", "UNKNOWN"),
                    "PENDING", now, now,
                ),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_setup_decision_full(self, decision_id: int, data: dict):
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """UPDATE setup_decision_log SET
                   change_type=?, component=?, from_value=?, to_value=?,
                   rationale=?, expected_effect=?, result_eval=?, updated_at=?
                   WHERE decision_id=?""",
                (
                    data.get("change_type"), data.get("component"),
                    data.get("from_value"), data.get("to_value"),
                    data.get("rationale"), data.get("expected_effect"),
                    data.get("result_eval", "UNKNOWN"), now, decision_id,
                ),
            )
            conn.commit()

    def update_setup_decision(self, decision_id: int, actual_effect: str, result_eval: str):
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """UPDATE setup_decision_log
                   SET actual_effect = ?, result_eval = ?, updated_at = ?
                   WHERE decision_id = ?""",
                (actual_effect, result_eval, now, decision_id),
            )
            conn.commit()

    def get_laps(self, run_id: str) -> list[dict]:
        """laps テーブルから指定 run_id の全ラップを返す。"""
        try:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT lap_no, lap_time_s, is_outlap
                       FROM laps WHERE run_id = ? ORDER BY lap_no""",
                    (run_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_best_worst_pairs(self, rider: str | None = None,
                              circuit: str | None = None,
                              analysis_type: str = "STANDARD") -> list[dict]:
        """best_worst_pairs テーブルから全ペアを返す。
        rider="BOTH" / "ALL" / None はフィルタなし。
        テーブルが存在しない場合は空リスト（クラッシュしない）。
        """
        try:
            sql = "SELECT * FROM best_worst_pairs WHERE analysis_type = ?"
            params: list = [analysis_type]
            if rider and rider not in ("ALL", "BOTH"):
                sql += " AND rider = ?"
                params.append(rider)
            if circuit and circuit not in ("ALL",):
                sql += " AND circuit = ?"
                params.append(circuit)
            sql += " ORDER BY round, rider"
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_runs_summary(self) -> list[dict]:
        """runs テーブルから簡易サマリを返す（Run検索用）。
        返却フィールド: run_id / circuit / session / rider / run_no / comment
        """
        try:
            sql = """
                SELECT run_id, circuit, session, rider, run_no, comment
                FROM runs
                ORDER BY round, circuit, session, run_no
            """
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

# ════════════════════════════════════════════════════════════════════
# Problem Log タブ
# ════════════════════════════════════════════════════════════════════


def _fmt_range(r: dict) -> str:
    """problem_log 行の距離/時間範囲を表示文字列に変換する。"""
    ds = r.get("distance_start_m")
    de = r.get("distance_end_m")
    if ds is not None and de is not None:
        return f"{ds:.0f}→{de:.0f}m"
    ts = r.get("time_start_s")
    te = r.get("time_end_s")
    if ts is not None and te is not None:
        return f"{ts:.1f}→{te:.1f}s"
    return "—"

class _RunSelectorWidget(QWidget):
    """Circuit → Run 選択 UI。CSV ロード不要で DB から直接 Run を選べる。"""

    def __init__(self, db: WorkbenchDB, on_run_selected, parent=None):
        super().__init__(parent)
        self._db = db
        self._cb = on_run_selected
        self._setup_ui()

    def _setup_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Run_ID / Comment で絞り込み...")
        self._search_box.setFixedWidth(180)
        self._search_box.textChanged.connect(self._on_search_changed)
        lay.addWidget(self._search_box)

        lbl_c = QLabel("🗂 Circuit:")
        lbl_c.setStyleSheet("font-size: 10px; font-weight: bold;")
        lay.addWidget(lbl_c)
        self._combo_circ = QComboBox()
        self._combo_circ.setMinimumWidth(120)
        lay.addWidget(self._combo_circ)
        lbl_r = QLabel("Run:")
        lbl_r.setStyleSheet("font-size: 10px; font-weight: bold;")
        lay.addWidget(lbl_r)
        self._combo_run = QComboBox()
        self._combo_run.setMinimumWidth(250)
        lay.addWidget(self._combo_run)
        lay.addStretch()
        self._combo_circ.currentTextChanged.connect(self._on_circ)
        self._combo_run.currentIndexChanged.connect(self._on_run)
        self.setStyleSheet(
            "background: #F0F4F8; border: 1px solid #C8D3DC;"
            " border-radius: 4px; padding: 2px;"
        )
        self._load_circuits()

    def _load_circuits(self):
        try:
            circs = self._db.get_circuits()
        except Exception:
            circs = []
        self._combo_circ.blockSignals(True)
        self._combo_circ.clear()
        self._combo_circ.addItem("— 全て —")
        self._combo_circ.addItems(circs)
        self._combo_circ.blockSignals(False)
        if circs:
            self._combo_circ.setCurrentIndex(1)
        else:
            self._on_circ("— 全て —")

    def _on_circ(self, _circuit: str):
        self._populate_run_combo(keyword=self._search_box.text().strip().lower())

    def _on_search_changed(self, text: str):
        self._populate_run_combo(keyword=text.strip().lower())

    def _populate_run_combo(self, keyword: str = ""):
        """現在の Circuit 選択と keyword で絞り込んで Run コンボを再構築する。"""
        circuit = self._combo_circ.currentText()
        circ = circuit if circuit != "— 全て —" else None
        try:
            runs = self._db.get_runs_summary()
        except Exception:
            runs = []
        if circ:
            runs = [r for r in runs if r.get("circuit") == circ]
        if keyword:
            runs = [
                r for r in runs
                if keyword in (r.get("run_id") or "").lower()
                or keyword in (r.get("comment") or "").lower()
            ]
        self._combo_run.blockSignals(True)
        self._combo_run.clear()
        for r in runs:
            label = f"{r['rider']}  {r['session']} R{r['run_no']}  ({r['run_id']})"
            self._combo_run.addItem(label, userData=r["run_id"])
        self._combo_run.blockSignals(False)
        if self._combo_run.count():
            self._combo_run.setCurrentIndex(0)
            self._emit()

    def _on_run(self, _idx: int):
        self._emit()

    def _emit(self):
        run_id = self._combo_run.currentData()
        if run_id:
            self._cb(run_id)

    def select_run_id(self, run_id: str):
        """外部から特定 run_id を選択状態にする（波形ロード連携）。"""
        for i in range(self._combo_run.count()):
            if self._combo_run.itemData(i) == run_id:
                self._combo_run.setCurrentIndex(i)
                return


class ProblemLogTab(QWidget):
    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._run_id: str = ""
        self._run_meta: dict = {}
        self._wave_prefill: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── DB ベース Run セレクタ ────────────────────────────────────
        self._run_sel = _RunSelectorWidget(self._db, self._on_db_run_selected)
        layout.addWidget(self._run_sel)

        # ── 一覧テーブル ──────────────────────────────────
        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Corner", "Phase", "Tag", "Description", "Severity", "Lap", "Range", "Source"]
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 60)
        self._table.setColumnWidth(2, 60)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 220)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 40)
        self._table.setColumnWidth(7, 160)
        self._table.setColumnWidth(8, 80)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, stretch=2)

        # 削除ボタン
        del_btn = QPushButton("選択行を削除")
        del_btn.clicked.connect(self._delete_selected)
        layout.addWidget(del_btn)

        # ── 区切り ────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # ── 新規追加フォーム ──────────────────────────────
        form_label = QLabel("▼ 新規問題を追加")
        form_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(form_label)

        # ── 波形連携: 自動入力エリア ─────────────────────────────────
        self._wave_info_box = QWidget()
        self._wave_info_box.setStyleSheet(
            "background: #EFF6FF; border: 1px solid #0078D4;"
            " border-radius: 4px; padding: 4px;"
        )
        wave_info_lay = QVBoxLayout(self._wave_info_box)
        wave_info_lay.setContentsMargins(8, 4, 8, 4)
        wave_info_lay.setSpacing(2)

        wave_header = QLabel("📊 波形から自動入力（読み取り専用）")
        wave_header.setStyleSheet("color: #0078D4; font-weight: bold; font-size: 10px;")
        wave_info_lay.addWidget(wave_header)

        self._lbl_auto_run   = QLabel("Run: —")
        self._lbl_auto_lap   = QLabel("Lap: —")
        self._lbl_auto_range = QLabel("Range: —")
        for lbl in (self._lbl_auto_run, self._lbl_auto_lap, self._lbl_auto_range):
            lbl.setStyleSheet("color: #004578; font-size: 10px;")
            wave_info_lay.addWidget(lbl)

        btn_clear_wave = QPushButton("✕ 自動入力をクリア")
        btn_clear_wave.setFixedHeight(20)
        btn_clear_wave.setStyleSheet("font-size: 10px; color: #666;")
        btn_clear_wave.clicked.connect(self._clear_wave_prefill)
        wave_info_lay.addWidget(btn_clear_wave)

        self._wave_info_box.setVisible(False)
        layout.addWidget(self._wave_info_box)

        form = QFormLayout()

        self._lbl_run = QLabel("（未選択）")
        form.addRow("Run:", self._lbl_run)

        self._spin_lap = QSpinBox()
        self._spin_lap.setRange(0, 999)
        self._spin_lap.setSpecialValueText("—")
        form.addRow("Lap No (optional):", self._spin_lap)

        self._combo_corner = QComboBox()
        self._combo_corner.addItem("NONE")
        for i in range(1, 18):
            self._combo_corner.addItem(f"T{i}")
        form.addRow("Corner:", self._combo_corner)

        self._combo_phase = QComboBox()
        self._combo_phase.addItems(PHASES)
        form.addRow("Phase:", self._combo_phase)

        self._combo_tag = QComboBox()
        self._combo_tag.addItems(PROBLEM_TAGS)
        form.addRow("Problem Tag:", self._combo_tag)

        self._txt_desc = QTextEdit()
        self._txt_desc.setFixedHeight(60)
        self._txt_desc.setPlaceholderText("詳細説明（任意）")
        form.addRow("Description:", self._txt_desc)

        self._combo_sev = QComboBox()
        self._combo_sev.addItems(SEVERITIES)
        self._combo_sev.setCurrentText("MEDIUM")
        form.addRow("Severity:", self._combo_sev)

        self._combo_src = QComboBox()
        self._combo_src.addItems(SOURCES)
        form.addRow("Source:", self._combo_src)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_add   = QPushButton("追加")
        btn_clear = QPushButton("クリア")
        btn_add.clicked.connect(self._add_entry)
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_db_run_selected(self, run_id: str):
        """Run セレクタから呼ばれる。DB からメタを取得して set_run() へ渡す。"""
        if not hasattr(self, '_lbl_run'):   # UI 初期化中の呼び出しは無視
            return
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {}
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run.setText(run_id or "（未選択）")
        self._refresh_table()

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run.setText(run_id or "（未選択）")
        self._refresh_table()
        if hasattr(self, "_run_sel"):
            self._run_sel.select_run_id(run_id)

    def prefill_from_waveform(self, data: dict) -> None:
        """WaveformView から呼ばれ、座標情報を自動入力する。"""
        self._wave_prefill = data

        run_id = data.get("run_id", "")
        if run_id and self._run_id and run_id != self._run_id:
            QMessageBox.warning(
                self,
                "Run 不一致",
                f"波形のRun ({run_id}) と\n"
                f"Problem Log のRun ({self._run_id}) が一致しません。\n"
                "左パネルで同じ Run を選択してください。",
            )
            self._wave_prefill = {}
            return

        self._lbl_auto_run.setText(f"Run: {run_id or '—'}")
        lap_no = data.get("lap_no")
        self._lbl_auto_lap.setText(f"Lap: {lap_no if lap_no is not None else '—'}")

        x_mode = data.get("x_mode", "")
        if x_mode == "distance":
            ds = data.get("distance_start_m")
            de = data.get("distance_end_m")
            range_str = (f"{ds:.1f}m → {de:.1f}m  ({de - ds:.1f}m)"
                         if ds is not None and de is not None else "—")
        elif x_mode == "time":
            ts = data.get("time_start_s")
            te = data.get("time_end_s")
            range_str = (f"{ts:.3f}s → {te:.3f}s  ({te - ts:.3f}s)"
                         if ts is not None and te is not None else "—")
        else:
            ts = data.get("time_start_s")
            te = data.get("time_end_s")
            range_str = f"progress {ts:.4f} → {te:.4f}" if ts is not None else "—"

        self._lbl_auto_range.setText(f"Range: {range_str}")
        self._wave_info_box.setVisible(True)

        if lap_no is not None:
            self._spin_lap.setValue(int(lap_no))

        src_items = [self._combo_src.itemText(i) for i in range(self._combo_src.count())]
        if "DATA" in src_items:
            self._combo_src.setCurrentText("DATA")

    def _clear_wave_prefill(self) -> None:
        """波形からの自動入力をリセットする。"""
        self._wave_prefill = {}
        self._lbl_auto_run.setText("Run: —")
        self._lbl_auto_lap.setText("Lap: —")
        self._lbl_auto_range.setText("Range: —")
        self._wave_info_box.setVisible(False)

    def _refresh_table(self):
        try:
            print("[ProblemLog] run_id:", self._run_id)
            rows = self._db.get_problem_logs(self._run_id) if self._run_id else []
            print("[ProblemLog] rows:", len(rows))
            if rows:
                print("[ProblemLog] keys:", list(rows[0].keys()))
        except Exception as e:
            print("[ProblemLog] refresh error:", e)
            import traceback; traceback.print_exc()
            rows = []
        self._table.setRowCount(0)
        for ri, r in enumerate(rows):
            try:
                self._table.insertRow(ri)
                vals = [
                    str(r.get("problem_id", "")),
                    str(r.get("corner", "") or ""),
                    str(r.get("phase", "") or ""),
                    str(r.get("problem_tag", "") or ""),
                    str(r.get("description", "") or ""),
                    str(r.get("severity", "") or ""),
                    str(r.get("lap_no", "") if r.get("lap_no") is not None else "—"),
                    _fmt_range(r),
                    str(r.get("source", "") or ""),
                ]
                for ci, val in enumerate(vals):
                    self._table.setItem(ri, ci, QTableWidgetItem(val))
            except Exception as e:
                print(f"[ProblemLog] row {ri} render error:", e)

    def _add_entry(self):
        if not self._run_id:
            QMessageBox.warning(self, "未選択", "左パネルでRunを選択してください。")
            return
        corner_val = self._combo_corner.currentText()
        if corner_val == "NONE":
            corner_val = None
        lap_val = self._spin_lap.value()
        if lap_val == 0:
            lap_val = None
        data = {
            "run_id":     self._run_id,
            "round":      self._run_meta.get("round"),
            "circuit":    self._run_meta.get("circuit"),
            "session":    self._run_meta.get("session"),
            "rider":      self._run_meta.get("rider"),
            "run_no":     self._run_meta.get("run_no"),
            "lap_no":     lap_val,
            "corner":     corner_val,
            "phase":      self._combo_phase.currentText(),
            "problem_tag": self._combo_tag.currentText(),
            "description": self._txt_desc.toPlainText().strip(),
            "severity":   self._combo_sev.currentText(),
            "source":     self._combo_src.currentText(),
            "distance_start_m": self._wave_prefill.get("distance_start_m"),
            "distance_end_m":   self._wave_prefill.get("distance_end_m"),
            "time_start_s":     self._wave_prefill.get("time_start_s"),
            "time_end_s":       self._wave_prefill.get("time_end_s"),
            "data_source_file": self._wave_prefill.get("data_source_file", ""),
            "analysis_note":    "",
        }
        self._db.add_problem_log(data)
        self._clear_form()
        self._clear_wave_prefill()
        self._refresh_table()

    def _clear_form(self):
        self._spin_lap.setValue(0)
        self._combo_corner.setCurrentIndex(0)
        self._combo_phase.setCurrentIndex(0)
        self._combo_tag.setCurrentIndex(0)
        self._txt_desc.clear()
        self._combo_sev.setCurrentText("MEDIUM")
        self._combo_src.setCurrentIndex(0)

    def refresh(self):
        """DB変更時に外部から呼び出される。テーブルを再読み込みする。"""
        self._refresh_table()

    def _delete_selected(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        pid_item = self._table.item(row, 0)
        if not pid_item:
            return
        try:
            pid = int(pid_item.text())
        except ValueError:
            return
        reply = QMessageBox.question(
            self, "削除確認", f"problem_id={pid} を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_problem_log(pid)
            self._refresh_table()


# ════════════════════════════════════════════════════════════════════
# Setup Decision Log タブ
# ════════════════════════════════════════════════════════════════════

class SetupDecisionTab(QWidget):
    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._run_id: str = ""
        self._run_meta: dict = {}
        self._edit_id: int | None = None   # None = 新規モード、int = 編集モード
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── DB ベース Run セレクタ ────────────────────────────────────
        self._run_sel = _RunSelectorWidget(self._db, self._on_db_run_selected)
        layout.addWidget(self._run_sel)

        # ── 一覧テーブル ヘッダー行 ────────────────────────────────
        tbl_header_row = QHBoxLayout()
        self._chk_show_all = QCheckBox("📋 Show All Decisions")
        self._chk_show_all.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self._chk_show_all.setChecked(True)
        self._chk_show_all.stateChanged.connect(self._on_show_all_toggled)
        tbl_header_row.addWidget(self._chk_show_all)
        tbl_header_row.addStretch()
        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet("color: #666; font-size: 10px;")
        tbl_header_row.addWidget(self._lbl_count)
        layout.addLayout(tbl_header_row)

        # ── 一覧テーブル ──────────────────────────────────
        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Run From", "Circuit", "Rider", "Component", "From", "To", "Rationale", "Result"]
        )
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 200)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 50)
        self._table.setColumnWidth(4, 100)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 70)
        self._table.setColumnWidth(7, 300)
        self._table.setColumnWidth(8, 80)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self._table, stretch=2)

        # 区切り
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        self._form_label = QLabel("▼ New Setup Decision")
        self._form_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(self._form_label)

        form = QFormLayout()

        self._lbl_run_from = QLabel("（未選択）")
        form.addRow("Run From:", self._lbl_run_from)

        self._combo_run_to = QComboBox()
        self._combo_run_to.addItem("NEXT（未定）")
        form.addRow("Run To:", self._combo_run_to)

        self._combo_chg_type = QComboBox()
        self._combo_chg_type.addItems(CHANGE_TYPES)
        form.addRow("Change Type:", self._combo_chg_type)

        self._combo_comp = QComboBox()
        self._combo_comp.addItems(COMPONENTS)
        form.addRow("Component:", self._combo_comp)

        row_fv = QHBoxLayout()
        self._edit_from = QLineEdit()
        self._edit_from.setPlaceholderText("例: 18")
        self._edit_to = QLineEdit()
        self._edit_to.setPlaceholderText("例: 16")
        row_fv.addWidget(self._edit_from)
        row_fv.addWidget(QLabel("→"))
        row_fv.addWidget(self._edit_to)
        form.addRow("From → To:", row_fv)

        self._txt_rationale = QTextEdit()
        self._txt_rationale.setFixedHeight(55)
        self._txt_rationale.setPlaceholderText("変更の根拠（データ/ライダー報告）")
        form.addRow("Rationale:", self._txt_rationale)

        self._txt_expected = QTextEdit()
        self._txt_expected.setFixedHeight(55)
        self._txt_expected.setPlaceholderText("期待する効果")
        form.addRow("Expected Effect:", self._txt_expected)

        self._combo_result = QComboBox()
        self._combo_result.addItems(RESULT_EVALS)
        self._combo_result.setCurrentText("UNKNOWN")
        form.addRow("Result Eval:", self._combo_result)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self._btn_save = QPushButton("＋ 追加")
        self._btn_new  = QPushButton("✦ 新規")
        btn_clear      = QPushButton("クリア")
        self._btn_save.clicked.connect(self._save_entry)
        self._btn_new.clicked.connect(self._clear_form)
        btn_clear.clicked.connect(self._clear_form)
        self._btn_new.setVisible(False)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_new)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_db_run_selected(self, run_id: str):
        if not hasattr(self, '_lbl_run_from'):  # UI 初期化中の呼び出しは無視
            return
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {}
        self.set_run(run_id, meta)

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run_from.setText(run_id or "（未選択）")
        self._combo_run_to.clear()
        self._combo_run_to.addItem("NEXT（未定）")
        next_runs = self._db.get_next_runs(run_id) if run_id else []
        for nr in next_runs:
            self._combo_run_to.addItem(
                f"{nr['run_id']}  ({nr['session']} R{nr['run_no']})",
                userData=nr["run_id"],
            )
        self._refresh_table()
        if hasattr(self, "_run_sel"):
            self._run_sel.select_run_id(run_id)

    def _on_show_all_toggled(self, _state):
        self._refresh_table()

    def _on_row_selected(self):
        """テーブル行クリック → フォームに内容を展開して編集モードへ。"""
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        # col0=ID, col1=RunFrom, col2=Circuit, col3=Rider,
        # col4=Component, col5=From, col6=To, col7=Rationale, col8=Result
        def cell(c):
            item = self._table.item(row, c)
            return item.text() if item else ""

        decision_id_str = cell(0)
        if not decision_id_str or decision_id_str == "—":
            return
        try:
            self._edit_id = int(decision_id_str)
        except ValueError:
            return

        # フォームに値を展開
        comp = cell(4)
        if comp in COMPONENTS:
            self._combo_comp.setCurrentText(comp)
        self._edit_from.setText(cell(5) if cell(5) != "—" else "")
        self._edit_to.setText(cell(6) if cell(6) != "—" else "")
        self._txt_rationale.setPlainText(cell(7) if cell(7) != "—" else "")
        result = cell(8)
        if result in RESULT_EVALS:
            self._combo_result.setCurrentText(result)

        # DB から詳細を取得して expected_effect も展開
        try:
            with self._db._conn() as conn:
                r = conn.execute(
                    "SELECT * FROM setup_decision_log WHERE decision_id=?",
                    (self._edit_id,)
                ).fetchone()
                if r:
                    d = dict(r)
                    chg = d.get("change_type", "")
                    if chg in CHANGE_TYPES:
                        self._combo_chg_type.setCurrentText(chg)
                    self._txt_expected.setPlainText(d.get("expected_effect") or "")
        except Exception:
            pass

        # UI を編集モードに切り替え
        self._form_label.setText(f"▼ Editing  ID:{self._edit_id}  —  {cell(1)}")
        self._form_label.setStyleSheet("color: #C00000; font-weight: bold;")
        self._btn_save.setText("✏️ 更新")
        self._btn_save.setStyleSheet("background-color: #FFC000; font-weight: bold;")
        self._btn_new.setVisible(True)

    def _refresh_table(self):
        show_all = self._chk_show_all.isChecked()
        if show_all:
            rows = self._db.get_all_setup_decisions()
        else:
            rows = self._db.get_setup_decisions(self._run_id) if self._run_id else []

        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for r in rows:
            ri = self._table.rowCount()
            self._table.insertRow(ri)
            vals = [
                r.get("decision_id", ""),
                r.get("run_id_from", ""),
                r.get("circuit", ""),
                r.get("rider", ""),
                r.get("component", ""),
                r.get("from_value", ""),
                r.get("to_value", ""),
                r.get("rationale", ""),
                r.get("result_eval", ""),
            ]
            for ci, val in enumerate(vals):
                item = QTableWidgetItem(str(val) if val is not None else "—")
                # Result列を色付け
                if ci == 8:
                    v = str(val or "")
                    if v == "POSITIVE":
                        item.setForeground(QColor(0, 150, 60))
                    elif v == "NEGATIVE":
                        item.setForeground(QColor(200, 40, 40))
                    elif v == "NEUTRAL":
                        item.setForeground(QColor(100, 100, 100))
                # 現在選択中のRunを強調
                if show_all and ci == 1 and str(val) == self._run_id:
                    item.setBackground(QColor(255, 255, 200))
                self._table.setItem(ri, ci, item)
        self._table.setSortingEnabled(True)
        total = len(rows)
        label = f"{'全' if show_all else '選択Run'}  {total} 件"
        self._lbl_count.setText(label)

    def _save_entry(self):
        """編集モードなら更新、新規モードなら追加。"""
        data = {
            "change_type":    self._combo_chg_type.currentText(),
            "component":      self._combo_comp.currentText(),
            "from_value":     self._edit_from.text().strip(),
            "to_value":       self._edit_to.text().strip(),
            "rationale":      self._txt_rationale.toPlainText().strip(),
            "expected_effect": self._txt_expected.toPlainText().strip(),
            "result_eval":    self._combo_result.currentText(),
        }
        if self._edit_id is not None:
            # 編集モード：既存レコードを更新
            self._db.update_setup_decision_full(self._edit_id, data)
        else:
            # 新規モード：新しいレコードを追加
            if not self._run_id:
                QMessageBox.warning(self, "未選択", "左パネルでRunを選択してください。")
                return
            run_to_idx = self._combo_run_to.currentIndex()
            run_to_data = self._combo_run_to.itemData(run_to_idx)
            data.update({
                "run_id_from":    self._run_id,
                "run_id_to":      run_to_data if run_to_data else None,
                "round":          self._run_meta.get("round"),
                "circuit":        self._run_meta.get("circuit"),
                "session":        self._run_meta.get("session"),
                "rider":          self._run_meta.get("rider"),
                "actual_effect":  None,
            })
            self._db.add_setup_decision(data)
        self._clear_form()
        self._refresh_table()

    def refresh(self):
        """DB変更時に外部から呼び出される。テーブルを再読み込みする。"""
        self._refresh_table()

    def _clear_form(self):
        self._edit_id = None
        self._combo_chg_type.setCurrentIndex(0)
        self._combo_comp.setCurrentIndex(0)
        self._edit_from.clear()
        self._edit_to.clear()
        self._txt_rationale.clear()
        self._txt_expected.clear()
        self._combo_result.setCurrentText("UNKNOWN")
        self._table.clearSelection()
        # UIを新規モードに戻す
        if hasattr(self, '_form_label'):
            self._form_label.setText("▼ New Setup Decision")
            self._form_label.setStyleSheet("")
        if hasattr(self, '_btn_save'):
            self._btn_save.setText("＋ 追加")
            self._btn_save.setStyleSheet("")
        if hasattr(self, '_btn_new'):
            self._btn_new.setVisible(False)



# ════════════════════════════════════════════════════════════════════
# Quick Log タブ
# ════════════════════════════════════════════════════════════════════

class QuickLogTab(QWidget):
    """⚡ Quick Log — CSV不要、30秒でProblemを記録する最小UIタブ。"""

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._setup_ui()

    def set_run(self, run_id: str, meta: dict) -> None:
        """RunBrowserからの選択を反映する。"""
        self._run_selector.select_run_id(run_id)

    def refresh(self):
        """DB変更時に外部から呼び出される。Run選択コンボを再読み込みする。"""
        if hasattr(self, "_run_selector"):
            self._run_selector._load_circuits()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        title = QLabel("⚡ Quick Problem Log")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #0078D4;")
        lay.addWidget(title)

        # ── Run 情報ラベル（_RunSelectorWidget より先に初期化する — 順序重要）────────
        self._lbl_run_info = QLabel("Run未選択")
        self._lbl_run_info.setStyleSheet("color: #888; font-size: 10px;")

        # ── Run セレクタ（初期化中に _on_run_selected が呼ばれるため後で追加）────
        self._run_selector = _RunSelectorWidget(
            db=self._db,
            on_run_selected=self._on_run_selected,
        )
        lay.addWidget(self._run_selector)
        lay.addWidget(self._lbl_run_info)

        # ── フォーム ────────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(6)

        self._spin_lap = QSpinBox()
        self._spin_lap.setRange(0, 99)
        self._spin_lap.setSpecialValueText("—")
        form.addRow("Lap No:", self._spin_lap)

        self._combo_corner = QComboBox()
        self._combo_corner.addItem("NONE")
        for i in range(1, 20):
            self._combo_corner.addItem(f"T{i}")
        form.addRow("Corner:", self._combo_corner)

        self._combo_phase = QComboBox()
        self._combo_phase.addItems(PHASES)
        form.addRow("Phase:", self._combo_phase)

        self._combo_tag = QComboBox()
        self._combo_tag.addItems(PROBLEM_TAGS)
        form.addRow("Problem Tag:", self._combo_tag)

        self._txt_desc = QTextEdit()
        self._txt_desc.setFixedHeight(72)
        self._txt_desc.setPlaceholderText("詳細説明（任意）")
        form.addRow("Description:", self._txt_desc)

        self._combo_sev = QComboBox()
        self._combo_sev.addItems(SEVERITIES)
        form.addRow("Severity:", self._combo_sev)

        lay.addLayout(form)

        # ── ボタン行 ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾  Save Problem")
        btn_save.setFixedHeight(36)
        btn_save.setStyleSheet(
            "QPushButton { background: #107C10; color: white; border-radius: 6px;"
            " font-size: 13px; font-weight: bold; padding: 0 20px; }"
            "QPushButton:hover { background: #0E6B0E; }"
        )
        btn_save.clicked.connect(self._save)
        btn_clear = QPushButton("クリア")
        btn_clear.setFixedHeight(36)
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._lbl_result = QLabel("")
        self._lbl_result.setStyleSheet("color: #107C10; font-size: 10px;")
        lay.addWidget(self._lbl_result)

        lay.addStretch()

        self._current_run_id: str = ""
        self._current_meta: dict = {}

    def _on_run_selected(self, run_id: str) -> None:
        if not hasattr(self, '_lbl_result'):  # UI 初期化中の呼び出しは無視
            return
        self._current_run_id = run_id
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {}
        self._current_meta = meta
        circuit  = meta.get("circuit", "")
        rider    = meta.get("rider", "")
        run_no   = meta.get("run_no", "")
        session  = meta.get("session", "")
        self._lbl_run_info.setText(
            f"✅ {circuit}  |  {rider}  |  {session}  Run #{run_no}"
        )
        self._lbl_result.setText("")

    def _save(self) -> None:
        if not self._current_run_id:
            QMessageBox.warning(self, "警告", "Runを先に選択してください。")
            return
        corner_val = self._combo_corner.currentText()
        if corner_val == "NONE":
            corner_val = None
        data = {
            "run_id":      self._current_run_id,
            "round":       self._current_meta.get("round"),
            "circuit":     self._current_meta.get("circuit"),
            "session":     self._current_meta.get("session"),
            "rider":       self._current_meta.get("rider"),
            "run_no":      self._current_meta.get("run_no"),
            "lap_no":      self._spin_lap.value() or None,
            "corner":      corner_val,
            "phase":       self._combo_phase.currentText(),
            "problem_tag": self._combo_tag.currentText(),
            "description": self._txt_desc.toPlainText().strip(),
            "severity":    self._combo_sev.currentText(),
            "source":      "OBSERVATION",
        }
        try:
            self._db.add_problem_log(data)
        except Exception as e:
            QMessageBox.critical(self, "DB Error", str(e))
            return
        tag = data["problem_tag"]
        self._lbl_result.setText(f"✅ 保存完了: {tag}")
        self._clear_form()

    def _clear_form(self) -> None:
        self._spin_lap.setValue(0)
        self._combo_corner.setCurrentIndex(0)
        self._combo_phase.setCurrentIndex(0)
        self._combo_tag.setCurrentIndex(0)
        self._txt_desc.clear()
        self._combo_sev.setCurrentIndex(0)


# ════════════════════════════════════════════════════════════════════
# トレンド分析タブ
# ════════════════════════════════════════════════════════════════════

class TrendAnalysisTab(QWidget):
    # NOTE: dead code — MainWindow未登録。将来削除予定。SetupTrendTab が後継。
    """ライダー別・セッション別のパフォーマンストレンドを表示するタブ。"""

    _RIDER_COLORS = {"DA77": "#0078D4", "JA52": "#E86C00"}

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._has_pg = False
        self._setup_ui()
        self.refresh()

    # ── UI 構築 ─────────────────────────────────────────────────────
    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        # ── 左フィルターパネル ──────────────────────────────────
        filter_panel = QWidget()
        filter_panel.setFixedWidth(190)
        fl = QVBoxLayout(filter_panel)
        fl.setContentsMargins(0, 0, 8, 0)
        fl.setSpacing(4)

        fl.addWidget(QLabel("<b>フィルター</b>"))

        fl.addWidget(QLabel("ライダー"))
        self._cb_rider = QComboBox()
        self._cb_rider.addItems(["両方", "DA77", "JA52"])
        fl.addWidget(self._cb_rider)

        fl.addWidget(QLabel("ラウンド"))
        self._cb_round = QComboBox()
        self._cb_round.addItem("全て")
        fl.addWidget(self._cb_round)

        fl.addWidget(QLabel("セッション"))
        self._cb_session = QComboBox()
        self._cb_session.addItems(["全て", "FP", "QP", "WUP1", "WUP2", "RACE1", "RACE2"])
        fl.addWidget(self._cb_session)

        btn_refresh = QPushButton("🔄 データ更新")
        btn_refresh.clicked.connect(self.refresh)
        fl.addWidget(btn_refresh)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        fl.addWidget(sep)

        fl.addWidget(QLabel("<b>サマリー</b>"))
        self._lbl_summary = QLabel("—")
        self._lbl_summary.setWordWrap(True)
        self._lbl_summary.setStyleSheet("font-size: 11px; color: #444;")
        fl.addWidget(self._lbl_summary)
        fl.addStretch()

        root.addWidget(filter_panel)

        # ── 右エリア：サブタブ ────────────────────────────────────
        self._inner_tabs = QTabWidget()

        # 📈 Lap Times
        self._w_laptime = QWidget()
        lt_layout = QVBoxLayout(self._w_laptime)
        lt_layout.setContentsMargins(0, 0, 0, 0)
        try:
            import pyqtgraph as pg
            pg.setConfigOption("background", "w")
            pg.setConfigOption("foreground", "k")

            class _LapAxis(pg.AxisItem):
                """秒数を M'SS.00 形式で表示するカスタム軸。"""
                def tickStrings(self, values, scale, spacing):
                    out = []
                    for v in values:
                        try:
                            s = float(v)
                            if s <= 0:
                                out.append("")
                                continue
                            m = int(s) // 60
                            out.append(f"{m}'{s - m*60:05.2f}")
                        except Exception:
                            out.append("")
                    return out

            self._pw_best = pg.PlotWidget(
                title="Best Lap per Run",
                axisItems={"left": _LapAxis(orientation="left")},
            )
            self._pw_best.showGrid(x=True, y=True, alpha=0.3)
            self._pw_best.setLabel("left", "Lap Time")
            self._pw_best.addLegend(offset=(-10, 10))
            self._pw_all = pg.PlotWidget(
                title="All Laps — Scatter (outlap除く)",
                axisItems={"left": _LapAxis(orientation="left")},
            )
            self._pw_all.showGrid(x=True, y=True, alpha=0.3)
            self._pw_all.setLabel("left", "Lap Time")
            lt_layout.addWidget(_make_help_panel(
                self._pw_best,
                "Best Lap per Run",
                "Best Lap per Run（ランごとベストラップ）\n\n"
                "縦軸: ベストラップタイム (M'SS.00 形式)\n"
                "横軸: Run（Session + Run番号 + Rider）\n\n"
                "各ランのベストラップを折れ線で結んで\n"
                "ラウンド内のペース推移を確認できます。\n"
                "DA77 (青) / JA52 (橙) を色分け表示。",
            ), 3)
            lt_layout.addWidget(_make_help_panel(
                self._pw_all,
                "All Laps Scatter",
                "All Laps Scatter（全ラップ散布図）\n\n"
                "縦軸: ラップタイム (M'SS.00 形式)\n"
                "横軸: Run（outlap除く）\n\n"
                "全ラップを散布点で表示します。\n"
                "点が縦に広がるほど lap-to-lap ばらつきが大きく、\n"
                "集まるほどペースが安定しています。",
            ), 2)
            self._has_pg = True
        except ImportError:
            lt_layout.addWidget(QLabel("pyqtgraph が未インストールです。"))
        self._inner_tabs.addTab(self._w_laptime, "📈 Lap Times")

        # 📋 Performance Table
        self._tbl_perf = QTableWidget()
        self._tbl_perf.setAlternatingRowColors(True)
        self._tbl_perf.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_perf.setSortingEnabled(True)
        self._inner_tabs.addTab(self._tbl_perf, "📋 Performance")

        # 🔧 Setup History
        self._tbl_setup = QTableWidget()
        self._tbl_setup.setAlternatingRowColors(True)
        self._tbl_setup.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._inner_tabs.addTab(self._tbl_setup, "🔧 Setup History")

        # ⚠️ Problem Analysis
        self._w_problem = QWidget()
        prob_layout = QVBoxLayout(self._w_problem)
        prob_layout.setContentsMargins(0, 0, 0, 0)
        prob_splitter = QSplitter(Qt.Orientation.Vertical)
        if self._has_pg:
            import pyqtgraph as pg
            self._pw_prob = pg.PlotWidget(title="Problem Tag 頻度")
            self._pw_prob.showGrid(x=False, y=True, alpha=0.3)
            self._pw_prob.setLabel("left", "件数")
            prob_splitter.addWidget(self._pw_prob)
        self._tbl_prob = QTableWidget()
        self._tbl_prob.setAlternatingRowColors(True)
        prob_splitter.addWidget(self._tbl_prob)
        prob_layout.addWidget(prob_splitter)
        self._inner_tabs.addTab(self._w_problem, "⚠️ Problems")

        # 📊 Lap Log (全ラップ詳細)
        self._tbl_laplog = QTableWidget()
        self._tbl_laplog.setAlternatingRowColors(True)
        self._tbl_laplog.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_laplog.setSortingEnabled(True)
        self._inner_tabs.addTab(self._tbl_laplog, "📊 Lap Log")

        # 🦾 Suspension (速度帯別サスペンション分析)
        self._w_sus = QWidget()
        sus_v = QVBoxLayout(self._w_sus)
        sus_v.setContentsMargins(4, 4, 4, 4)
        sus_v.setSpacing(4)

        # ── フィルターバー ──
        sus_bar = QWidget()
        sus_bar_h = QHBoxLayout(sus_bar)
        sus_bar_h.setContentsMargins(0, 0, 0, 4)
        sus_bar_h.addWidget(QLabel("⚡ 速度帯:"))
        self._cb_speed_zone = QComboBox()
        self._cb_speed_zone.addItems(["全て", "低速 <80km/h", "中速 80-120km/h", "高速 >120km/h"])
        self._cb_speed_zone.currentIndexChanged.connect(self._on_sus_filter_changed)
        sus_bar_h.addWidget(self._cb_speed_zone)
        sus_bar_h.addSpacing(16)
        sus_bar_h.addWidget(QLabel("📊 Y軸:"))
        self._cb_sus_metric = QComboBox()
        self._cb_sus_metric.addItems(
            ["ApexSusF vs LapTime", "ApexSusR vs LapTime",
             "BrkSusF vs LapTime",  "BrkSusR vs LapTime",
             "ApexSusF vs ApexSusR (F/R姿勢)"])
        self._cb_sus_metric.currentIndexChanged.connect(self._on_sus_filter_changed)
        sus_bar_h.addWidget(self._cb_sus_metric)
        sus_bar_h.addStretch()
        self._lbl_sus_zone_info = QLabel("")
        self._lbl_sus_zone_info.setStyleSheet("color:#555; font-size:10px;")
        sus_bar_h.addWidget(self._lbl_sus_zone_info)
        sus_v.addWidget(sus_bar)

        # ── プロットエリア: メイン散布図 + 速度帯別バーチャート ──
        if self._has_pg:
            import pyqtgraph as pg
            sus_plot_split = QSplitter(Qt.Orientation.Horizontal)
            self._pw_sus_main = pg.PlotWidget()
            self._pw_sus_main.showGrid(x=True, y=True, alpha=0.3)
            self._pw_sus_main.addLegend(offset=(-10, 10))
            sus_plot_split.addWidget(self._pw_sus_main)
            self._pw_sus_zone = pg.PlotWidget(title="速度帯別 平均SusF / SusR (DA77|JA52)")
            self._pw_sus_zone.showGrid(x=False, y=True, alpha=0.3)
            self._pw_sus_zone.setLabel("left", "Sus Position (mm)")
            sus_plot_split.addWidget(self._pw_sus_zone)
            sus_plot_split.setSizes([700, 400])
            sus_v.addWidget(sus_plot_split, 2)

        # ── テーブル ──
        self._tbl_sus = QTableWidget()
        self._tbl_sus.setAlternatingRowColors(False)
        self._tbl_sus.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_sus.setSortingEnabled(True)
        self._tbl_sus.verticalHeader().setDefaultSectionSize(22)
        sus_v.addWidget(self._tbl_sus, 3)
        self._inner_tabs.addTab(self._w_sus, "🦾 Suspension")

        # 🔍 Analysis (FAST/SLOW比較 + 回路別問題トレンド)
        self._w_analysis = QWidget()
        ana_v = QVBoxLayout(self._w_analysis)
        ana_v.setContentsMargins(4, 4, 4, 4)
        ana_split = QSplitter(Qt.Orientation.Vertical)

        # ── 上部: FAST vs SLOW ──
        ana_top = QWidget()
        ana_top_v = QVBoxLayout(ana_top)
        ana_top_v.setContentsMargins(0, 0, 0, 0)
        ana_lbl = QLabel(
            "<b>🏁 FAST vs SLOW サスペンション比較</b>"
            "  <small style='color:#666;'>(上位30% vs 下位30% ラップ | "
            "負Δ = FAST時により沈む = 良い方向)</small>"
        )
        ana_lbl.setStyleSheet("padding:2px;")
        ana_top_v.addWidget(ana_lbl)
        if self._has_pg:
            self._pw_fast_slow = pg.PlotWidget()
            self._pw_fast_slow.showGrid(x=False, y=True, alpha=0.3)
            self._pw_fast_slow.setLabel("left", "FAST-SLOW Δ SusF (mm)")
            ana_top_v.addWidget(self._pw_fast_slow, 2)
        self._tbl_fast_slow = QTableWidget()
        self._tbl_fast_slow.setAlternatingRowColors(True)
        self._tbl_fast_slow.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        ana_top_v.addWidget(self._tbl_fast_slow, 2)
        ana_split.addWidget(ana_top)

        # ── 下部: 回路別問題タグ ──
        ana_bot = QWidget()
        ana_bot_v = QVBoxLayout(ana_bot)
        ana_bot_v.setContentsMargins(0, 0, 0, 0)
        ana_lbl2 = QLabel(
            "<b>🗺️ 回路別 問題タグ トレンド</b>"
            "  <small style='color:#666;'>(セル = DA77件数 | JA52件数)</small>"
        )
        ana_lbl2.setStyleSheet("padding:2px;")
        ana_bot_v.addWidget(ana_lbl2)
        self._tbl_circuit_prob = QTableWidget()
        self._tbl_circuit_prob.setAlternatingRowColors(True)
        self._tbl_circuit_prob.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        ana_bot_v.addWidget(self._tbl_circuit_prob)
        ana_split.addWidget(ana_bot)

        ana_split.setSizes([380, 280])
        ana_v.addWidget(ana_split)
        self._inner_tabs.addTab(self._w_analysis, "🔍 Analysis")

        # 📊 Perf Corr (パフォーマンス相関)
        self._w_perf_corr = QWidget()
        pc_layout = QVBoxLayout(self._w_perf_corr)
        pc_layout.setContentsMargins(4, 4, 4, 4)
        pc_lbl = QLabel("<b>パフォーマンス相関 — セッション別サスペンション vs ラップタイム</b>")
        pc_layout.addWidget(pc_lbl)
        self._tbl_perf_corr = QTableWidget()
        self._tbl_perf_corr.setAlternatingRowColors(True)
        self._tbl_perf_corr.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_perf_corr.setSortingEnabled(True)
        pc_layout.addWidget(self._tbl_perf_corr, 3)
        pc_sep = QFrame(); pc_sep.setFrameShape(QFrame.Shape.HLine)
        pc_layout.addWidget(pc_sep)
        pc_lbl2 = QLabel("<b>FAST vs SLOW サスペンション比較 (回路別)</b>")
        pc_layout.addWidget(pc_lbl2)
        self._tbl_perf_cmp = QTableWidget()
        self._tbl_perf_cmp.setAlternatingRowColors(True)
        self._tbl_perf_cmp.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        pc_layout.addWidget(self._tbl_perf_cmp, 2)
        self._inner_tabs.addTab(self._w_perf_corr, "📊 Perf Corr")

        # 📝 Session Notes (エンジニアノート + 問題タグ)
        self._w_notes = QWidget()
        notes_layout = QVBoxLayout(self._w_notes)
        notes_layout.setContentsMargins(4, 4, 4, 4)
        notes_splitter = QSplitter(Qt.Orientation.Horizontal)
        # 左: 問題タグ表
        self._tbl_tag_summary = QTableWidget()
        self._tbl_tag_summary.setAlternatingRowColors(True)
        self._tbl_tag_summary.setMaximumWidth(450)
        notes_splitter.addWidget(self._tbl_tag_summary)
        # 右: エンジニアノートテキスト
        from PyQt6.QtWidgets import QTextBrowser
        self._txt_notes = QTextBrowser()
        self._txt_notes.setOpenExternalLinks(False)
        notes_splitter.addWidget(self._txt_notes)
        notes_splitter.setSizes([420, 800])
        notes_layout.addWidget(notes_splitter)
        self._inner_tabs.addTab(self._w_notes, "📝 Session Notes")

        # 🎯 Observations (lap_observation_log 一覧)
        self._w_obs = QWidget()
        obs_layout = QVBoxLayout(self._w_obs)
        obs_layout.setContentsMargins(4, 4, 4, 4)
        obs_layout.setSpacing(4)
        # フィルター行
        obs_filter_row = QHBoxLayout()
        obs_filter_row.addWidget(QLabel("Type:"))
        self._cmb_obs_type = QComboBox()
        self._cmb_obs_type.addItems(["ALL", "GOOD", "BAD", "NEUTRAL"])
        self._cmb_obs_type.setFixedWidth(90)
        obs_filter_row.addWidget(self._cmb_obs_type)
        obs_filter_row.addWidget(QLabel("Rider:"))
        self._cmb_obs_rider = QComboBox()
        self._cmb_obs_rider.addItems(["ALL", "DA77", "JA52"])
        self._cmb_obs_rider.setFixedWidth(80)
        obs_filter_row.addWidget(self._cmb_obs_rider)
        btn_obs_refresh = QPushButton("🔄")
        btn_obs_refresh.setFixedWidth(36)
        btn_obs_refresh.clicked.connect(self._refresh_observations)
        obs_filter_row.addWidget(btn_obs_refresh)
        self._lbl_obs_count = QLabel("")
        self._lbl_obs_count.setStyleSheet("color:#888; font-size:10px;")
        obs_filter_row.addWidget(self._lbl_obs_count)
        obs_filter_row.addStretch()
        obs_layout.addLayout(obs_filter_row)
        # テーブル
        self._tbl_obs = QTableWidget()
        self._tbl_obs.setColumnCount(9)
        self._tbl_obs.setHorizontalHeaderLabels(
            ["Type", "Tag", "Rider", "Circuit", "Session",
             "Lap", "Lap Time", "Comment", "Created"])
        self._tbl_obs.setAlternatingRowColors(True)
        self._tbl_obs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_obs.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_obs.horizontalHeader().setStretchLastSection(True)
        self._tbl_obs.setSortingEnabled(True)
        obs_layout.addWidget(self._tbl_obs)
        self._inner_tabs.addTab(self._w_obs, "🎯 Observations")

        # Observations フィルター変更
        self._cmb_obs_type.currentIndexChanged.connect(self._refresh_observations)
        self._cmb_obs_rider.currentIndexChanged.connect(self._refresh_observations)

        root.addWidget(self._inner_tabs, 1)

        # フィルター変更でコネクト
        self._cb_rider.currentIndexChanged.connect(self._on_filter_changed)
        self._cb_round.currentIndexChanged.connect(self._on_filter_changed)
        self._cb_session.currentIndexChanged.connect(self._on_filter_changed)

    # ── データ更新 ───────────────────────────────────────────────────
    def refresh(self):
        """DBとExcelからデータを再読み込みしてラウンドComboBoxと静的ビューを更新。"""
        rounds = self._db.get_all_rounds()
        prev = self._cb_round.currentText()
        self._cb_round.blockSignals(True)
        self._cb_round.clear()
        self._cb_round.addItem("全て")
        for r in rounds:
            self._cb_round.addItem(r)
        idx = self._cb_round.findText(prev)
        if idx >= 0:
            self._cb_round.setCurrentIndex(idx)
        self._cb_round.blockSignals(False)

        # Excelデータをキャッシュ（フィルター変更時に再ロードしない）
        try:
            self._perf_corr_cache = self._db.get_perf_correlation()
        except Exception:
            self._perf_corr_cache = ([], [], [], [])
        try:
            self._trend_notes_cache = self._db.get_trend_notes()
        except Exception:
            self._trend_notes_cache = {"tags": [], "rider_tags": {}, "notes": []}

        self._update_views()

    def _on_filter_changed(self, _=None):
        self._update_views()

    def _refresh_observations(self):
        """🎯 Observations タブのテーブルを更新する。"""
        obs_type = self._cmb_obs_type.currentText()
        rider    = self._cmb_obs_rider.currentText()
        try:
            rows = self._db.get_lap_observations(
                obs_type = obs_type if obs_type != "ALL" else None,
                rider    = rider    if rider    != "ALL" else None,
            )
        except Exception:
            rows = []

        # タイプ別カラー
        type_colors = {"GOOD": "#1a6b2a", "BAD": "#6b1a1a", "NEUTRAL": "#4a4a1a"}
        type_icons  = {"GOOD": "✅", "BAD": "❌", "NEUTRAL": "〇"}

        self._tbl_obs.setSortingEnabled(False)
        self._tbl_obs.setRowCount(len(rows))
        for r, obs in enumerate(rows):
            lt = obs.get("lap_time_s") or 0
            try:
                lt = float(lt)
                mm = int(lt) // 60
                lt_str = f"{mm}'{lt - mm*60:05.2f}"
            except (TypeError, ValueError):
                lt_str = "—"

            otype = obs.get("observation_type", "")
            icon  = type_icons.get(otype, "")
            bg    = type_colors.get(otype, "#1e1e1e")

            cells = [
                f"{icon} {otype}",
                obs.get("observation_tag", ""),
                obs.get("rider", ""),
                obs.get("circuit", ""),
                obs.get("session", ""),
                str(obs.get("lap_no", "")),
                lt_str,
                obs.get("comment", ""),
                (obs.get("created_at") or "")[:16],
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setBackground(QColor(bg))
                self._tbl_obs.setItem(r, c, item)

        self._tbl_obs.setSortingEnabled(True)
        self._tbl_obs.resizeColumnsToContents()
        self._lbl_obs_count.setText(f"{len(rows)} records")

    def _on_sus_filter_changed(self, _=None):
        """Suspensionタブ内の速度帯/メトリック変更時のみ再描画。"""
        sus_data = getattr(self, "_sus_cache", [])
        self._build_suspension_view(sus_data)

    def _get_filters(self) -> tuple:
        rider_sel = self._cb_rider.currentText()
        rider = None if rider_sel == "両方" else rider_sel
        round_sel = self._cb_round.currentText()
        round_s = None if round_sel == "全て" else round_sel
        session_sel = self._cb_session.currentText()
        session_s = None if session_sel == "全て" else session_sel
        return rider, round_s, session_s

    def _update_views(self):
        rider, round_s, session_s = self._get_filters()
        laps     = self._db.get_trend_laps(rider, round_s, session_s)
        runs     = self._db.get_trend_runs(rider, round_s, session_s)
        problems = self._db.get_trend_problems(rider, round_s, session_s)
        sus_data = self._db.get_lap_suspension(rider, round_s, session_s)

        valid_laps = [l for l in laps if not l.get("is_outlap") and l.get("lap_time_s")]
        riders = sorted(set(l.get("rider", "") for l in laps if l.get("rider")))
        self._lbl_summary.setText(
            f"Runs: {len(runs)}\n"
            f"Laps: {len(valid_laps)}\n"
            f"Sus Laps: {len(sus_data)}\n"
            f"Problems: {len(problems)}\n"
            f"Riders: {', '.join(riders)}"
        )

        self._build_laptime_plot(laps, runs)
        self._build_perf_table(laps, runs)
        self._build_setup_table(runs)
        self._build_problem_view(problems)
        self._build_laplog_table(laps)

        # sus_data をキャッシュ（速度帯フィルター変更時に再利用）
        self._sus_cache = sus_data
        self._build_suspension_view(sus_data)

        # Analysis tab (FAST/SLOW + Circuit Problem Trend)
        notes = getattr(self, "_trend_notes_cache", {"tags": [], "rider_tags": {}, "notes": []})
        self._build_analysis_view(sus_data, notes)

        # Perf Corr / Session Notes はキャッシュから
        pc = getattr(self, "_perf_corr_cache", ([], [], [], []))
        self._build_perf_corr_tables(pc, rider, round_s)
        self._build_session_notes(notes, rider)

    # ── ユーティリティ ───────────────────────────────────────────────
    @staticmethod
    def _fmt(s) -> str:
        """秒数を M'SS.000 形式（motorsport標準）に変換。"""
        if s is None:
            return "—"
        try:
            s = float(s)
        except (ValueError, TypeError):
            return str(s)
        m = int(s) // 60
        sec = s - m * 60
        return f"{m}'{sec:06.3f}"

    @staticmethod
    def _fmt_delta(delta_s) -> str:
        """差分秒数を +0.000s 形式に変換。"""
        if delta_s is None:
            return "—"
        try:
            d = float(delta_s)
        except (ValueError, TypeError):
            return "—"
        if abs(d) < 0.001:
            return "—"
        return f"+{d:.3f}s" if d > 0 else f"{d:.3f}s"

    # ── 📈 Lap Time プロット ─────────────────────────────────────────
    def _build_laptime_plot(self, laps: list, runs: list):
        if not self._has_pg:
            return
        import pyqtgraph as pg

        run_ids = [r["run_id"] for r in runs]
        x_map   = {rid: i for i, rid in enumerate(run_ids)}
        x_labels = [
            f"{r.get('session','?')}R{r.get('run_no','?')}\n{r.get('rider','?')}"
            for r in runs
        ]

        self._pw_best.clear()
        self._pw_all.clear()

        for pw in (self._pw_best, self._pw_all):
            pw.getAxis("bottom").setTicks([list(enumerate(x_labels))] if x_labels else [[]])

        for rider, color in self._RIDER_COLORS.items():
            rider_runs = [r for r in runs if r.get("rider") == rider]
            best_x, best_y, all_x, all_y = [], [], [], []

            for r in rider_runs:
                rid = r["run_id"]
                xi = x_map.get(rid)
                if xi is None:
                    continue
                r_laps = [l for l in laps if l["run_id"] == rid
                          and not l.get("is_outlap") and l.get("lap_time_s")]
                if not r_laps:
                    continue
                times = [float(l["lap_time_s"]) for l in r_laps]
                best_x.append(xi)
                best_y.append(min(times))
                jitter = 0.12 if rider == "JA52" else -0.12
                for t in times:
                    all_x.append(xi + jitter)
                    all_y.append(t)

            pen   = pg.mkPen(color, width=2)
            brush = pg.mkBrush(color)

            if best_x:
                self._pw_best.plot(best_x, best_y, pen=pen, name=rider)
                self._pw_best.plot(best_x, best_y, pen=None, symbol="o",
                                   symbolSize=11, symbolBrush=brush,
                                   symbolPen=pg.mkPen("w", width=1.5))

            if all_x:
                r_c = int(color[1:3], 16)
                g_c = int(color[3:5], 16)
                b_c = int(color[5:7], 16)
                self._pw_all.plot(all_x, all_y, pen=None, symbol="o",
                                  symbolSize=7,
                                  symbolBrush=pg.mkBrush(r_c, g_c, b_c, 140),
                                  symbolPen=pg.mkPen(r_c, g_c, b_c, 200),
                                  name=rider)

    # ── 📋 Performance テーブル ──────────────────────────────────────
    def _build_perf_table(self, laps: list, runs: list):
        cols    = ["Round", "Session", "Run", "Rider", "Laps",
                   "Best Lap", "Avg Lap", "Worst Lap",
                   "Gap to Best", "Improvement"]
        headers = cols
        self._tbl_perf.setSortingEnabled(False)
        self._tbl_perf.setColumnCount(len(cols))
        self._tbl_perf.setHorizontalHeaderLabels(headers)

        from collections import defaultdict
        rows_data = []
        for r in runs:
            rid = r["run_id"]
            r_laps = [l for l in laps if l["run_id"] == rid
                      and not l.get("is_outlap") and l.get("lap_time_s")]
            if not r_laps:
                continue
            times = [float(l["lap_time_s"]) for l in r_laps]
            improvement = times[0] - times[-1] if len(times) >= 2 else 0.0
            rows_data.append({
                "round": r.get("round", ""), "session": r.get("session", ""),
                "run_no": r.get("run_no", ""), "rider": r.get("rider", ""),
                "n_laps": len(times), "best": min(times),
                "avg": sum(times) / len(times), "worst": max(times),
                "improvement": improvement,
            })

        # セッション別ベスト（ギャップ計算用）
        session_bests: dict = defaultdict(lambda: float("inf"))
        for rd in rows_data:
            key = (rd["round"], rd["session"])
            session_bests[key] = min(session_bests[key], rd["best"])

        self._tbl_perf.setRowCount(len(rows_data))
        for i, rd in enumerate(rows_data):
            key = (rd["round"], rd["session"])
            gap = rd["best"] - session_bests[key]
            values = [
                rd["round"], rd["session"], f"R{rd['run_no']}", rd["rider"],
                str(rd["n_laps"]),
                self._fmt(rd["best"]), self._fmt(rd["avg"]), self._fmt(rd["worst"]),
                f"+{gap:.3f}s" if gap > 0.001 else "—",
                f"{rd['improvement']:+.3f}s" if abs(rd["improvement"]) > 0.001 else "—",
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if gap < 0.001 and j >= 5:  # ベストラン行をハイライト
                    item.setBackground(QColor("#E8F5E9"))
                self._tbl_perf.setItem(i, j, item)

        self._tbl_perf.resizeColumnsToContents()
        self._tbl_perf.horizontalHeader().setStretchLastSection(True)
        self._tbl_perf.setSortingEnabled(True)

    # ── 🔧 Setup History テーブル ────────────────────────────────────
    def _build_setup_table(self, runs: list):
        run_ids  = [r["run_id"] for r in runs]
        detailed = self._db.get_trend_runs_detail(run_ids)

        key_cols = ["session", "run_no", "rider",
                    "tyre_front", "tyre_rear",
                    "f_comp", "f_reb", "f_offset",
                    "r_comp", "r_reb", "ride_hgt",
                    "perf_best_lap", "perf_n_laps", "comment"]
        headers  = ["Session", "Run", "Rider",
                    "Tyre F", "Tyre R",
                    "F Comp", "F Reb", "F Offset",
                    "R Comp", "R Reb", "Ride Hgt",
                    "Best Lap", "Laps", "Comment"]

        self._tbl_setup.setColumnCount(len(headers))
        self._tbl_setup.setHorizontalHeaderLabels(headers)
        self._tbl_setup.setRowCount(len(detailed))

        # 前行との差異を検出してハイライトするため値を収集
        prev_vals: dict = {}
        for i, r in enumerate(detailed):
            for j, col in enumerate(key_cols):
                v = r.get(col)
                if col == "perf_best_lap" and v is not None:
                    display = self._fmt(v)
                elif col == "run_no":
                    display = f"R{v}" if v is not None else "—"
                else:
                    display = str(v) if v is not None else "—"

                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                # セットアップ値が前行から変化した場合に黄色ハイライト
                setup_cols = {"f_comp", "f_reb", "f_offset", "r_comp", "r_reb", "ride_hgt",
                              "tyre_front", "tyre_rear"}
                if col in setup_cols and v is not None:
                    if prev_vals.get(col) is not None and str(prev_vals[col]) != str(v):
                        item.setBackground(QColor("#FFF9C4"))
                    prev_vals[col] = v

                self._tbl_setup.setItem(i, j, item)

        self._tbl_setup.resizeColumnsToContents()
        self._tbl_setup.horizontalHeader().setStretchLastSection(True)

    # ── ⚠️ Problem Analysis ─────────────────────────────────────────
    def _build_problem_view(self, problems: list):
        from collections import Counter
        tag_counts = Counter(p.get("problem_tag", "?") for p in problems)
        tags_sorted = sorted(tag_counts.items(), key=lambda x: -x[1])

        # バーチャート
        if self._has_pg:
            import pyqtgraph as pg
            self._pw_prob.clear()
            if tags_sorted:
                x = list(range(len(tags_sorted)))
                y = [cnt for _, cnt in tags_sorted]
                labels = [tag for tag, _ in tags_sorted]
                bargraph = pg.BarGraphItem(x=x, height=y, width=0.6,
                                           brush="#E74C3C", pen=pg.mkPen("w", width=0.5))
                self._pw_prob.addItem(bargraph)
                self._pw_prob.getAxis("bottom").setTicks([list(enumerate(labels))])
                self._pw_prob.setTitle("Problem Tag 頻度")
            else:
                # データなし時のメッセージ
                self._pw_prob.setTitle("")
                msg = pg.TextItem(
                    text="Problem Log にデータがありません\n"
                         "波形タブで問題を選択し「Problem Log へ送る」ボタンで登録できます",
                    color="#AAAAAA", anchor=(0.5, 0.5))
                msg.setPos(0.5, 0.5)
                self._pw_prob.addItem(msg)
                self._pw_prob.setXRange(0, 1)
                self._pw_prob.setYRange(0, 1)

        # テーブル
        cols = ["Tag", "件数", "Max Severity", "Riders", "Sessions", "Corners"]
        self._tbl_prob.setColumnCount(len(cols))
        self._tbl_prob.setHorizontalHeaderLabels(cols)
        self._tbl_prob.setRowCount(len(tags_sorted))

        sev_map: dict = {}
        for p in problems:
            tag = p.get("problem_tag", "?")
            sev_map[tag] = max(sev_map.get(tag, 0), int(p.get("severity") or 0))

        for i, (tag, cnt) in enumerate(tags_sorted):
            tag_probs = [p for p in problems if p.get("problem_tag") == tag]
            riders   = ", ".join(sorted({p.get("rider", "") for p in tag_probs if p.get("rider")}))
            sessions = ", ".join(sorted({p.get("session", "") for p in tag_probs if p.get("session")}))
            corners  = ", ".join(sorted({str(p.get("corner", "")) for p in tag_probs if p.get("corner")}))
            sev = sev_map.get(tag, 0)
            values = [tag, str(cnt), str(sev) if sev else "—", riders, sessions, corners]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if cnt >= 3:
                    item.setBackground(QColor("#FFEBEE"))
                elif cnt >= 2:
                    item.setBackground(QColor("#FFF3E0"))
                self._tbl_prob.setItem(i, j, item)

        self._tbl_prob.resizeColumnsToContents()
        self._tbl_prob.horizontalHeader().setStretchLastSection(True)

    # ── 📊 Lap Log テーブル ─────────────────────────────────────────
    def _build_laplog_table(self, laps: list):
        cols    = ["Round", "Circuit", "Session", "Run", "Lap", "Rider",
                   "Lap Time", "Outlap", "Tyre F", "Tyre R",
                   "Weather", "Track °C", "Air °C"]
        self._tbl_laplog.setSortingEnabled(False)
        self._tbl_laplog.setColumnCount(len(cols))
        self._tbl_laplog.setHorizontalHeaderLabels(cols)
        self._tbl_laplog.setRowCount(len(laps))

        for i, l in enumerate(laps):
            lt = l.get("lap_time_s")
            is_out = bool(l.get("is_outlap"))
            values = [
                l.get("round", ""), l.get("circuit", ""),
                l.get("session", ""), f"R{l.get('run_no','?')}",
                str(l.get("lap_no", "")), l.get("rider", ""),
                self._fmt(lt),
                "✓" if is_out else "",
                l.get("tyre_front", "") or "—",
                l.get("tyre_rear", "") or "—",
                l.get("weather", "") or "—",
                str(l.get("track_temp", "")) or "—",
                str(l.get("air_temp", "")) or "—",
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if is_out:
                    item.setForeground(QColor("#999999"))
                # ライダー色分け
                rider = l.get("rider", "")
                if rider in self._RIDER_COLORS and not is_out:
                    c = self._RIDER_COLORS[rider]
                    item.setBackground(QColor(c).lighter(195))
                self._tbl_laplog.setItem(i, j, item)

        self._tbl_laplog.resizeColumnsToContents()
        self._tbl_laplog.horizontalHeader().setStretchLastSection(True)
        self._tbl_laplog.setSortingEnabled(True)

    # ── 🦾 Suspension ビュー (速度帯フィルター対応) ──────────────────
    @staticmethod
    def _valid_sus(sus_data: list) -> list:
        """outlap除去 + 極端な異常値除去の共通フィルター。"""
        return [d for d in sus_data
                if d.get("lap_time_s")
                and float(d["lap_time_s"]) > 85
                and float(d["lap_time_s"]) < 360
                and d.get("lap_no") and int(d["lap_no"]) > 0
                and d.get("apex_spd_avg")
                and float(d["apex_spd_avg"]) > 10]

    def _build_suspension_view(self, sus_data: list):
        """速度帯フィルター付きサスペンション分析ビュー。"""
        zone = getattr(self._cb_speed_zone, "currentText", lambda: "全て")()
        metric = getattr(self._cb_sus_metric, "currentText",
                         lambda: "ApexSusF vs LapTime")()

        valid = self._valid_sus(sus_data)

        # ── 速度帯フィルター ──
        if zone == "低速 <80km/h":
            filtered = [d for d in valid if float(d["apex_spd_avg"]) < 80]
        elif zone == "中速 80-120km/h":
            filtered = [d for d in valid if 80 <= float(d["apex_spd_avg"]) <= 120]
        elif zone == "高速 >120km/h":
            filtered = [d for d in valid if float(d["apex_spd_avg"]) > 120]
        else:
            filtered = valid

        # ── メトリック選択 ──
        if metric == "ApexSusR vs LapTime":
            y_key, y_lbl = "apex_susR_avg", "ApexSusR (mm)"
            x_key, x_lbl = "lap_time_s",    "Lap Time (s)"
        elif metric == "BrkSusF vs LapTime":
            y_key, y_lbl = "brk_susF_avg",  "BrkSusF (mm)"
            x_key, x_lbl = "lap_time_s",    "Lap Time (s)"
        elif metric == "BrkSusR vs LapTime":
            y_key, y_lbl = "brk_susR_avg",  "BrkSusR (mm)"
            x_key, x_lbl = "lap_time_s",    "Lap Time (s)"
        elif metric == "ApexSusF vs ApexSusR (F/R姿勢)":
            y_key, y_lbl = "apex_susF_avg", "ApexSusF (mm)"   # Y軸=フロント
            x_key, x_lbl = "apex_susR_avg", "ApexSusR (mm)"   # X軸=リア
        else:  # デフォルト
            y_key, y_lbl = "apex_susF_avg", "ApexSusF (mm)"
            x_key, x_lbl = "lap_time_s",    "Lap Time (s)"

        # ── ゾーン情報ラベル ──
        parts = []
        for rider in ("DA77", "JA52"):
            rpts = [d for d in filtered if d.get("rider") == rider
                    and d.get("apex_susF_avg") and d.get("apex_susR_avg")]
            if rpts:
                af = sum(float(d["apex_susF_avg"]) for d in rpts) / len(rpts)
                ar = sum(float(d["apex_susR_avg"]) for d in rpts) / len(rpts)
                parts.append(f"{rider}: n={len(rpts)} | ApexSusF={af:.1f}mm | ApexSusR={ar:.1f}mm")
        if hasattr(self, "_lbl_sus_zone_info"):
            self._lbl_sus_zone_info.setText("   ".join(parts))

        # ── メイン散布図 ──
        if self._has_pg and hasattr(self, "_pw_sus_main"):
            import pyqtgraph as pg
            self._pw_sus_main.clear()
            title = f"{y_lbl} vs {x_lbl}"
            if zone != "全て":
                title += f"  [{zone}]"
            self._pw_sus_main.setTitle(title)
            self._pw_sus_main.setLabel("left", y_lbl)
            self._pw_sus_main.setLabel("bottom", x_lbl)

            for rider, color in self._RIDER_COLORS.items():
                pts = [(float(d[x_key]), float(d[y_key]))
                       for d in filtered
                       if d.get("rider") == rider
                       and d.get(x_key) and d.get(y_key)]
                if not pts:
                    continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                rc, gc, bc = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
                self._pw_sus_main.plot(
                    xs, ys, pen=None, symbol="o", symbolSize=8,
                    symbolBrush=pg.mkBrush(rc, gc, bc, 170),
                    symbolPen=pg.mkPen(rc, gc, bc, 220), name=rider)
                # 平均線
                if xs and y_key != x_key:
                    mean_y = sum(ys) / len(ys)
                    self._pw_sus_main.addItem(pg.InfiniteLine(
                        pos=mean_y, angle=0,
                        pen=pg.mkPen(rc, gc, bc, 120, width=1.5,
                                     style=Qt.PenStyle.DashLine),
                        label=f"{rider} avg:{mean_y:.1f}mm",
                        labelOpts={"color": color, "position": 0.05}))

        # ── 速度帯別バーチャート (右側) ──
        if self._has_pg and hasattr(self, "_pw_sus_zone"):
            import pyqtgraph as pg
            self._pw_sus_zone.clear()
            zone_defs = [
                ("低速\n<80", lambda d: float(d["apex_spd_avg"]) < 80),
                ("中速\n80-120", lambda d: 80 <= float(d["apex_spd_avg"]) <= 120),
                ("高速\n>120", lambda d: float(d["apex_spd_avg"]) > 120),
            ]
            x_ticks, bar_items = [], []
            x_base = 0.0
            for z_lbl, z_fn in zone_defs:
                z_pts = [d for d in valid if d.get("apex_spd_avg") and z_fn(d)]
                for ri, (rider, color) in enumerate(self._RIDER_COLORS.items()):
                    rz = [d for d in z_pts
                          if d.get("rider") == rider
                          and d.get("apex_susF_avg") and d.get("apex_susR_avg")]
                    if rz:
                        avg_f = sum(float(d["apex_susF_avg"]) for d in rz) / len(rz)
                        avg_r = sum(float(d["apex_susR_avg"]) for d in rz) / len(rz)
                        xpos = x_base + ri * 0.45
                        rc, gc, bc = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
                        # SusF (solid), SusR (transparent)
                        self._pw_sus_zone.addItem(pg.BarGraphItem(
                            x=[xpos], height=[avg_f], width=0.4,
                            brush=pg.mkBrush(rc, gc, bc, 220),
                            pen=pg.mkPen("k", width=0.5)))
                        self._pw_sus_zone.addItem(pg.BarGraphItem(
                            x=[xpos], height=[avg_r], width=0.4,
                            brush=pg.mkBrush(rc, gc, bc, 80),
                            pen=pg.mkPen(rc, gc, bc, 180, width=1.5,
                                         style=Qt.PenStyle.DashLine)))
                x_ticks.append((x_base + 0.22, z_lbl))
                x_base += 1.3
            if x_ticks:
                self._pw_sus_zone.getAxis("bottom").setTicks([x_ticks])

        # ── テーブル ──
        db_keys = ["round", "circuit", "session", "run_no", "lap_no", "rider",
                   "lap_time_s", "apex_spd_avg",
                   "apex_susF_avg", "apex_susR_avg",
                   "brk_susF_avg", "brk_susR_avg",
                   "fullbrk_susF", "fullbrk_susR",
                   "lap_susF_mean", "lap_susF_min", "lap_susF_max", "lap_susR_mean"]
        col_hdrs = ["Round", "Circuit", "Sess", "Run", "Lap", "Rider",
                    "Lap Time", "ApexSpd\n(km/h)",
                    "ApexSusF\n(mm)", "ApexSusR\n(mm)",
                    "BrkSusF\n(mm)", "BrkSusR\n(mm)",
                    "FullBrk\nSusF", "FullBrk\nSusR",
                    "SusF\nMean", "SusF\nMin", "SusF\nMax", "SusR\nMean"]

        self._tbl_sus.setSortingEnabled(False)
        self._tbl_sus.setColumnCount(len(col_hdrs))
        self._tbl_sus.setHorizontalHeaderLabels(col_hdrs)
        self._tbl_sus.setRowCount(len(filtered))

        # ライダー別に交互背景色（視認性を高める）
        RIDER_BG = {
            "DA77": ("#1A3A5C", "#FFFFFF"),   # 濃紺テキスト → 明るい青系背景
            "JA52": ("#5C2A00", "#FFFFFF"),   # 濃茶テキスト → 明るいオレンジ系背景
        }
        RIDER_FILL = {
            "DA77": QColor("#D0E8FF"),   # 青系
            "JA52": QColor("#FFE0B2"),   # オレンジ系
        }
        for i, d in enumerate(filtered):
            rider = d.get("rider", "")
            bg = RIDER_FILL.get(rider, QColor("#EEEEEE"))
            fg = QColor(RIDER_BG.get(rider, ("#000000", "#000000"))[0])
            for j, key in enumerate(db_keys):
                v = d.get(key)
                if key == "lap_time_s":
                    display = self._fmt(v)
                elif key == "run_no":
                    display = f"R{v}" if v is not None else "—"
                elif isinstance(v, float):
                    display = f"{v:.2f}"
                elif v is None:
                    display = "—"
                else:
                    display = str(v)
                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setBackground(bg)
                item.setForeground(fg)
                self._tbl_sus.setItem(i, j, item)

        self._tbl_sus.resizeColumnsToContents()
        self._tbl_sus.horizontalHeader().setStretchLastSection(True)
        self._tbl_sus.setSortingEnabled(True)

    # ── 🔍 Analysis (FAST/SLOW + 回路別問題トレンド) ─────────────────
    def _build_analysis_view(self, sus_data: list, notes_data: dict):
        """FAST vs SLOW サスペンション比較 + 回路別問題タグ クロス集計。"""
        from collections import defaultdict

        valid = self._valid_sus(sus_data)

        # ════════════════════════════════════════════════
        # 1) FAST vs SLOW 比較 (ライダー×回路 ごと)
        # ════════════════════════════════════════════════
        groups: dict = defaultdict(list)
        for d in valid:
            groups[(d.get("rider"), d.get("circuit"))].append(d)

        def avg_key(lst, key):
            vals = [float(d[key]) for d in lst if d.get(key)]
            return sum(vals) / len(vals) if vals else None

        comp_rows = []
        for (rider, circuit), laps in sorted(groups.items()):
            if len(laps) < 4:
                continue
            times = sorted(float(d["lap_time_s"]) for d in laps)
            n3 = max(1, len(times) // 3)
            fast_t = set(times[:n3])
            slow_t = set(times[-n3:])
            fast_laps = [d for d in laps if float(d["lap_time_s"]) in fast_t]
            slow_laps = [d for d in laps if float(d["lap_time_s"]) in slow_t]

            def delta(fval, sval):
                if fval is None or sval is None:
                    return None
                return round(fval - sval, 2)

            faf = avg_key(fast_laps, "apex_susF_avg")
            saf = avg_key(slow_laps, "apex_susF_avg")
            far = avg_key(fast_laps, "apex_susR_avg")
            sar = avg_key(slow_laps, "apex_susR_avg")
            fbf = avg_key(fast_laps, "brk_susF_avg")
            sbf = avg_key(slow_laps, "brk_susF_avg")
            fbr = avg_key(fast_laps, "brk_susR_avg")
            sbr = avg_key(slow_laps, "brk_susR_avg")

            comp_rows.append({
                "rider": rider or "?", "circuit": circuit or "?",
                "n": len(laps), "n3": n3,
                "fast_best": min(times[:n3]), "slow_best": max(times[-n3:]),
                "fApexF": faf, "sApexF": saf, "dApexF": delta(faf, saf),
                "fApexR": far, "sApexR": sar, "dApexR": delta(far, sar),
                "fBrkF": fbf,  "sBrkF": sbf,  "dBrkF":  delta(fbf, sbf),
                "fBrkR": fbr,  "sBrkR": sbr,  "dBrkR":  delta(fbr, sbr),
            })

        # バーチャート: Δ ApexSusF per rider+circuit
        if self._has_pg and hasattr(self, "_pw_fast_slow"):
            import pyqtgraph as pg
            self._pw_fast_slow.clear()
            x_ticks = []
            for xi, row in enumerate(comp_rows):
                color = self._RIDER_COLORS.get(row["rider"], "#888")
                rc, gc, bc = int(color[1:3],16), int(color[3:5],16), int(color[5:7],16)
                d_f = row.get("dApexF") or 0
                d_r = row.get("dApexR") or 0
                # SusF bar (solid), SusR bar (behind, lighter)
                self._pw_fast_slow.addItem(pg.BarGraphItem(
                    x=[xi - 0.18], height=[d_f], width=0.32,
                    brush=pg.mkBrush(rc, gc, bc, 220),
                    pen=pg.mkPen("k", width=0.5)))
                self._pw_fast_slow.addItem(pg.BarGraphItem(
                    x=[xi + 0.18], height=[d_r], width=0.32,
                    brush=pg.mkBrush(rc, gc, bc, 90),
                    pen=pg.mkPen(rc, gc, bc, 180, width=1)))
                x_ticks.append((xi, f"{row['rider']}\n{(row['circuit'] or '')[:7]}"))
            self._pw_fast_slow.setTitle(
                "FAST vs SLOW Δ: ■=ApexSusF  □=ApexSusR  (負=FAST時に沈む=良方向)")
            self._pw_fast_slow.addItem(pg.InfiniteLine(
                pos=0, angle=0, pen=pg.mkPen("k", width=1)))
            if x_ticks:
                self._pw_fast_slow.getAxis("bottom").setTicks([x_ticks])
                self._pw_fast_slow.getAxis("bottom").setStyle(tickFont=None)

        # FAST/SLOW テーブル
        fs_hdrs = ["Rider", "Circuit", "N", "n/3",
                   "FAST Best", "SLOW Best",
                   "FAST\nApexF", "SLOW\nApexF", "Δ ApexF",
                   "FAST\nApexR", "SLOW\nApexR", "Δ ApexR",
                   "FAST\nBrkF",  "SLOW\nBrkF",  "Δ BrkF",
                   "FAST\nBrkR",  "SLOW\nBrkR",  "Δ BrkR"]
        self._tbl_fast_slow.setSortingEnabled(False)
        self._tbl_fast_slow.setColumnCount(len(fs_hdrs))
        self._tbl_fast_slow.setHorizontalHeaderLabels(fs_hdrs)
        self._tbl_fast_slow.setRowCount(len(comp_rows))
        self._tbl_fast_slow.verticalHeader().setDefaultSectionSize(22)

        delta_cols = {8, 11, 14, 17}  # Δ列インデックス

        for i, row in enumerate(comp_rows):
            color = self._RIDER_COLORS.get(row["rider"])
            base_bg = QColor(color).lighter(215) if color else QColor("#F5F5F5")

            def fmtv(v):
                if v is None: return "—"
                if isinstance(v, float): return f"{v:.2f}"
                return str(v)

            vals = [
                row["rider"], row["circuit"],
                str(row["n"]), str(row["n3"]),
                self._fmt(row["fast_best"]), self._fmt(row["slow_best"]),
                fmtv(row["fApexF"]), fmtv(row["sApexF"]),
                f"{row['dApexF']:+.2f}" if row.get("dApexF") is not None else "—",
                fmtv(row["fApexR"]), fmtv(row["sApexR"]),
                f"{row['dApexR']:+.2f}" if row.get("dApexR") is not None else "—",
                fmtv(row["fBrkF"]),  fmtv(row["sBrkF"]),
                f"{row['dBrkF']:+.2f}" if row.get("dBrkF") is not None else "—",
                fmtv(row["fBrkR"]),  fmtv(row["sBrkR"]),
                f"{row['dBrkR']:+.2f}" if row.get("dBrkR") is not None else "—",
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if j in delta_cols and v not in ("—", ""):
                    try:
                        dv = float(str(v).replace("+", ""))
                        # 負=FAST時により沈む=良方向 → 緑
                        item.setBackground(QColor("#C8E6C9") if dv < -0.5
                                           else QColor("#FFCDD2") if dv > 0.5
                                           else QColor("#FFF9C4"))
                    except ValueError:
                        item.setBackground(base_bg)
                else:
                    item.setBackground(base_bg)
                self._tbl_fast_slow.setItem(i, j, item)

        self._tbl_fast_slow.resizeColumnsToContents()
        self._tbl_fast_slow.horizontalHeader().setStretchLastSection(True)
        self._tbl_fast_slow.setSortingEnabled(True)

        # ════════════════════════════════════════════════
        # 2) 回路別 問題タグ クロス集計
        # ════════════════════════════════════════════════
        rider_tags = notes_data.get("rider_tags", {})
        circuit_tag: dict = defaultdict(lambda: defaultdict(dict))

        for rider, rtags in rider_tags.items():
            for tag, count, circuits_str in rtags:
                for circ in [c.strip() for c in circuits_str.split(",") if c.strip()]:
                    circuit_tag[circ][tag][rider] = count

        if not circuit_tag:
            self._tbl_circuit_prob.setRowCount(0)
            return

        # タグを全体件数で降順ソート
        all_tags_raw = set()
        for td in circuit_tag.values():
            all_tags_raw.update(td.keys())
        tag_totals = {
            t: sum(circuit_tag[c].get(t, {}).get("DA77", 0)
                   + circuit_tag[c].get(t, {}).get("JA52", 0)
                   for c in circuit_tag)
            for t in all_tags_raw
        }
        tags_ord = sorted(all_tags_raw, key=lambda t: -tag_totals.get(t, 0))
        circuits_ord = sorted(circuit_tag.keys())

        # ヘッダー: Circuit + タグ列 (DA77 | JA52)
        hdr = ["Circuit"] + tags_ord
        self._tbl_circuit_prob.setColumnCount(len(hdr))
        self._tbl_circuit_prob.setHorizontalHeaderLabels(hdr)
        self._tbl_circuit_prob.setRowCount(len(circuits_ord))
        self._tbl_circuit_prob.verticalHeader().setDefaultSectionSize(24)

        for i, circ in enumerate(circuits_ord):
            for j, col in enumerate(hdr):
                if col == "Circuit":
                    item = QTableWidgetItem(circ)
                    item.setBackground(QColor("#E3F2FD"))
                else:
                    td = circuit_tag[circ].get(col, {})
                    da = td.get("DA77", 0)
                    ja = td.get("JA52", 0)
                    total = da + ja
                    if total == 0:
                        display = "—"
                        bg = QColor("#FAFAFA")
                    else:
                        display = f"D:{da}  J:{ja}"
                        bg = (QColor("#FFCDD2") if total >= 2
                              else QColor("#FFF9C4"))
                    item = QTableWidgetItem(display)
                    item.setBackground(bg)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._tbl_circuit_prob.setItem(i, j, item)

        self._tbl_circuit_prob.resizeColumnsToContents()
        self._tbl_circuit_prob.horizontalHeader().setStretchLastSection(True)

    # ── 📊 Perf Corr テーブル ────────────────────────────────────────
    def _build_perf_corr_tables(self, pc_cache: tuple, rider_f: str | None, round_f: str | None):
        """PERFORMANCE_CORRELATION の per-run と FAST/SLOW 比較をテーブル表示。"""
        run_hdrs, run_data, cmp_hdrs, cmp_data = pc_cache

        # ── per-run テーブル ──
        display_run_cols = [
            "RUN_ID", "Rider", "Circuit", "Date", "Session", "Run",
            "Best Lap", "Avg Lap", "N Laps",
            "APEX SusF (mm)", "APEX SusR (mm)",
            "APEX WhlF (N)", "APEX WhlR (N)",
            "APEX Spd (km/h)", "APEX ax (m/s²)",
            "Brk SusF (mm)", "Brk SusR (mm)", "Brk Spd (km/h)",
            "Rank", "Gap (s)", "Tier",
        ]
        # run_hdrs のキーマッピング (header → friendly name)
        hdr_map = {}
        if run_hdrs:
            for h in run_hdrs:
                clean = h.replace("\n", " ").strip()
                hdr_map[clean] = clean

        # フィルタリング
        filtered = run_data
        if rider_f:
            filtered = [d for d in filtered if d.get("Rider") == rider_f]
        if round_f:
            filtered = [d for d in filtered
                        if round_f.upper() in str(d.get(run_hdrs[1] if run_hdrs else "RUN_ID", "")).upper()]

        # テーブル構築
        raw_cols = run_hdrs[1:] if run_hdrs else []  # skip col0 (stale)
        friendly = [c.replace("\n", " ").strip() for c in raw_cols]
        self._tbl_perf_corr.setSortingEnabled(False)
        self._tbl_perf_corr.setColumnCount(len(friendly))
        self._tbl_perf_corr.setHorizontalHeaderLabels(friendly)
        self._tbl_perf_corr.setRowCount(len(filtered))

        tier_colors = {"FAST": "#E8F5E9", "MED": "#FFF9C4", "SLOW": "#FFEBEE"}
        for i, d in enumerate(filtered):
            tier = str(d.get("Tier") or "")
            bg = tier_colors.get(tier.upper(), None)
            for j, col in enumerate(raw_cols):
                v = d.get(col)
                # 数値型の場合 2桁小数
                if col in ("Best Lap", "Avg Lap"):
                    display = str(v) if v else "—"
                elif isinstance(v, float):
                    display = f"{v:.2f}"
                else:
                    display = str(v) if v is not None else "—"
                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if bg:
                    item.setBackground(QColor(bg))
                self._tbl_perf_corr.setItem(i, j, item)

        self._tbl_perf_corr.resizeColumnsToContents()
        self._tbl_perf_corr.horizontalHeader().setStretchLastSection(True)
        self._tbl_perf_corr.setSortingEnabled(True)

        # ── FAST/SLOW 比較テーブル ──
        cmp_filtered = cmp_data
        if rider_f:
            cmp_filtered = [d for d in cmp_data
                            if d.get(cmp_hdrs[2] if len(cmp_hdrs) > 2 else "Rider") == rider_f]

        cmp_raw = cmp_hdrs[2:] if len(cmp_hdrs) > 2 else cmp_hdrs
        cmp_friendly = [c.replace("\n", " ").strip() for c in cmp_raw]
        self._tbl_perf_cmp.setSortingEnabled(False)
        self._tbl_perf_cmp.setColumnCount(len(cmp_friendly))
        self._tbl_perf_cmp.setHorizontalHeaderLabels(cmp_friendly)
        self._tbl_perf_cmp.setRowCount(len(cmp_filtered))

        for i, d in enumerate(cmp_filtered):
            rider = d.get(cmp_hdrs[2] if len(cmp_hdrs) > 2 else "", "")
            bc = self._RIDER_COLORS.get(rider)
            for j, col in enumerate(cmp_raw):
                v = d.get(col)
                if isinstance(v, float):
                    display = f"{v:.2f}"
                else:
                    display = str(v) if v is not None else "—"
                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if bc:
                    item.setBackground(QColor(bc).lighter(215))
                self._tbl_perf_cmp.setItem(i, j, item)

        self._tbl_perf_cmp.resizeColumnsToContents()
        self._tbl_perf_cmp.horizontalHeader().setStretchLastSection(True)

    # ── 📝 Session Notes ─────────────────────────────────────────────
    def _build_session_notes(self, notes_data: dict, rider_f: str | None):
        """問題タグサマリー + エンジニアノートを表示。"""
        # ── 左: 問題タグテーブル ──
        tags = notes_data.get("tags", [])
        rider_tags = notes_data.get("rider_tags", {})

        # 全タグ + ライダー別件数を統合表示
        combined: dict = {}
        for tag, cnt, phase, meaning in tags:
            combined[tag] = {"total": cnt, "phase": phase, "meaning": meaning,
                             "DA77": 0, "JA52": 0}
        for rider, rtags in rider_tags.items():
            for tag, cnt, circuits in rtags:
                if tag not in combined:
                    combined[tag] = {"total": 0, "phase": "", "meaning": "",
                                     "DA77": 0, "JA52": 0}
                combined[tag][rider] = cnt
                combined[tag]["circuits_" + rider] = circuits

        # ライダーフィルター適用
        if rider_f:
            sorted_tags = sorted(
                [(t, d) for t, d in combined.items() if d.get(rider_f, 0) > 0],
                key=lambda x: -x[1].get(rider_f, 0)
            )
        else:
            sorted_tags = sorted(combined.items(), key=lambda x: -x[1].get("total", 0))

        tag_cols = ["Tag", "Phase", "Total", "DA77", "JA52", "Meaning"]
        self._tbl_tag_summary.setSortingEnabled(False)
        self._tbl_tag_summary.setColumnCount(len(tag_cols))
        self._tbl_tag_summary.setHorizontalHeaderLabels(tag_cols)
        self._tbl_tag_summary.setRowCount(len(sorted_tags))

        for i, (tag, d) in enumerate(sorted_tags):
            total = d.get("total", 0)
            bg = "#FFCDD2" if total >= 8 else "#FFE0B2" if total >= 5 else "#FFF9C4" if total >= 3 else None
            values = [tag, d.get("phase", ""), str(total),
                      str(d.get("DA77", 0)), str(d.get("JA52", 0)), d.get("meaning", "")]
            for j, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if bg:
                    item.setBackground(QColor(bg))
                self._tbl_tag_summary.setItem(i, j, item)

        self._tbl_tag_summary.resizeColumnsToContents()
        self._tbl_tag_summary.horizontalHeader().setStretchLastSection(True)
        self._tbl_tag_summary.setSortingEnabled(True)

        # ── 右: エンジニアノートHTML ──
        notes = notes_data.get("notes", [])
        if rider_f:
            notes = [(k, v) for k, v in notes if rider_f in k.upper()]

        html_parts = ["<html><body style='font-family:Arial;font-size:11px;'>"]
        for session_key, note_text in sorted(notes, reverse=True):
            if not note_text:
                continue
            # セッションキー色分け
            if "ROUND4" in session_key: hdr_col = "#1565C0"
            elif "ROUND3" in session_key: hdr_col = "#2E7D32"
            elif "ROUND2" in session_key: hdr_col = "#6A1B9A"
            elif "ROUND1" in session_key: hdr_col = "#BF360C"
            else: hdr_col = "#424242"

            # ライダー色
            if "DA77" in session_key: rider_col = "#0078D4"
            elif "JA52" in session_key: rider_col = "#E86C00"
            else: rider_col = "#666"

            html_parts.append(
                f"<div style='margin-bottom:12px; border-left:4px solid {hdr_col}; "
                f"padding-left:8px;'>"
                f"<div style='font-weight:bold; color:{rider_col}; margin-bottom:4px;'>"
                f"📋 {session_key}</div>"
                f"<div style='color:#333; white-space:pre-wrap;'>"
                f"{note_text.replace('<', '&lt;').replace('>', '&gt;')}</div>"
                f"</div>"
            )
        html_parts.append("</body></html>")
        self._txt_notes.setHtml("".join(html_parts))


# ════════════════════════════════════════════════════════════════════
# グラフ共通ユーティリティ
# ════════════════════════════════════════════════════════════════════

def _make_help_panel(plot_widget: QWidget, title: str, help_text: str) -> QWidget:
    """PlotWidget を ? ヘルプボタン付きパネルでラップする。"""
    panel = QWidget()
    vbox = QVBoxLayout(panel)
    vbox.setContentsMargins(0, 0, 0, 0)
    vbox.setSpacing(0)

    hdr = QHBoxLayout()
    hdr.setContentsMargins(4, 2, 4, 0)
    lbl = QLabel(f"<b style='font-size:10px;color:#333;'>{title}</b>")
    hdr.addWidget(lbl)
    hdr.addStretch()

    btn = QPushButton("?")
    btn.setFixedSize(18, 18)
    btn.setToolTip(help_text)
    btn.setStyleSheet(
        "QPushButton{background:#EBF3FF;border:1px solid #4A90D9;"
        "border-radius:9px;color:#1A73E8;font-weight:bold;font-size:10px;}"
        "QPushButton:hover{background:#D2E3FC;}"
    )
    _t, _h = title, help_text
    btn.clicked.connect(lambda: QMessageBox.information(panel, _t, _h))
    hdr.addWidget(btn)

    vbox.addLayout(hdr)
    vbox.addWidget(plot_widget, stretch=1)
    return panel


# ════════════════════════════════════════════════════════════════════
# Setup Trend タブ（best_worst_pairs ベース）
# ════════════════════════════════════════════════════════════════════

class _RiderTrendWidget(QWidget):
    """🏍️ Rider Setup Trend — ライダー別セットアップ感度分析。

    X軸: セットアップパラメータ値（BEST / WORST）
    Y軸: Apex Speed (km/h)
    データ: best_worst_pairs テーブル（STANDARD ペアのみ）
    """

    PARAMS = [
        ("F_COMP",  "f_comp_best",  "f_comp_worst"),
        ("F_REB",   "f_reb_best",   "f_reb_worst"),
        ("F_PRE",   "f_pre_best",   "f_pre_worst"),
        ("F_SPR_L", "f_spr_l_best", "f_spr_l_worst"),
        ("F_SPR_R", "f_spr_r_best", "f_spr_r_worst"),
        ("R_COMP",  "r_comp_best",  "r_comp_worst"),
        ("R_REB",   "r_reb_best",   "r_reb_worst"),
        ("R_PRE",   "r_pre_best",   "r_pre_worst"),
        ("SA",      "sa_best",      "sa_worst"),
    ]
    RIDER_COLORS = {"JA52": "#4CAF50", "DA77": "#9C27B0"}

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._pairs: list[dict] = []
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Rider:"))
        self._combo_rider = QComboBox()
        self._combo_rider.addItems(["BOTH", "JA52", "DA77"])
        self._combo_rider.setFixedWidth(90)
        self._combo_rider.currentTextChanged.connect(self._draw)
        ctrl.addWidget(self._combo_rider)

        ctrl.addWidget(QLabel("Parameter:"))
        self._combo_param = QComboBox()
        self._combo_param.addItems([p[0] for p in self.PARAMS])
        self._combo_param.setFixedWidth(100)
        self._combo_param.currentTextChanged.connect(self._draw)
        ctrl.addWidget(self._combo_param)

        btn = QPushButton("🔄 Refresh")
        btn.setFixedWidth(80)
        btn.clicked.connect(self.refresh)
        ctrl.addWidget(btn)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        import pyqtgraph as pg
        self._plot = pg.PlotWidget(title="Setup Value vs Apex Speed")
        self._plot.setLabel("left",   "Apex Speed (km/h)")
        self._plot.setLabel("bottom", "Setup Value")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.addLegend()
        splitter.addWidget(self._plot)

        self._summary_table = QTableWidget(0, 6)
        self._summary_table.setHorizontalHeaderLabels([
            "Circuit", "Rider", "Param BEST", "Apex BEST",
            "Param WORST", "Δ Apex"
        ])
        self._summary_table.horizontalHeader().setStretchLastSection(True)
        self._summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._summary_table.setAlternatingRowColors(True)
        splitter.addWidget(self._summary_table)
        splitter.setSizes([420, 300])
        lay.addWidget(splitter)

        self._text_obs = QTextEdit()
        self._text_obs.setReadOnly(True)
        self._text_obs.setMaximumHeight(90)
        self._text_obs.setPlaceholderText("Setup Changes / 原因考察")
        lay.addWidget(self._text_obs)

    def refresh(self):
        self._pairs = self._db.get_best_worst_pairs()
        self._draw()

    def _draw(self):
        import pyqtgraph as pg

        rider_f = self._combo_rider.currentText()
        idx = self._combo_param.currentIndex()
        if idx < 0 or idx >= len(self.PARAMS):
            return
        param_label, col_best, col_worst = self.PARAMS[idx]

        filtered = [
            p for p in self._pairs
            if rider_f == "BOTH" or p.get("rider") == rider_f
        ]

        self._plot.clear()
        self._plot.setTitle(f"{param_label} vs Apex Speed (○=BEST  ×=WORST)")

        obs_lines = []
        table_rows = []

        for p in filtered:
            color = self.RIDER_COLORS.get(p.get("rider", ""), "#888888")
            x_best  = p.get(col_best)
            y_best  = p.get("apex_spd_best")
            x_worst = p.get(col_worst)
            y_worst = p.get("apex_spd_worst")

            try:
                if x_best is not None and y_best is not None:
                    sp = pg.ScatterPlotItem(
                        [float(x_best)], [float(y_best)],
                        symbol="o", size=11,
                        pen=pg.mkPen(color, width=1),
                        brush=pg.mkBrush(color),
                    )
                    self._plot.addItem(sp)
                    label = pg.TextItem(
                        (p.get("circuit") or "")[:3], color=color, anchor=(0, 1)
                    )
                    label.setPos(float(x_best), float(y_best))
                    self._plot.addItem(label)
            except (TypeError, ValueError):
                pass

            try:
                if x_worst is not None and y_worst is not None:
                    sp2 = pg.ScatterPlotItem(
                        [float(x_worst)], [float(y_worst)],
                        symbol="x", size=11,
                        pen=pg.mkPen(color, width=2),
                        brush=pg.mkBrush(color),
                    )
                    self._plot.addItem(sp2)
            except (TypeError, ValueError):
                pass

            table_rows.append((
                p.get("circuit"), p.get("rider"),
                x_best, y_best, x_worst,
                p.get("apex_spd_delta"),
            ))

            if p.get("setup_changes") or p.get("cause_analysis"):
                obs_lines.append(
                    f"[{p.get('circuit')}/{p.get('rider')}] "
                    f"{p.get('setup_changes','—')} → {p.get('cause_analysis','')}"
                )

        self._summary_table.setRowCount(len(table_rows))
        for ri, row_data in enumerate(table_rows):
            for ci, v in enumerate(row_data):
                item = QTableWidgetItem(str(v) if v is not None else "—")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if ci == 5:
                    try:
                        if float(v) < -15:
                            item.setForeground(QColor("#C62828"))
                        elif float(v) < -5:
                            item.setForeground(QColor("#E65100"))
                    except (TypeError, ValueError):
                        pass
                self._summary_table.setItem(ri, ci, item)

        self._text_obs.setPlainText(
            "\n".join(obs_lines) if obs_lines else "データなし"
        )


class _CircuitTrendWidget(QWidget):
    """🏁 Circuit Setup Trend — サーキット別セットアップ比較。

    JA52 / DA77 の BEST・WORST セットアップ値を横並び比較する。
    データ: best_worst_pairs テーブル（STANDARD ペアのみ）
    """

    SETUP_PARAMS = [
        ("F_COMP",  "f_comp_best",  "f_comp_worst"),
        ("F_REB",   "f_reb_best",   "f_reb_worst"),
        ("F_PRE",   "f_pre_best",   "f_pre_worst"),
        ("F_SPR_L", "f_spr_l_best", "f_spr_l_worst"),
        ("F_SPR_R", "f_spr_r_best", "f_spr_r_worst"),
        ("R_COMP",  "r_comp_best",  "r_comp_worst"),
        ("R_REB",   "r_reb_best",   "r_reb_worst"),
        ("R_PRE",   "r_pre_best",   "r_pre_worst"),
        ("SA",      "sa_best",      "sa_worst"),
    ]

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._pairs: list[dict] = []
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Circuit:"))
        self._combo_circ = QComboBox()
        self._combo_circ.setFixedWidth(150)
        self._combo_circ.currentTextChanged.connect(self._draw)
        ctrl.addWidget(self._combo_circ)
        btn = QPushButton("🔄 Refresh")
        btn.setFixedWidth(80)
        btn.clicked.connect(self.refresh)
        ctrl.addWidget(btn)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        self._compare_table = QTableWidget(len(self.SETUP_PARAMS), 5)
        self._compare_table.setHorizontalHeaderLabels([
            "Parameter", "JA52 BEST", "DA77 BEST",
            "JA52 WORST", "DA77 WORST"
        ])
        self._compare_table.verticalHeader().setVisible(False)
        self._compare_table.horizontalHeader().setStretchLastSection(True)
        self._compare_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._compare_table.setAlternatingRowColors(True)
        for ri, (label, _, _) in enumerate(self.SETUP_PARAMS):
            item = QTableWidgetItem(label)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._compare_table.setItem(ri, 0, item)
        lay.addWidget(self._compare_table)

        self._lbl_apex = QLabel("Apex Speed: —")
        self._lbl_apex.setStyleSheet(
            "font-size: 12px; font-weight: bold; padding: 6px;"
            "background: #F5F5F5; border-radius: 4px;"
        )
        lay.addWidget(self._lbl_apex)

        self._text_2d = QTextEdit()
        self._text_2d.setReadOnly(True)
        self._text_2d.setMaximumHeight(140)
        self._text_2d.setPlaceholderText("2D観察値 / 考察 / 次戦への提案")
        lay.addWidget(self._text_2d)

    def refresh(self):
        self._pairs = self._db.get_best_worst_pairs()
        circuits = sorted({p["circuit"] for p in self._pairs if p.get("circuit")})
        saved = self._combo_circ.currentText()
        self._combo_circ.blockSignals(True)
        self._combo_circ.clear()
        self._combo_circ.addItems(circuits)
        if saved in circuits:
            self._combo_circ.setCurrentText(saved)
        self._combo_circ.blockSignals(False)
        self._draw()

    def _draw(self):
        circ = self._combo_circ.currentText()
        if not circ:
            return

        by_rider = {
            p["rider"]: p
            for p in self._pairs
            if p.get("circuit") == circ
        }
        ja = by_rider.get("JA52", {})
        da = by_rider.get("DA77", {})

        best_bg  = QColor("#E8F5E9")
        worst_bg = QColor("#FFEBEE")

        for ri, (label, col_b, col_w) in enumerate(self.SETUP_PARAMS):
            for ci_offset, (v, bg) in enumerate(zip(
                [ja.get(col_b), da.get(col_b), ja.get(col_w), da.get(col_w)],
                [best_bg, best_bg, worst_bg, worst_bg]
            )):
                item = QTableWidgetItem(str(v) if v is not None else "—")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(bg)
                self._compare_table.setItem(ri, ci_offset + 1, item)

        ja_best  = ja.get("apex_spd_best",  "—")
        da_best  = da.get("apex_spd_best",  "—")
        ja_delta = ja.get("apex_spd_delta", "—")
        da_delta = da.get("apex_spd_delta", "—")
        self._lbl_apex.setText(
            f"Apex BEST —  JA52: {ja_best} km/h  |  DA77: {da_best} km/h　　"
            f"Δ(BEST→WORST) —  JA52: {ja_delta} km/h  |  DA77: {da_delta} km/h"
        )

        lines = []
        for rider, p in [("JA52", ja), ("DA77", da)]:
            if not p:
                continue
            lines.append(f"── {rider} ──")
            if p.get("obs_apex_sus_f_best"):
                lines.append(f"  Apex Sus : {p['obs_apex_sus_f_best']}")
            if p.get("obs_pit_sus_f_best"):
                lines.append(f"  Pit Sus  : {p['obs_pit_sus_f_best']}")
            if p.get("obs_brk_sus_f_best"):
                lines.append(f"  Brk Sus  : {p['obs_brk_sus_f_best']}")
            if p.get("cause_analysis"):
                lines.append(f"  考察     : {p['cause_analysis']}")
            if p.get("next_race_suggest"):
                lines.append(f"  次戦提案 : {p['next_race_suggest']}")
        self._text_2d.setPlainText("\n".join(lines) if lines else "データなし")


class SetupTrendTab(QWidget):
    """📊 Setup Trend — セットアップ傾向分析タブ。
    best_worst_pairs テーブルを使った Round 横断分析。
    サブタブ: 🏍️ Rider Trend / 🏁 Circuit Trend
    """

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)

        self._inner_tabs = QTabWidget()
        self._w_rider   = _RiderTrendWidget(db=self._db)
        self._w_circuit = _CircuitTrendWidget(db=self._db)
        self._inner_tabs.addTab(self._w_rider,   "🏍️ Rider Trend")
        self._inner_tabs.addTab(self._w_circuit, "🏁 Circuit Trend")
        lay.addWidget(self._inner_tabs)

    def refresh(self):
        try:
            self._w_rider.refresh()
            self._w_circuit.refresh()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# 姿勢分析タブ
# ════════════════════════════════════════════════════════════════════

class PostureAnalysisTab(QWidget):
    """🎯 姿勢分析タブ
    Pitch = ApexSusF - ApexSusR  (負値=ノーズDOWN=良好なターンイン)
    Heave = (ApexSusF + ApexSusR) / 2  (全体沈み込み量)
    データソース: lap_suspension_data.json (参考値 §0)
    """

    _LAP_SUS = SCRIPT_DIR / "lap_suspension_data.json"
    _COLORS   = {"DA77": "#0078D4", "JA52": "#FF8C00"}

    # ── Observation タグ定義 ─────────────────────────────────────────
    _OBS_TAGS: dict[str, list[tuple[str, str]]] = {
        "GOOD": [
            ("good_front_load_entry",     "エントリー フロント荷重 良好"),
            ("good_turn_in",              "ターンイン スムーズ"),
            ("good_rear_traction",        "リア トラクション 良好"),
            ("good_braking_stability",    "ブレーキング 安定"),
            ("good_high_speed_stability", "高速安定性 良好"),
            ("good_exit_drive",           "立ち上がり ドライブ 良好"),
            ("good_balance_overall",      "全体バランス 良好"),
            ("good_apex_control",         "アペックス コントロール 良好"),
        ],
        "BAD": [
            ("front_overload",            "フロント 過荷重"),
            ("front_underload",           "フロント 荷重不足"),
            ("rear_support_lack",         "リア サポート不足"),
            ("rear_chatter",              "リア チャター"),
            ("front_chatter",             "フロント チャター"),
            ("poor_exit_drive",           "立ち上がり ドライブ不足"),
            ("unstable_braking",          "ブレーキング 不安定"),
            ("understeer_entry",          "エントリー アンダー"),
            ("oversteer_exit",            "立ち上がり オーバー"),
            ("poor_high_speed_stability", "高速不安定"),
        ],
        "NEUTRAL": [
            ("reference_lap",             "参考ラップ"),
            ("weather_affected",          "天候影響"),
            ("tyre_degradation",          "タイヤ デグラ"),
            ("setup_change_lap",          "セットアップ変更直後"),
            ("outlap",                    "アウトラップ"),
            ("push_lap",                  "プッシュラップ"),
        ],
    }

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db  = db
        self._df  = None        # pandas DataFrame
        self._circuit_filter = ""
        self._setup_ui()
        self._load_data()

    # ── データ読み込み ──────────────────────────────────────────────

    def refresh(self):
        """DB/JSON変更時に外部から呼び出される。データを再読み込みする。"""
        self._load_data()

    def _load_data(self):
        """データ読み込み: SQLite (ts24_unified.db) を優先し、JSONにフォールバック。"""
        try:
            # ── SQLite から直接読み込み（優先） ──────────────────────
            import sqlite3 as _sqlite3
            _db_path = str(Path(self._db.db_path))
            with _sqlite3.connect(_db_path) as _con:
                _con.row_factory = _sqlite3.Row
                _rows = _con.execute("SELECT * FROM lap_suspension").fetchall()
            if _rows:
                self._df = pd.DataFrame([dict(r) for r in _rows])
                self._df.columns = [c.lower() for c in self._df.columns]
                _source = f"SQLite ({len(self._df)} laps)"
            elif self._LAP_SUS.exists():
                # ── JSON フォールバック ───────────────────────────────
                raw = json.loads(self._LAP_SUS.read_text(encoding="utf-8"))
                self._df = pd.DataFrame(raw)
                self._df.columns = [c.lower() for c in self._df.columns]
                _source = f"JSON ({len(self._df)} laps)"
            else:
                if hasattr(self, "_lbl_status"):
                    self._lbl_status.setText(
                        "⚠️  lap_suspension データがありません。"
                        " python lap_suspension_stats.py を実行してください。"
                    )
                return

            sf = "apex_susf_avg"
            sr = "apex_susr_avg"
            if sf in self._df.columns and sr in self._df.columns:
                # Pitch (mm): 正値 = ノーズDOWN（フロントより圧縮）
                # F 130mm / R 70mm = Full Stroke
                self._df["pitch"] = self._df[sf] - self._df[sr]
                # Heave (mm): 車体全体の平均沈み込み = コーナリングG の代理指標
                self._df["heave"] = (self._df[sf] + self._df[sr]) / 2.0
                # Pitch_pct: ストローク使用率の差（F% - R%）
                # 0% = F/R 均等荷重, 正 = フロント荷重優位, 負 = リア荷重優位
                self._df["pitch_pct"] = (
                    self._df[sf] / self._SUS_F_MAX
                    - self._df[sr] / self._SUS_R_MAX
                ) * 100.0
            if hasattr(self, "_lbl_status"):
                riders = self._df["rider"].unique().tolist() if "rider" in self._df.columns else []
                self._lbl_status.setText(
                    f"✅  {_source} | riders: {', '.join(riders)}"
                )
            # サーキット選択コンボ更新
            if "circuit" in self._df.columns:
                circs = sorted(self._df["circuit"].dropna().unique().tolist())
                self._combo_circ.blockSignals(True)
                self._combo_circ.clear()
                self._combo_circ.addItem("全サーキット")
                self._combo_circ.addItems(circs)
                self._combo_circ.blockSignals(False)
            self._update_all()
        except Exception as e:
            if hasattr(self, "_lbl_status"):
                self._lbl_status.setText(f"❌ 読み込みエラー: {e}")

    # サスペンション物理限界（これを超えるデータは計測誤差として除外）
    _SUS_F_MAX = 130.0   # mm
    _SUS_R_MAX = 70.0    # mm
    _LAP_TIME_MIN = 60.0   # s（1分未満はアウトラップ / 計測エラー）
    _LAP_TIME_MAX = 300.0  # s（5分超は明らかな異常値）

    def _filtered_df(self):
        if self._df is None:
            return None
        df = self._df
        # サーキットフィルター
        circ = self._combo_circ.currentText()
        if circ and circ != "全サーキット" and "circuit" in df.columns:
            df = df[df["circuit"] == circ]
        # ── 物理限界フィルター ──────────────────────────────────────
        # F Sus 最大 130mm / R Sus 最大 70mm を超えるデータは計測誤差
        if "apex_susf_avg" in df.columns:
            df = df[df["apex_susf_avg"].between(0, self._SUS_F_MAX, inclusive="both")]
        if "apex_susr_avg" in df.columns:
            df = df[df["apex_susr_avg"].between(0, self._SUS_R_MAX, inclusive="both")]
        if "brk_susf_avg" in df.columns:
            df = df[df["brk_susf_avg"].between(0, self._SUS_F_MAX, inclusive="both")]
        # ラップタイム異常値除外（アウトラップ・セーフティカーラップ等）
        if "lap_time_s" in df.columns:
            df = df[df["lap_time_s"].between(
                self._LAP_TIME_MIN, self._LAP_TIME_MAX, inclusive="both")]
        return df

    # ── UI 構築 ────────────────────────────────────────────────────

    def _setup_ui(self):
        try:
            import pyqtgraph as pg
            self._pg   = pg
            self._haspg = True
        except ImportError:
            self._haspg = False

        root = QVBoxLayout(self)
        root.setSpacing(4)

        # §0 原則注記
        warn = QLabel("⚠️  §0 参考値 — サスペンション統計データ (推定値)")
        warn.setStyleSheet("color: #D83B01; font-style: italic; font-size: 10px; padding: 2px;")
        root.addWidget(warn)

        # ツールバー行
        tb = QHBoxLayout()
        self._lbl_status = QLabel("データ読込中…")
        self._lbl_status.setStyleSheet("font-size: 10px; color: #666;")
        tb.addWidget(self._lbl_status, stretch=1)
        tb.addWidget(QLabel("Circuit:"))
        self._combo_circ = QComboBox()
        self._combo_circ.setMinimumWidth(130)
        self._combo_circ.currentTextChanged.connect(self._update_all)
        tb.addWidget(self._combo_circ)
        btn_reload = QPushButton("↺ 再読込")
        btn_reload.setFixedHeight(24)
        btn_reload.clicked.connect(self._load_data)
        tb.addWidget(btn_reload)
        root.addLayout(tb)

        if not self._haspg:
            root.addWidget(QLabel("pyqtgraph が必要です: pip install pyqtgraph"))
            return

        pg = self._pg
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        # ── カスタム軸: 秒 → M'SS.00 ─────────────────────────────────
        class _LapAxis(pg.AxisItem):
            def tickStrings(self, values, scale, spacing):
                out = []
                for v in values:
                    try:
                        s = float(v)
                        if s <= 0:
                            out.append("")
                            continue
                        m = int(s) // 60
                        out.append(f"{m}'{s - m*60:05.2f}")
                    except Exception:
                        out.append("")
                return out

        # 2×2 グリッド: QSplitter 縦 × (横スプリッタ 上/下)
        vsplit = QSplitter(Qt.Orientation.Vertical)

        # 上段スプリッタ
        top = QSplitter(Qt.Orientation.Horizontal)
        self._pw_scatter = pg.PlotWidget(
            axisItems={"bottom": _LapAxis(orientation="bottom")})
        self._pw_phase   = pg.PlotWidget()
        top.addWidget(_make_help_panel(
            self._pw_scatter,
            "Pitch vs Lap Time",
            "Pitch vs Lap Time（アペックス散布図）\n\n"
            "【センサー定義】\n"
            "  F_Sus 130mm = Full Stroke（最大圧縮）\n"
            "  R_Sus  70mm = Full Stroke（最大圧縮）\n\n"
            "【Pitch の定義】\n"
            "  Pitch (mm) = ApexSusF − ApexSusR\n"
            "  正値（大）→ フロント荷重優位 → ノーズDOWN\n"
            "  正値（小）→ F/R バランス良好\n"
            "  負値     → リア荷重優位 → テールDOWN\n\n"
            "【青破線：F/R 均等荷重ライン (60mm)】\n"
            "  SusF使用率 = SusR使用率 の基準。\n"
            "  この線より上 = フロント相対過荷重（ノーズDIVE）\n"
            "  この線より下 = リア相対過荷重（テールDOWN）\n\n"
            "【アペックスでの理想状態】\n"
            "  ブレーキング残りが少なく均等荷重に近い\n"
            "  = 青破線付近に散布点が集中\n\n"
            "DA77 (青) / JA52 (橙) を色分け表示。\n"
            "※ §0 参考値（推定データ使用）",
        ))
        top.addWidget(_make_help_panel(
            self._pw_phase,
            "Phase Space (SusF vs SusR)",
            "Phase Space（位相空間図）\n\n"
            "【センサー定義】\n"
            "  F_Sus 130mm / R_Sus 70mm = Full Stroke\n\n"
            "【軸】\n"
            "  横軸: Apex SusR (mm) [0–70mm = R Full Stroke]\n"
            "  縦軸: Apex SusF (mm) [0–130mm = F Full Stroke]\n\n"
            "【青破線：F/R 均等荷重ライン】\n"
            "  SusF/130 = SusR/70 となる線（傾き ≈ 1.857）\n"
            "  この線上 = F/R ストローク使用率が等しい\n\n"
            "【各ゾーンの意味】\n"
            "  線より上（Y方向）→ F相対過荷重（ノーズDIVE）\n"
            "  線より下（X方向）→ R相対過荷重（テールDOWN）\n"
            "  右上方向 → 全体高荷重（高コーナリングG）\n"
            "  左下方向 → 全体低荷重（低速 / 荷重不足）\n\n"
            "DA77 (●) / JA52 (▼) で形を分けて表示。\n"
            "※ §0 参考値（推定データ使用）",
        ))
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)

        # 下段スプリッタ
        bot = QSplitter(Qt.Orientation.Horizontal)
        self._pw_radar = pg.PlotWidget()
        # Pitch / Heave を上下2段で分けて見やすくする
        trend_container = QWidget()
        trend_v = QVBoxLayout(trend_container)
        trend_v.setContentsMargins(0, 0, 0, 0)
        trend_v.setSpacing(2)
        self._pw_pitch_plot = pg.PlotWidget()
        self._pw_heave_plot = pg.PlotWidget()
        self._pw_heave_plot.setXLink(self._pw_pitch_plot)   # X 軸を連動
        for _p in (self._pw_pitch_plot, self._pw_heave_plot):
            _p.showGrid(x=True, y=True, alpha=0.3)
            _p.addLegend(offset=(-10, 5))
        self._pw_pitch_plot.setLabel("left", "Pitch (mm)  [↑ノーズDOWN]")
        self._pw_heave_plot.setLabel("left", "Heave (mm)  [↑高荷重]")
        self._pw_heave_plot.setLabel("bottom", "Lap No")
        trend_v.addWidget(self._pw_pitch_plot, 1)
        trend_v.addWidget(self._pw_heave_plot, 1)

        bot.addWidget(_make_help_panel(
            self._pw_radar,
            "Rider Fingerprint",
            "Rider Fingerprint（レーダーチャート）\n\n"
            "各ライダーのアペックス平均特性を5指標で比較。\n"
            "全軸「外側 = 相対的に良好」に正規化済み。\n\n"
            "【各指標の物理的意味】\n"
            "・Pitch (SusF−SusR)\n"
            "  外側 = 均等荷重に近い（ブレーキング残り小）\n"
            "  内側 = ノーズDIVE過大 or テールDOWN\n\n"
            "・Heave = (SusF+SusR)/2\n"
            "  外側 = 沈み込み小（軽荷重 or ソフトセット）\n"
            "  内側 = 沈み込み大（高荷重 or ハードブレーキ）\n\n"
            "・BRK SusF（制動時フロント圧縮）\n"
            "  外側 = 制動中の沈み込み小 → 安定制動\n"
            "  内側 = 過大なノーズDIVE → 不安定\n\n"
            "・Apex Speed: 外側 = コーナー速度高（速い）\n\n"
            "・Lap Time: 外側 = ラップタイム小（速い）\n\n"
            "DA77 (青) / JA52 (橙) を色分け表示。\n"
            "※ §0 参考値（推定データ使用）",
        ))
        bot.addWidget(_make_help_panel(
            trend_container,
            "Pitch / Heave Lap推移",
            "Pitch / Heave Lap推移（折れ線）\n\n"
            "【センサー定義】\n"
            "  F_Sus 130mm / R_Sus 70mm = Full Stroke\n\n"
            "【縦軸 (mm) / 横軸: ラップ番号】\n\n"
            "━ 実線: Pitch = SusF − SusR\n"
            "  正値（大）→ ノーズDOWN（フロント荷重優位）\n"
            "  青破線(60mm) = F/R 均等荷重の基準\n"
            "  理想: 均等荷重ライン付近で安定推移\n\n"
            "┈ 破線: Heave = (SusF + SusR) / 2\n"
            "  車体全体の平均沈み込み量\n"
            "  ラップが進むにつれ増加 → タイヤ摩耗で\n"
            "  グリップ低下 → ライダーが荷重を増やす傾向\n\n"
            "【ラップ間変動の読み方】\n"
            "  Pitch がラップごとに大きく変動\n"
            "  → ブレーキポイントが安定していない\n"
            "  Pitch がフラットに推移\n"
            "  → 一貫したライディングスタイル\n\n"
            "DA77 (青) / JA52 (橙) を色分け表示。\n"
            "※ §0 参考値（推定データ使用）",
        ))
        bot.setStretchFactor(0, 1)
        bot.setStretchFactor(1, 1)

        vsplit.addWidget(top)
        vsplit.addWidget(bot)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 1)

        for _pw in (self._pw_scatter, self._pw_phase, self._pw_radar):
            _pw.showGrid(x=True, y=True, alpha=0.3)
            _pw.addLegend()

        # Radar は極座標描画のため軸を非表示・正方形
        self._pw_radar.setAspectLocked(True)
        self._pw_radar.hideAxis("bottom")
        self._pw_radar.hideAxis("left")

        # ── 内部サブタブ: 既存4パネル / Damping-Phase を分離 ───────────
        self._inner_tabs = QTabWidget()
        self._inner_tabs.addTab(vsplit, "📊 APEX分析（基本）")
        self._inner_tabs.addTab(self._build_damping_phase_tab(), "⚙️ Damping / Phase")
        root.addWidget(self._inner_tabs, stretch=1)

    # ════════════════════════════════════════════════════════════════
    # ⚙️ Damping / Phase サブタブ（サス速度・PH1-2指標）
    # ════════════════════════════════════════════════════════════════
    # 表示カラム（lap_suspension・全lap単位・全小文字）
    #   brk_f_dive_spd_avg/peak : Hard Brake内フロント圧縮(diving,+)速度 [mm/s]
    #   ce_r_spd_avg/peak       : Corner Exit内リアサス速度の絶対値 [mm/s]
    #   ph12_rear0_s            : PH1-2進入相で SUSP_REAR<=0mm の累積秒 [s]
    #   fullbrk_count / ce_count: 信頼度（サンプル数）併記用
    # n<5 のラップは DB 側で NULL → UI で NaN 安全処理（描画は dropna・表は "—"）
    _DP_LOWSAMPLE = 5   # この未満は「参考」（淡色）表示

    def _build_damping_phase_tab(self) -> QWidget:
        """⚙️ Damping / Phase タブ（2×2）を構築して返す。
        相対ダンピング速度指数（校正済み絶対mm/sではない）。
        リアサス速度は絶対値（動きの忙しさ）である点に注意。
        """
        pg = self._pg
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(3)

        # 注記行（速度の性質・絶対値の説明）
        note = QLabel(
            "⚠️ 速度値は「相対ダンピング速度指数」（校正済み絶対 mm/s ではない）。"
            " Corner Exit リア速度は絶対値（動きの忙しさ）。"
            " n<5 のラップは DB で NULL → 散布/推移は除外・表は「—」表示。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#555; font-style:italic; font-size:10px; padding:2px;")
        outer.addWidget(note)

        # ── カスタム軸: 秒 → M'SS.00（散布図 X 用に再定義）─────────────
        class _LapAxisDP(pg.AxisItem):
            def tickStrings(self, values, scale, spacing):
                out = []
                for v in values:
                    try:
                        s = float(v)
                        if s <= 0:
                            out.append("")
                            continue
                        m = int(s) // 60
                        out.append(f"{m}'{s - m*60:05.2f}")
                    except Exception:
                        out.append("")
                return out

        vsplit = QSplitter(Qt.Orientation.Vertical)

        # 上段
        top = QSplitter(Qt.Orientation.Horizontal)
        self._pw_dp_dive = pg.PlotWidget()
        self._pw_dp_ce = pg.PlotWidget(
            axisItems={"bottom": _LapAxisDP(orientation="bottom")})
        for _p in (self._pw_dp_dive, self._pw_dp_ce):
            _p.showGrid(x=True, y=True, alpha=0.3)
            _p.addLegend()
        self._pw_dp_dive.setLabel("left", "F Dive Speed (mm/s 指数)")
        self._pw_dp_dive.setLabel("bottom", "Lap No")
        self._pw_dp_ce.setLabel("left", "CE Rear |v| (mm/s 指数・絶対値)")
        self._pw_dp_ce.setLabel("bottom", "Lap Time (M'SS.00)")
        top.addWidget(_make_help_panel(
            self._pw_dp_dive,
            "Hard Brake Front Diving Speed",
            "Hard Brake Front Diving Speed — Lap推移\n\n"
            "FULL_BRAKING(Hard Brake)区間でフロントが圧縮(diving,+)\n"
            "する方向の速度 [mm/s 相対指数]。\n\n"
            "  実線 ● = avg（brk_f_dive_spd_avg）\n"
            "  点線 × = peak（brk_f_dive_spd_peak）\n\n"
            "DA77(青) / JA52(橙) を色分け。\n"
            "n<5 のラップ（fullbrk_count<5）は DB で NULL → 除外。\n"
            "※ 校正済み絶対 mm/s ではなく相対ダンピング速度指数。",
        ))
        top.addWidget(_make_help_panel(
            self._pw_dp_ce,
            "Corner Exit Rear Speed |v|",
            "Corner Exit Rear Speed (|v|) — 散布図\n\n"
            "  X = ラップタイム / Y = ce_r_spd_avg [mm/s 絶対値]\n"
            "  点の大きさ = ce_count（サンプル数=信頼度）\n"
            "    大きい点 = サンプル多 = 信頼度高\n"
            "    小さい点 = 参考値\n\n"
            "リアサス速度の絶対値 = コーナー立ち上がりでの\n"
            "リアの「動きの忙しさ」。\n\n"
            "DA77(青) / JA52(橙) を色分け。\n"
            "n<5（ce_count<5）は DB で NULL → 除外。\n"
            "※ 相対ダンピング速度指数。",
        ))
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)

        # 下段
        bot = QSplitter(Qt.Orientation.Horizontal)
        self._pw_dp_ph12 = pg.PlotWidget()
        self._pw_dp_ph12.showGrid(x=True, y=True, alpha=0.3)
        self._pw_dp_ph12.addLegend()
        self._pw_dp_ph12.setLabel("left", "PH1-2 Rear@0mm 累積 (s)")
        self._pw_dp_ph12.setLabel("bottom", "Lap No")
        bot.addWidget(_make_help_panel(
            self._pw_dp_ph12,
            "PH1-2 Rear@0mm 累積秒",
            "PH1-2 Rear@0mm 累積秒 — Lap推移\n\n"
            "PH1-2（BRAKE_FRONT>=0.3bar の進入相）で\n"
            "SUSP_REAR<=0mm（リア完全伸び切り）だった累積秒 [s]。\n"
            "（ph12_rear0_s）\n\n"
            "リアが浮く＝荷重が乗っていない時間。\n"
            "タイヤ摩耗が進むとこの値が増える挙動を見る。\n\n"
            "DA77(青) / JA52(橙) を色分け。\n"
            "NaN（データなし）のラップは除外。",
        ))

        # 右下: 数値テーブル
        self._tbl_dp = QTableWidget()
        self._tbl_dp.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl_dp.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_dp.setColumnCount(10)
        self._tbl_dp.setHorizontalHeaderLabels([
            "Rider", "Run", "Lap",
            "F-Dive avg", "F-Dive peak",
            "CE-R avg", "CE-R peak",
            "PH1-2 R@0 (s)",
            "n(brk)", "n(ce)",
        ])
        try:
            from PyQt6.QtWidgets import QHeaderView
            self._tbl_dp.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch)
        except Exception:
            pass
        tbl_panel = _make_help_panel(
            self._tbl_dp,
            "数値テーブル（信頼度併記）",
            "数値テーブル\n\n"
            "Rider/Run/Lap ごとの各指標と信頼度サンプル数。\n\n"
            "  n(brk) = fullbrk_count（Hard Brake サンプル数）\n"
            "  n(ce)  = ce_count（Corner Exit サンプル数）\n\n"
            "NaN（n<5 で DB NULL）→ 「—」表示。\n"
            "サンプル数が少ない行（n<5）は淡色＝「参考」値。",
        )
        bot.addWidget(tbl_panel)
        bot.setStretchFactor(0, 1)
        bot.setStretchFactor(1, 1)

        vsplit.addWidget(top)
        vsplit.addWidget(bot)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 1)
        outer.addWidget(vsplit, stretch=1)
        return container

    @staticmethod
    def _dp_num(v):
        """NaN/None 安全な float 変換。無効値は None を返す。"""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f:   # NaN
            return None
        return f

    def _draw_damping_phase(self, df):
        """⚙️ Damping / Phase タブの3プロット＋テーブルを描画。
        NaN は描画から除外（dropna）し、テーブルでは "—"・少サンプルは淡色。
        新カラムが DB に未生成でも落ちないよう列存在を都度確認する。
        """
        if not getattr(self, "_haspg", False):
            return
        if not hasattr(self, "_pw_dp_dive"):
            return   # タブ未構築（pyqtgraph 無し等）
        pg = self._pg

        col_dive_avg = "brk_f_dive_spd_avg"
        col_dive_pk = "brk_f_dive_spd_peak"
        col_ce_avg = "ce_r_spd_avg"
        col_ce_pk = "ce_r_spd_peak"
        col_ph12 = "ph12_rear0_s"

        # ── 1) F Dive Speed — Lap推移（avg実線+peak点線）────────────────
        pp = self._pw_dp_dive
        pp.clear()
        pp.addLegend()
        if "lap_no" in df.columns and "rider" in df.columns:
            for rider, col in self._COLORS.items():
                rs = df[df["rider"] == rider].sort_values("lap_no")
                if rs.empty:
                    continue
                # avg 実線
                if col_dive_avg in rs.columns:
                    sub = rs.dropna(subset=["lap_no", col_dive_avg])
                    if not sub.empty:
                        pp.plot(sub["lap_no"].tolist(),
                                sub[col_dive_avg].tolist(),
                                pen=pg.mkPen(col, width=2.2),
                                symbol="o", symbolSize=6,
                                symbolBrush=pg.mkBrush(col),
                                symbolPen=pg.mkPen("w", width=0.5),
                                name=f"{rider} avg")
                # peak 点線
                if col_dive_pk in rs.columns:
                    subp = rs.dropna(subset=["lap_no", col_dive_pk])
                    if not subp.empty:
                        pp.plot(subp["lap_no"].tolist(),
                                subp[col_dive_pk].tolist(),
                                pen=pg.mkPen(col, width=1.4,
                                             style=Qt.PenStyle.DashLine),
                                symbol="x", symbolSize=6,
                                symbolBrush=pg.mkBrush(col),
                                symbolPen=pg.mkPen(col, width=1.0),
                                name=f"{rider} peak")

        # ── 2) Corner Exit Rear Speed(|v|) — 散布図 ────────────────────
        ps = self._pw_dp_ce
        ps.clear()
        ps.addLegend()
        if (col_ce_avg in df.columns and "lap_time_s" in df.columns
                and "rider" in df.columns):
            ce_cnt_present = "ce_count" in df.columns
            for rider, col in self._COLORS.items():
                rs = df[df["rider"] == rider].dropna(
                    subset=["lap_time_s", col_ce_avg])
                if rs.empty:
                    continue
                # 凡例ダミー
                ps.plot([], [], pen=None, symbol="o",
                        symbolBrush=pg.mkBrush(col), name=rider)
                spots = []
                for _, r in rs.iterrows():
                    x = self._dp_num(r.get("lap_time_s"))
                    y = self._dp_num(r.get(col_ce_avg))
                    if x is None or y is None:
                        continue
                    nce = self._dp_num(r.get("ce_count")) if ce_cnt_present else None
                    # 点サイズで ce_count（信頼度）を反映: n<5=小, 多いほど大
                    if nce is None:
                        sz = 6
                    elif nce < self._DP_LOWSAMPLE:
                        sz = 5
                    else:
                        sz = float(min(16, 7 + nce * 0.25))
                    spots.append({"pos": (x, y), "size": sz,
                                  "brush": pg.mkBrush(col + "AA"),
                                  "pen": pg.mkPen(col, width=1.0)})
                if spots:
                    sc = pg.ScatterPlotItem(spots=spots, hoverable=True)
                    ps.addItem(sc)
            ps.enableAutoRange(axis="y")

        # ── 3) PH1-2 Rear@0mm 累積秒 — Lap推移 ─────────────────────────
        pq = self._pw_dp_ph12
        pq.clear()
        pq.addLegend()
        if col_ph12 in df.columns and "lap_no" in df.columns and "rider" in df.columns:
            for rider, col in self._COLORS.items():
                rs = df[df["rider"] == rider].sort_values("lap_no")
                rs = rs.dropna(subset=["lap_no", col_ph12])
                if rs.empty:
                    continue
                pq.plot(rs["lap_no"].tolist(), rs[col_ph12].tolist(),
                        pen=pg.mkPen(col, width=2.2),
                        symbol="t", symbolSize=7,
                        symbolBrush=pg.mkBrush(col),
                        symbolPen=pg.mkPen("w", width=0.5),
                        name=rider)
            pq.enableAutoRange(axis="y")

        # ── 4) 数値テーブル（NaN→"—" / 少サンプル淡色）────────────────
        self._fill_dp_table(df)

    def _fill_dp_table(self, df):
        """Damping/Phase 数値テーブルを埋める。NaN→'—'・少サンプル行は淡色。"""
        tbl = self._tbl_dp
        tbl.setRowCount(0)
        if df is None or df.empty:
            return

        sort_cols = [c for c in ("rider", "run_no", "lap_no") if c in df.columns]
        view = df.sort_values(sort_cols) if sort_cols else df

        def _cell(v, dec=1):
            f = self._dp_num(v)
            return "—" if f is None else f"{f:.{dec}f}"

        def _cnt(v):
            f = self._dp_num(v)
            return "—" if f is None else f"{int(f)}"

        pale = QColor("#999999")
        rows = view.to_dict("records")
        tbl.setRowCount(len(rows))
        for ri, r in enumerate(rows):
            nbrk = self._dp_num(r.get("fullbrk_count"))
            nce = self._dp_num(r.get("ce_count"))
            low = ((nbrk is not None and nbrk < self._DP_LOWSAMPLE)
                   or (nce is not None and nce < self._DP_LOWSAMPLE))
            vals = [
                str(r.get("rider", "—")),
                _cnt(r.get("run_no")),
                _cnt(r.get("lap_no")),
                _cell(r.get("brk_f_dive_spd_avg")),
                _cell(r.get("brk_f_dive_spd_peak")),
                _cell(r.get("ce_r_spd_avg")),
                _cell(r.get("ce_r_spd_peak")),
                _cell(r.get("ph12_rear0_s"), 3),
                _cnt(r.get("fullbrk_count")),
                _cnt(r.get("ce_count")),
            ]
            for ci, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if low:
                    item.setForeground(pale)
                    if ci == 0:
                        item.setToolTip("参考: サンプル数が少ない（n<5）")
                tbl.setItem(ri, ci, item)

    # ── 描画 ───────────────────────────────────────────────────────

    def _update_all(self):
        if not self._haspg or self._df is None:
            return
        df = self._filtered_df()
        if df is None or df.empty:
            return
        self._draw_pitch_scatter(df)
        self._draw_phase_space(df)
        self._draw_radar(df)
        self._draw_trend(df)
        self._draw_damping_phase(df)

    # ── ラップ詳細ポップアップ ────────────────────────────────────
    def _on_pt_click(self, points):
        """ScatterPlotItem クリック → ラップ詳細 + セットアップ + Observation + コメント。"""
        if not points:
            return
        d = points[0].data()
        if not isinstance(d, dict):
            return

        run_id = d.get("run_id", "")

        # DB からセットアップ・コメントデータ取得
        run_meta: dict = {}
        if run_id:
            try:
                run_meta = self._db.get_run(run_id) or {}
            except Exception:
                pass

        # ── ラップタイムフォーマット ──────────────────────────────
        lt = 0.0
        try:
            lt = float(d.get("lap_time_s") or 0)
        except (TypeError, ValueError):
            pass
        m = int(lt) // 60
        lap_fmt = f"{m}'{lt - m*60:05.2f}" if lt > 0 else "—"

        def _fmt(v, unit="mm", dec=1):
            try:
                return f"{float(v):.{dec}f} {unit}"
            except (TypeError, ValueError):
                return "—"

        # ── QDialog 構築 ─────────────────────────────────────────
        dlg = QDialog(self)
        dlg.setWindowTitle(f"ラップ詳細  |  {run_id or '—'}")
        dlg.setMinimumWidth(520)
        dlg.setMinimumHeight(400)
        dlg.setStyleSheet("""
            QDialog   { background: #1E1E1E; color: #E0E0E0; }
            QWidget   { background: #1E1E1E; color: #E0E0E0; }
            QScrollArea { border: none; background: #1E1E1E; }
            QLabel    { color: #E0E0E0; background: transparent; }
            QGroupBox { color: #AAAAAA; border: 1px solid #444; border-radius: 4px;
                        margin-top: 8px; padding-top: 6px; padding-bottom: 6px;
                        background: #252525; }
            QGroupBox::title { color: #888; subcontrol-origin: margin; left: 8px; }
            QTextEdit { background: #2A2A2A; color: #E0E0E0; border: 1px solid #555;
                        border-radius: 3px; padding: 4px; font-size: 11px; }
            QComboBox { background: #2A2A2A; color: #E0E0E0; border: 1px solid #555;
                        border-radius: 3px; padding: 2px 6px; font-size: 11px; }
            QComboBox QAbstractItemView { background: #2A2A2A; color: #E0E0E0; }
            QPushButton { background: #333; color: #E0E0E0; border: 1px solid #555;
                          border-radius: 3px; padding: 4px 10px; font-size: 11px; }
            QPushButton:hover   { background: #444; }
            QPushButton:checked { border-width: 2px; font-weight: bold; }
            QPushButton#good    { background:#0f3a1f; border-color:#1a7a33; }
            QPushButton#good:checked  { background:#1a6b2a; border-color:#2ecc55; color:#2ecc55; }
            QPushButton#bad     { background:#3a0f0f; border-color:#7a1a1a; }
            QPushButton#bad:checked   { background:#6b1a1a; border-color:#e74c3c; color:#e74c3c; }
            QPushButton#neutral { background:#2a2a0f; border-color:#6a6a1a; }
            QPushButton#neutral:checked { background:#4a4a1a; border-color:#f0c040; color:#f0c040; }
            QPushButton#conf_h:checked  { background:#1a3a6a; border-color:#3a8aff; color:#3a8aff; }
            QPushButton#conf_m:checked  { background:#2a4a1a; border-color:#4aaa2a; color:#4aaa2a; }
            QPushButton#conf_l:checked  { background:#3a2a1a; border-color:#aa7a2a; color:#aa7a2a; }
            QPushButton#btn_obs_save { background:#1a4a6a; border-color:#2a8aaa; }
            QPushButton#btn_obs_save:hover { background:#1e6090; }
            QPushButton#btn_jump { background:#1a3f6a; border-color:#2266AA; }
            QPushButton#btn_jump:hover { background:#1e5090; }
            QPushButton#btn_run_save { background:#1a4a1a; border-color:#2a8a2a; }
            QPushButton#btn_run_save:hover { background:#1e641e; }
        """)

        outer_lay = QVBoxLayout(dlg)
        outer_lay.setContentsMargins(8, 8, 8, 8)
        outer_lay.setSpacing(6)

        # ── スクロールエリア（コンテンツ部分） ────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        main_lay = QVBoxLayout(content)
        main_lay.setSpacing(6)
        main_lay.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(content)
        outer_lay.addWidget(scroll, 1)

        def _add_kv(grid, row, label, value):
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #888; font-size: 10px;")
            val = QLabel(str(value))
            val.setStyleSheet("color: #E0E0E0; font-size: 11px; font-weight: bold;")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(lbl, row, 0)
            grid.addWidget(val, row, 1)

        # ── 1. ラップ情報 ─────────────────────────────────────────
        grp_lap = QGroupBox("🏁 ラップ情報")
        gl = QGridLayout(grp_lap)
        gl.setSpacing(3)
        gl.setColumnMinimumWidth(0, 110)
        _add_kv(gl, 0, "Rider",
                d.get("rider", "—"))
        _add_kv(gl, 1, "Circuit / Session",
                f"{d.get('circuit','—')}  /  {d.get('session','—')}  ({d.get('round','—')})")
        _add_kv(gl, 2, "Date",
                d.get("date", "—"))
        _add_kv(gl, 3, "Lap No → Time",
                f"Lap {d.get('lap_no','—')}  →  {lap_fmt}")
        _add_kv(gl, 4, "Pitch / Heave",
                f"{_fmt(d.get('pitch'))}  /  {_fmt(d.get('heave'))}")
        _add_kv(gl, 5, "Apex SusF / SusR",
                f"{_fmt(d.get('apex_susf_avg'))}  /  {_fmt(d.get('apex_susr_avg'))}")
        _add_kv(gl, 6, "Run ID",
                run_id or "—")
        main_lay.addWidget(grp_lap)

        # ── 2. セットアップサマリー ───────────────────────────────
        if run_meta:
            grp_setup = QGroupBox("🔧 セットアップ")
            gs = QGridLayout(grp_setup)
            gs.setSpacing(3)
            gs.setColumnMinimumWidth(0, 110)
            setup_rows = [
                ("Fork Spr L/R",
                 f"{_fmt(run_meta.get('f_spr_l'))} / {_fmt(run_meta.get('f_spr_r'))}"),
                ("Fork Comp / Reb",
                 f"{_fmt(run_meta.get('f_comp'),'clk',0)} / {_fmt(run_meta.get('f_reb'),'clk',0)}"),
                ("Fork Preload",    _fmt(run_meta.get("f_preload"))),
                ("Fork Oil Lvl",    _fmt(run_meta.get("f_oil_lvl"))),
                ("Fork Offset",     _fmt(run_meta.get("f_offset"))),
                ("Fork Hgt T/B",
                 f"{_fmt(run_meta.get('f_hgt_top'))} / {_fmt(run_meta.get('f_hgt_bot'))}"),
                ("Shock Spr",       _fmt(run_meta.get("r_spr"), "N/mm")),
                ("Shock Comp / Reb",
                 f"{_fmt(run_meta.get('r_comp'),'clk',0)} / {_fmt(run_meta.get('r_reb'),'clk',0)}"),
                ("Shock Len",       _fmt(run_meta.get("shock_len"))),
                ("Ride Hgt",        _fmt(run_meta.get("ride_hgt"))),
                ("Tyre F / R",
                 f"{run_meta.get('tyre_front') or '—'} / {run_meta.get('tyre_rear') or '—'}"),
                ("Press Out F / R",
                 f"{_fmt(run_meta.get('f_press_out'),'kPa',0)} / {_fmt(run_meta.get('r_press_out'),'kPa',0)}"),
            ]
            for i, (row_lbl, row_val) in enumerate(setup_rows):
                _add_kv(gs, i, row_lbl, row_val)
            main_lay.addWidget(grp_setup)

        # ── 3. Lap Observation ────────────────────────────────────
        grp_obs = QGroupBox("🎯 Lap Observation")
        go = QVBoxLayout(grp_obs)
        go.setSpacing(5)
        go.setContentsMargins(8, 6, 8, 8)

        # タイプ選択ボタン
        type_row = QHBoxLayout()
        btn_good    = QPushButton("✅  GOOD")
        btn_bad     = QPushButton("❌  BAD")
        btn_neutral = QPushButton("〇  NEUTRAL")
        for b, oid in ((btn_good,"good"), (btn_bad,"bad"), (btn_neutral,"neutral")):
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.setObjectName(oid)
        type_row.addWidget(btn_good)
        type_row.addWidget(btn_bad)
        type_row.addWidget(btn_neutral)
        go.addLayout(type_row)

        # タグ選択
        tag_row = QHBoxLayout()
        lbl_tag = QLabel("Tag:")
        lbl_tag.setFixedWidth(30)
        cmb_tag = QComboBox()
        cmb_tag.setEditable(True)   # フリー入力も可
        cmb_tag.setMinimumWidth(200)
        tag_row.addWidget(lbl_tag)
        tag_row.addWidget(cmb_tag, 1)
        go.addLayout(tag_row)

        # 観察コメント
        txt_obs = QTextEdit()
        txt_obs.setPlaceholderText(
            "観察内容を詳しく記録…\n例: Front load strong but rider still turns in well. "
            "Good reference for high-speed entry.")
        txt_obs.setFixedHeight(70)
        go.addWidget(txt_obs)

        # 確信度
        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("確信度:"))
        btn_high = QPushButton("HIGH")
        btn_med  = QPushButton("MED")
        btn_low  = QPushButton("LOW")
        for b, oid in ((btn_high,"conf_h"), (btn_med,"conf_m"), (btn_low,"conf_l")):
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setFixedWidth(58)
            b.setObjectName(oid)
        btn_med.setChecked(True)   # デフォルト MED
        conf_row.addWidget(btn_high)
        conf_row.addWidget(btn_med)
        conf_row.addWidget(btn_low)
        conf_row.addStretch()
        go.addLayout(conf_row)
        main_lay.addWidget(grp_obs)

        # ── 4. Run コメント ───────────────────────────────────────
        grp_comment = QGroupBox("📝 Run コメント（このRunへのメモ）")
        gc = QVBoxLayout(grp_comment)
        gc.setContentsMargins(6, 4, 6, 6)
        txt_comment = QTextEdit()
        txt_comment.setPlaceholderText("Run全体へのメモ・セットアップ所感…")
        txt_comment.setFixedHeight(60)
        existing = run_meta.get("comment") or ""
        txt_comment.setPlainText(existing)
        gc.addWidget(txt_comment)
        main_lay.addWidget(grp_comment)

        main_lay.addStretch()

        # ── ボタン行 ──────────────────────────────────────────────
        btn_bar = QHBoxLayout()
        btn_jump     = QPushButton("🗺️ Run Browser")
        btn_obs_save = QPushButton("🎯 Observation記録")
        btn_run_save = QPushButton("💾 Run Comment保存")
        btn_close    = QPushButton("閉じる")
        for b, oid in ((btn_jump,"btn_jump"),
                       (btn_obs_save,"btn_obs_save"),
                       (btn_run_save,"btn_run_save")):
            b.setObjectName(oid)
        for b in (btn_jump, btn_obs_save, btn_run_save, btn_close):
            b.setFixedHeight(30)
        btn_bar.addWidget(btn_jump)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_obs_save)
        btn_bar.addWidget(btn_run_save)
        btn_bar.addWidget(btn_close)
        outer_lay.addLayout(btn_bar)

        # ── タグリストをタイプに応じて更新 ───────────────────────
        def _refresh_tags(obs_type: str):
            cmb_tag.clear()
            for tag_key, tag_label in self._OBS_TAGS.get(obs_type, []):
                cmb_tag.addItem(tag_label, userData=tag_key)

        def _on_type(selected, obs_type: str):
            for b in (btn_good, btn_bad, btn_neutral):
                b.setChecked(b is selected)
            _refresh_tags(obs_type)

        btn_good.clicked.connect(   lambda: _on_type(btn_good,    "GOOD"))
        btn_bad.clicked.connect(    lambda: _on_type(btn_bad,     "BAD"))
        btn_neutral.clicked.connect(lambda: _on_type(btn_neutral, "NEUTRAL"))

        def _on_conf(selected):
            for b in (btn_high, btn_med, btn_low):
                b.setChecked(b is selected)

        btn_high.clicked.connect(lambda: _on_conf(btn_high))
        btn_med.clicked.connect( lambda: _on_conf(btn_med))
        btn_low.clicked.connect( lambda: _on_conf(btn_low))

        # ── Observation 保存 ──────────────────────────────────────
        def _on_obs_save():
            obs_type = None
            for b, t in ((btn_good,"GOOD"), (btn_bad,"BAD"), (btn_neutral,"NEUTRAL")):
                if b.isChecked():
                    obs_type = t
                    break
            if not obs_type:
                QMessageBox.warning(dlg, "Observation エラー",
                                    "GOOD / BAD / NEUTRAL のいずれかを選択してください。")
                return
            tag_key = cmb_tag.currentData() or cmb_tag.currentText().strip()
            conf = next((c for b, c in ((btn_high,"HIGH"),(btn_med,"MED"),(btn_low,"LOW"))
                         if b.isChecked()), "MED")
            obs_data = {
                "run_id":           run_id,
                "lap_id":           d.get("lap_id"),
                "lap_no":           d.get("lap_no"),
                "rider":            d.get("rider"),
                "circuit":          d.get("circuit"),
                "session":          d.get("session"),
                "round":            d.get("round"),
                "lap_time_s":       d.get("lap_time_s"),
                "pitch":            d.get("pitch"),
                "heave":            d.get("heave"),
                "apex_susf_avg":    d.get("apex_susf_avg"),
                "apex_susr_avg":    d.get("apex_susr_avg"),
                "observation_type": obs_type,
                "observation_tag":  tag_key,
                "comment":          txt_obs.toPlainText().strip(),
                "confidence":       conf,
            }
            try:
                self._db.add_lap_observation(obs_data)
                btn_obs_save.setText("✅ 記録済み")
                btn_obs_save.setEnabled(False)
            except Exception as e:
                QMessageBox.warning(dlg, "保存エラー", str(e))

        # ── Run Comment 保存 ──────────────────────────────────────
        def _on_run_save():
            if not run_id:
                return
            try:
                self._db.save_comment(run_id, txt_comment.toPlainText().strip())
                btn_run_save.setText("✅ 保存済み")
                btn_run_save.setEnabled(False)
            except Exception as e:
                QMessageBox.warning(dlg, "保存エラー", str(e))

        def _on_jump():
            dlg.accept()
            win = self.window()
            if hasattr(win, "_tab_browser") and hasattr(win, "_tabs"):
                win._tabs.setCurrentWidget(win._tab_browser)
                win._tab_browser.jump_to_run(run_id)

        txt_comment.textChanged.connect(
            lambda: (btn_run_save.setText("💾 Run Comment保存"),
                     btn_run_save.setEnabled(True)))
        txt_obs.textChanged.connect(
            lambda: (btn_obs_save.setText("🎯 Observation記録"),
                     btn_obs_save.setEnabled(True)))

        btn_obs_save.clicked.connect(_on_obs_save)
        btn_run_save.clicked.connect(_on_run_save)
        btn_jump.clicked.connect(_on_jump)
        btn_close.clicked.connect(dlg.accept)

        # ダイアログ高さをスクリーンの 80% に制限
        screen_h = dlg.screen().availableGeometry().height() if dlg.screen() else 900
        dlg.setMaximumHeight(int(screen_h * 0.82))

        dlg.exec()

    # ── 散布図共通ヘルパー: ScatterPlotItem スポットリスト作成 ───
    @staticmethod
    def _make_spots(pg, grp, col, pen_col, sz, alpha, info_cols):
        """クラスタ別 spots リストを生成（クリック用データ付き）。"""
        avail = [c for c in info_cols if c in grp.columns]
        records = grp[avail].where(grp[avail].notna(), other=None).to_dict("records")
        xs = grp.iloc[:, 0].values   # x は grp の第1列
        ys = grp.iloc[:, 1].values   # y は grp の第2列
        brush = pg.mkBrush(col + alpha)
        pen   = pg.mkPen(pen_col, width=1.5)
        return [{"pos": (float(x), float(y)),
                 "brush": brush, "pen": pen, "size": sz, "data": d}
                for x, y, d in zip(xs, ys, records)
                if x == x and y == y]   # NaN 除外

    def _draw_pitch_scatter(self, df):
        """Panel 1: Pitch vs Lap Time 散布図（クラスタ色分け付き）。
        Pitch = SusF - SusR (mm)  正値 = ノーズDOWN（フロント荷重優位）
        ─ クラスタ凡例 ─────────────────────────
        🟢 緑枠 (大) = Fast lap  (全体 Q25 以下)
        ⬜ 灰枠 (中) = Mid  lap  (Q25〜Q75)
        🔴 赤枠 (小) = Slow lap  (Q75 以上)
        ─────────────────────────────────────────
        """
        pg  = self._pg
        pw  = self._pw_scatter
        pw.clear()
        pw.setLabel("left",   "Pitch (mm) = SusF − SusR  [↑ノーズDOWN]")
        pw.setLabel("bottom", "Lap Time (M'SS.00)")
        if "pitch" not in df.columns or "lap_time_s" not in df.columns:
            return

        # ── ラップタイム四分位（全ライダー統合）──────────────────
        all_t = df["lap_time_s"].dropna()
        q25 = float(all_t.quantile(0.25)) if len(all_t) >= 4 else float("inf")
        q75 = float(all_t.quantile(0.75)) if len(all_t) >= 4 else float("-inf")

        pw.addLegend()
        _INFO = ["run_id","lap_id","rider","round","circuit","session",
                 "lap_no","date","lap_time_s","pitch","heave",
                 "apex_susf_avg","apex_susr_avg"]

        for rider, col in self._COLORS.items():
            if "rider" not in df.columns:
                break
            sub = df[df["rider"] == rider].dropna(subset=["pitch","lap_time_s"])
            if sub.empty:
                continue
            # ダミーエントリ（凡例にライダー名を表示）
            pw.plot([], [], pen=None, symbol="o",
                    symbolBrush=pg.mkBrush(col), name=rider)

            # クラスタ定義: (mask, 枠色, サイズ, alpha hex)
            # Slow を先に描き Fast を最前面に
            clusters = [
                (sub["lap_time_s"] >= q75, "#CC2200", 5, "55"),  # Slow: 赤枠・小
                ((sub["lap_time_s"] > q25) & (sub["lap_time_s"] < q75),
                 "#777777", 6, "88"),                              # Mid: 灰枠・中
                (sub["lap_time_s"] <= q25, "#00BB44", 8, "FF"),   # Fast: 緑枠・大
            ]
            for mask, pen_col, sz, alpha in clusters:
                grp = sub[mask][["lap_time_s","pitch"] +
                                [c for c in _INFO if c in sub.columns and
                                 c not in ("lap_time_s","pitch")]]
                if grp.empty:
                    continue
                spots = self._make_spots(pg, grp, col, pen_col, sz, alpha, _INFO)
                if not spots:
                    continue
                sc = pg.ScatterPlotItem(spots=spots, hoverable=True)
                # sigClicked: 0.12.x → (scatter, pts)  /  0.13.x → (scatter, pts, ev)
                sc.sigClicked.connect(
                    lambda *a, s=self: s._on_pt_click(a[1] if len(a) >= 2 else []))
                pw.addItem(sc)

        # F/R 均等荷重ライン
        balance_pitch = self._SUS_F_MAX - self._SUS_R_MAX   # = 60mm
        pw.addItem(pg.InfiniteLine(
            pos=balance_pitch, angle=0,
            pen=pg.mkPen("#0078D4", width=1.2, style=Qt.PenStyle.DashLine),
            label="F/R 均等荷重 ({value:.0f}mm)",
            labelOpts={"color": "#0078D4", "position": 0.9},
        ))
        pw.addItem(pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen("#888", width=0.8, style=Qt.PenStyle.DotLine),
        ))
        pw.setYRange(-10, self._SUS_F_MAX, padding=0.04)

    def _draw_phase_space(self, df):
        """Panel 2: SusR (X) vs SusF (Y) Phase Space。物理限界軸固定。"""
        pg = self._pg
        pw = self._pw_phase
        pw.clear()
        # X = SusR (0-70mm), Y = SusF (0-130mm)
        pw.setLabel("bottom", "Apex SusR (mm)")
        pw.setLabel("left",   "Apex SusF (mm)")
        sf_col = "apex_susf_avg"
        sr_col = "apex_susr_avg"
        if sf_col not in df.columns or sr_col not in df.columns:
            return
        sub = df.dropna(subset=[sf_col, sr_col])
        if sub.empty:
            return
        # ── Phase Space クラスタ（ラップタイム四分位）────────────────
        all_t = sub["lap_time_s"].dropna() if "lap_time_s" in sub.columns else pd.Series([], dtype=float)
        q25 = float(all_t.quantile(0.25)) if len(all_t) >= 4 else float("inf")
        q75 = float(all_t.quantile(0.75)) if len(all_t) >= 4 else float("-inf")
        has_time = "lap_time_s" in sub.columns

        _INFO = ["run_id","lap_id","rider","round","circuit","session",
                 "lap_no","date","lap_time_s","pitch","heave",
                 "apex_susf_avg","apex_susr_avg"]

        pw.addLegend()
        for rider, col in self._COLORS.items():
            if "rider" not in df.columns:
                break
            rs = sub[sub["rider"] == rider]
            if rs.empty:
                continue
            # ダミーレジェンドエントリ
            pw.plot([], [], pen=None, symbol="o",
                    symbolBrush=pg.mkBrush(col), name=rider)

            clusters = [
                (rs["lap_time_s"] >= q75 if has_time else pd.Series([False]*len(rs), index=rs.index),
                 "#CC2200", 5, "55"),
                ((rs["lap_time_s"] > q25) & (rs["lap_time_s"] < q75)
                 if has_time else pd.Series([True]*len(rs), index=rs.index),
                 "#777777", 7, "A0"),
                (rs["lap_time_s"] <= q25 if has_time else pd.Series([False]*len(rs), index=rs.index),
                 "#00BB44", 9, "FF"),
            ]
            for mask, pen_col, sz, alpha in clusters:
                grp = rs[mask][[sr_col, sf_col] +
                               [c for c in _INFO if c in rs.columns and
                                c not in (sr_col, sf_col)]]
                if grp.empty:
                    continue
                spots = self._make_spots(pg, grp, col, pen_col, sz, alpha, _INFO)
                if not spots:
                    continue
                sc = pg.ScatterPlotItem(spots=spots, hoverable=True)
                # sigClicked: 0.12.x → (scatter, pts)  /  0.13.x → (scatter, pts, ev)
                sc.sigClicked.connect(
                    lambda *a, s=self: s._on_pt_click(a[1] if len(a) >= 2 else []))
                pw.addItem(sc)
        # F/R 均等荷重ライン: SusF/130 = SusR/70 → SusF = (130/70)*SusR
        # この線上では F/R ストローク使用率が等しい（ピッチ0°相当）
        ratio = self._SUS_F_MAX / self._SUS_R_MAX   # ≈ 1.857
        pw.plot(
            [0, self._SUS_R_MAX],
            [0, self._SUS_F_MAX],
            pen=pg.mkPen("#0078D4", width=1.5, style=Qt.PenStyle.DashLine),
        )
        ti = pg.TextItem("F/R 均等荷重ライン", anchor=(0, 1), color="#0078D4")
        ti.setPos(self._SUS_R_MAX * 0.55, self._SUS_F_MAX * 0.55)
        pw.addItem(ti)
        # 固定レンジ: X=SusR 0-70mm, Y=SusF 0-130mm
        pw.setXRange(0, self._SUS_R_MAX, padding=0.02)
        pw.setYRange(0, self._SUS_F_MAX, padding=0.02)

    def _draw_radar(self, df):
        """Panel 3: ライダー指紋レーダーチャート（5軸）。"""
        import math
        pg = self._pg
        pw = self._pw_radar
        pw.clear()
        pw.addLegend()

        METRICS = [
            ("pitch",          "Pitch\n(SusF-SusR)",  True),   # (列名, ラベル, 小さい=良い)
            ("heave",          "Heave\n(avg sink)",    True),
            ("brk_susf_avg",   "BRK\nSusF",           True),
            ("apex_spd_avg",   "Apex\nSpeed",          False),  # 大きい=良い
            ("lap_time_s",     "Lap\nTime",            True),
        ]
        n = len(METRICS)
        angles = [2 * math.pi * i / n - math.pi / 2 for i in range(n)]

        # 各指標の全ライダー平均
        rider_vals: dict[str, list[float]] = {}
        raw_stats: dict[str, dict] = {}
        for rider in self._COLORS:
            if "rider" not in df.columns:
                break
            rs = df[df["rider"] == rider]
            vals = []
            stats = {}
            for col, _lbl, lower_better in METRICS:
                if col in rs.columns:
                    v = rs[col].dropna().mean()
                    stats[col] = float(v) if not pd.isna(v) else 0.0
                else:
                    stats[col] = 0.0
                vals.append(stats[col])
            rider_vals[rider] = vals
            raw_stats[rider] = stats

        if not rider_vals:
            return

        # ── 物理的分布パーセンタイル正規化 ──────────────────────────
        # 各指標で「全ラップ分布の中でライダー平均がどの位置か」を計算。
        # 2ライダーの値比較ではなく、実データ分布に対するスコアなので
        # サーキット混在でも意味のある比較が可能。
        # スコアは 0.2〜1.0 にスケール（最低20%で非表示を防ぐ）。
        _NORM_MIN = 0.2
        norm_vals: dict[str, list[float]] = {r: [] for r in rider_vals}
        for i, (col, _lbl, lower_better) in enumerate(METRICS):
            # 全ラップの分布（df = _filtered_df 結果）
            full_dist = df[col].dropna() if col in df.columns else pd.Series([], dtype=float)
            for rider in rider_vals:
                raw = rider_vals[rider][i]
                if len(full_dist) > 1 and not pd.isna(raw):
                    # ライダー平均が全分布の何パーセンタイルか
                    pct = float((full_dist < raw).mean())  # 0.0=最低, 1.0=最高
                else:
                    pct = 0.5   # データ不足は中央値扱い
                if lower_better:
                    pct = 1.0 - pct   # 「小さい=良い」指標は反転
                # 0.2〜1.0 にスケール
                norm_vals[rider].append(_NORM_MIN + pct * (1.0 - _NORM_MIN))

        # グリッド円
        for r in [0.25, 0.5, 0.75, 1.0]:
            xs = [math.cos(a) * r for a in angles] + [math.cos(angles[0]) * r]
            ys = [math.sin(a) * r for a in angles] + [math.sin(angles[0]) * r]
            pw.plot(xs, ys, pen=pg.mkPen("#DDD", width=0.7))

        # 軸線 + ラベル
        for a, (_, lbl, _b) in zip(angles, METRICS):
            pw.plot([0, math.cos(a)], [0, math.sin(a)],
                    pen=pg.mkPen("#AAA", width=0.7))
            ti = pg.TextItem(lbl, anchor=(0.5, 0.5), color="#555")
            ti.setPos(math.cos(a) * 1.22, math.sin(a) * 1.22)
            pw.addItem(ti)

        # ライダーポリゴン
        # 描画順: DA77（塗り）→ JA52（塗り）→ DA77（輪郭）→ JA52（輪郭）
        # 輪郭を最後に重ねることで両者が必ず視認できる
        items = list(self._COLORS.items())  # [("DA77", blue), ("JA52", orange)]

        # ① 塗りつぶしレイヤー（両者を薄く）
        for rider, col in items:
            if rider not in norm_vals:
                continue
            nv = norm_vals[rider]
            xs = [math.cos(angles[i]) * nv[i] for i in range(n)] + \
                 [math.cos(angles[0]) * nv[0]]
            ys = [math.sin(angles[i]) * nv[i] for i in range(n)] + \
                 [math.sin(angles[0]) * nv[0]]
            pw.plot(xs, ys,
                    pen=pg.mkPen(col, width=0),   # 輪郭なし（後で描く）
                    fillLevel=0,
                    brush=pg.mkBrush(col + "28")) # 透明度 16%

        # ② 輪郭 + 頂点マーカーレイヤー（両者を上書き）
        for rider, col in items:
            if rider not in norm_vals:
                continue
            nv = norm_vals[rider]
            xs = [math.cos(angles[i]) * nv[i] for i in range(n)] + \
                 [math.cos(angles[0]) * nv[0]]
            ys = [math.sin(angles[i]) * nv[i] for i in range(n)] + \
                 [math.sin(angles[0]) * nv[0]]
            pw.plot(xs, ys,
                    pen=pg.mkPen(col, width=2.5),
                    name=rider)

            vx = [math.cos(angles[i]) * nv[i] for i in range(n)]
            vy = [math.sin(angles[i]) * nv[i] for i in range(n)]
            pw.plot(vx, vy,
                    pen=None,
                    symbol="o", symbolSize=7,
                    symbolBrush=pg.mkBrush(col),
                    symbolPen=pg.mkPen("w", width=1.0))

        pw.setXRange(-1.4, 1.4, padding=0)
        pw.setYRange(-1.4, 1.4, padding=0)

    def _draw_trend(self, df):
        """Panel 4: Pitch / Heave を上下2段に分けて表示。"""
        pg   = self._pg
        pp   = self._pw_pitch_plot   # 上段: Pitch
        ph   = self._pw_heave_plot   # 下段: Heave
        pp.clear()
        ph.clear()

        if "pitch" not in df.columns or "lap_no" not in df.columns:
            return

        pitch_vals, heave_vals = [], []
        for rider, col in self._COLORS.items():
            if "rider" not in df.columns:
                break
            rs = df[df["rider"] == rider].sort_values("lap_no")
            if rs.empty:
                continue
            rs = rs.dropna(subset=["lap_no", "pitch", "heave"])
            if rs.empty:
                continue
            laps = rs["lap_no"].values.tolist()
            pv   = rs["pitch"].values.tolist()
            hv   = rs["heave"].values.tolist()
            pitch_vals.extend(pv)
            heave_vals.extend(hv)

            # ── Pitch パネル ────────────────────────────────────────
            pp.plot(laps, pv,
                    pen=pg.mkPen(col, width=2.2),
                    symbol="o", symbolSize=6,
                    symbolBrush=pg.mkBrush(col),
                    symbolPen=pg.mkPen("w", width=0.5),
                    name=rider)

            # ── Heave パネル ────────────────────────────────────────
            ph.plot(laps, hv,
                    pen=pg.mkPen(col, width=2.2),
                    symbol="s", symbolSize=6,          # 四角でPitchと区別
                    symbolBrush=pg.mkBrush(col),
                    symbolPen=pg.mkPen("w", width=0.5),
                    name=rider)

        # Pitch パネル: F/R 均等荷重ライン
        balance = self._SUS_F_MAX - self._SUS_R_MAX   # 60mm
        pp.addItem(pg.InfiniteLine(
            pos=balance, angle=0,
            pen=pg.mkPen("#0078D4", width=1.5, style=Qt.PenStyle.DashLine),
            label=f"F/R均等荷重 ({balance:.0f}mm)",
            labelOpts={"color": "#0078D4", "position": 0.02},
        ))

        # Y 軸をデータ範囲に合わせて自動調整（余白 15mm）
        pad = 15
        if pitch_vals:
            pp.setYRange(max(0, min(pitch_vals) - pad),
                         min(self._SUS_F_MAX, max(pitch_vals) + pad),
                         padding=0)
        if heave_vals:
            ph.setYRange(max(0, min(heave_vals) - pad),
                         min(self._SUS_F_MAX, max(heave_vals) + pad),
                         padding=0)


# ════════════════════════════════════════════════════════════════════
# チェックボックス付き多選択コンボボックス
# ════════════════════════════════════════════════════════════════════

class CheckableComboBox(QComboBox):
    """QComboBox の各アイテムにチェックボックスを持つ多選択コントロール。
    Round/Session のコンボと同じ見た目でライダーを多選択できる。
    """
    selectionChanged = pyqtSignal()

    def __init__(self, placeholder: str = "選択…", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._mdl = QStandardItemModel(self)
        self.setModel(self._mdl)
        self.setEditable(True)
        le = self.lineEdit()
        le.setReadOnly(True)
        le.setPlaceholderText(placeholder)
        le.installEventFilter(self)
        self._suppress_hide = False
        self.view().pressed.connect(self._on_item_pressed)

    # ── イベントフィルター: lineEdit クリックでポップアップ表示 ──
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if (obj is self.lineEdit()
                and event.type() == QEvent.Type.MouseButtonPress):
            self.showPopup()
            return True
        return super().eventFilter(obj, event)

    # ── アイテムクリック: チェック状態をトグル ────────────────
    def _on_item_pressed(self, index):
        item = self._mdl.itemFromIndex(index)
        if item is None:
            return
        new = (Qt.CheckState.Unchecked
               if item.checkState() == Qt.CheckState.Checked
               else Qt.CheckState.Checked)
        item.setCheckState(new)
        self._update_display()
        self._suppress_hide = True   # クリック後にポップアップを閉じない
        self.selectionChanged.emit()

    # ── ポップアップを閉じないようにする ─────────────────────
    def hidePopup(self):
        if self._suppress_hide:
            self._suppress_hide = False
            return
        super().hidePopup()

    # ── アイテム追加 ──────────────────────────────────────────
    def addCheckItem(self, text: str, user_data=None, checked: bool = True):
        item = QStandardItem(text)
        item.setData(user_data, Qt.ItemDataRole.UserRole)
        item.setCheckable(True)
        item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._mdl.appendRow(item)
        self._update_display()

    def clearItems(self):
        self._mdl.clear()
        self.lineEdit().setText("")

    # ── 状態取得 ──────────────────────────────────────────────
    def isItemChecked(self, index: int) -> bool:
        item = self._mdl.item(index)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def checkedData(self) -> list:
        """チェック済みアイテムの UserRole データのリストを返す。"""
        return [self._mdl.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self._mdl.rowCount())
                if self.isItemChecked(i)]

    # ── 一括操作 ──────────────────────────────────────────────
    def setAllChecked(self, checked: bool):
        for i in range(self._mdl.rowCount()):
            self._mdl.item(i).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_display()
        self.selectionChanged.emit()

    # ── 表示テキスト更新 ──────────────────────────────────────
    def _update_display(self):
        n = self._mdl.rowCount()
        if n == 0:
            self.lineEdit().setText("")
            return
        checked = sum(1 for i in range(n) if self.isItemChecked(i))
        if checked == 0:
            txt = "なし"
        elif checked == n:
            txt = f"全員 ({n}名)"
        else:
            txt = f"{checked}/{n} 名選択"
        self.lineEdit().setText(txt)


# ════════════════════════════════════════════════════════════════════
# Race Analysis Tab  ―  PDF ラップデータによるパフォーマンス分析
# データソース: pdf_lap_times テーブル (SQLite)
# ════════════════════════════════════════════════════════════════════

class RaceAnalysisTab(QWidget):
    """📊 Race Analysis
    4 サブタブ:
      1. 📈 ラップ推移   — セッション内ラップタイム推移（JA52/DA77/フィールド）
      2. ⏱️  タイム差    — 各ラップのトップ差・DA77-JA52差
      3. 📊 セクター比較  — Seg1–4 の平均比較（バー）
      4. 🏆 ラウンド間ベスト — ラウンドごとベストラップ推移折れ線
    """

    # JA52/DA77の固定カラー
    _COLORS = {
        "JA52": (255, 140,   0),   # orange
        "DA77": (  0, 120, 212),   # blue
    }
    # Field ライダーのデフォルトカラー（最大5名）
    _FIELD_DEFAULTS = [
        (120, 120, 120),
        (180,  80, 180),
        ( 80, 160,  80),
        (200, 100,  40),
        ( 40, 160, 200),
    ]

    # ラップ明細のデータソース（2026-06-29 Tatsuki GO で v2 overlay VIEW へ切替）。
    # VIEW race_lap_detail = v2 PASS（RACE）を優先し、無い rider-session は旧 pdf_lap_times に
    # フォールバック（非RACE 無回帰）。rollback 時は "pdf_lap_times" に戻す。
    RACE_LAP_SRC = "race_lap_detail"

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        # field rider num → (name, color_rgb)
        self._field_colors: dict[int, tuple[str, tuple]] = {}
        # rider num → combo item index
        self._rider_checks: dict[int, int] = {}
        self._setup_ui()
        self._load_meta()
        self._update_rider_ui()
        self._refresh_charts()

    # ─────────────────────────────────────────────────────────────
    # DB ヘルパー
    # ─────────────────────────────────────────────────────────────

    def _query(self, sql: str, params=()) -> list[dict]:
        try:
            with sqlite3.connect(self._db.db_path) as con:
                con.row_factory = sqlite3.Row
                return [dict(r) for r in con.execute(sql, params)]
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────
    # UI 構築
    # ─────────────────────────────────────────────────────────────

    def _setup_ui(self):
        try:
            import pyqtgraph as pg
            self._pg = pg
            pg.setConfigOption("background", "w")
            pg.setConfigOption("foreground", "k")
            self._haspg = True
        except ImportError:
            self._haspg = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(2)

        # ── フィルターバー 1行目 ─────────────────────────────────
        bar1 = QWidget()
        b1h = QHBoxLayout(bar1)
        b1h.setContentsMargins(0, 0, 0, 0)
        b1h.setSpacing(8)

        b1h.addWidget(QLabel("Round:"))
        self._combo_round = QComboBox()
        self._combo_round.setMinimumWidth(110)
        b1h.addWidget(self._combo_round)

        b1h.addWidget(QLabel("Session:"))
        self._combo_session = QComboBox()
        self._combo_session.setMinimumWidth(90)
        b1h.addWidget(self._combo_session)

        b1h.addWidget(QLabel("表示:"))
        self._chk_ja52 = QCheckBox("JA52")
        self._chk_da77 = QCheckBox("DA77")
        self._chk_ja52.setChecked(True)
        self._chk_da77.setChecked(True)
        b1h.addWidget(self._chk_ja52)
        b1h.addWidget(self._chk_da77)

        b1h.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("font-size: 10px; color: #666;")
        b1h.addWidget(self._lbl_status)

        root.addWidget(bar1)

        # ── フィルターバー 2行目 ─────────────────────────────────
        bar2 = QWidget()
        b2h = QHBoxLayout(bar2)
        b2h.setContentsMargins(0, 0, 0, 0)
        b2h.setSpacing(8)

        # ピットイン除外
        self._chk_no_pit = QCheckBox("ピットイン除外")
        self._chk_no_pit.setChecked(True)
        b2h.addWidget(self._chk_no_pit)

        # Field カラー設定ボタン
        self._btn_field_colors = QPushButton("🎨 Field カラー設定…")
        self._btn_field_colors.setFixedHeight(24)
        self._btn_field_colors.clicked.connect(self._open_field_color_dialog)
        b2h.addWidget(self._btn_field_colors)

        # Tolerance スライダー
        b2h.addWidget(QLabel(" Tol:"))
        self._spin_tol = QDoubleSpinBox()
        self._spin_tol.setRange(0.5, 10.0)
        self._spin_tol.setValue(3.0)
        self._spin_tol.setSingleStep(0.5)
        self._spin_tol.setSuffix(" s")
        self._spin_tol.setFixedWidth(72)
        self._spin_tol.setToolTip("Tolerance: ベストラップからこの秒数以内のラップを有効とする")
        self._spin_tol.valueChanged.connect(self._refresh_charts)
        b2h.addWidget(self._spin_tol)

        # ラップ明細データソースの品質表示（2026-06-29・v2 overlay 切替に伴い追加）
        self._lbl_quality = QLabel("")
        self._lbl_quality.setStyleSheet("font-size: 10px; color: #555;")
        self._lbl_quality.setToolTip(
            "ラップ明細データソース: v2 = Quality Gate PASS の Result PDF v2 抽出（pdf_lap_times_v2_staging）/ "
            "legacy = 旧 pdf_lap_times。VIEW race_lap_detail 経由（RACE は v2 優先・非RACEは legacy）。")
        b2h.addWidget(self._lbl_quality)

        b2h.addStretch()

        btn_refresh = QPushButton("↺ 更新")
        btn_refresh.setFixedHeight(24)
        btn_refresh.clicked.connect(self._refresh_charts)
        b2h.addWidget(btn_refresh)

        root.addWidget(bar2)

        # ── ライダー選択パネル（3行目）— bar1/bar2 と同スタイル ──
        bar3 = QWidget()
        b3h = QHBoxLayout(bar3)
        b3h.setContentsMargins(0, 0, 0, 0)
        b3h.setSpacing(8)

        b3h.addWidget(QLabel("ライダー:"))

        # チェックボックス付きコンボボックス（Round/Session と同スタイル）
        self._rider_combo = CheckableComboBox(placeholder="全員")
        self._rider_combo.setMinimumWidth(140)
        self._rider_combo.selectionChanged.connect(self._refresh_charts)
        b3h.addWidget(self._rider_combo)

        for txt, slot in [("全選択", "_select_all_riders"),
                          ("全解除", "_deselect_all_riders"),
                          ("TS24のみ", "_select_ts24_only")]:
            b = QPushButton(txt)
            b.setFixedHeight(24)
            b.clicked.connect(getattr(self, slot))
            b3h.addWidget(b)

        b3h.addStretch()
        root.addWidget(bar3)

        # ── シグナル接続 ─────────────────────────────────────────
        self._combo_round.currentTextChanged.connect(self._on_round_changed)
        self._combo_session.currentTextChanged.connect(self._on_session_changed)
        self._chk_ja52.stateChanged.connect(self._refresh_charts)
        self._chk_da77.stateChanged.connect(self._refresh_charts)
        self._chk_no_pit.stateChanged.connect(self._refresh_charts)

        if not self._haspg:
            root.addWidget(QLabel(
                "pyqtgraph が必要です: pip install pyqtgraph"))
            return

        # ── 共通: カスタム軸 ─────────────────────────────────────
        pg = self._pg

        class _LapAxis(pg.AxisItem):
            def tickStrings(self, values, scale, spacing):
                out = []
                for v in values:
                    try:
                        s = float(v)
                        if s <= 0:
                            out.append("")
                            continue
                        m = int(s) // 60
                        out.append(f"{m}'{s - m*60:05.2f}")
                    except Exception:
                        out.append("")
                return out

        self._LapAxis = _LapAxis

        # ── サブタブ ────────────────────────────────────────────
        tabs = QTabWidget()
        root.addWidget(tabs, stretch=1)

        # ── Tab 1: ラップ推移 + ラップ比較テーブル ─────────────────
        w1 = QWidget()
        v1 = QVBoxLayout(w1)
        v1.setContentsMargins(0, 0, 0, 0)
        sp1 = QSplitter(Qt.Orientation.Horizontal)

        # ラップ比較テーブル（左）
        self._tbl_lap = QTableWidget(0, 4)
        self._tbl_lap.setHorizontalHeaderLabels(["Lap", "JA52", "DA77", "Gap"])
        self._tbl_lap.horizontalHeader().setStretchLastSection(True)
        self._tbl_lap.setMinimumWidth(200)
        self._tbl_lap.setMaximumWidth(340)
        self._tbl_lap.setAlternatingRowColors(True)
        self._tbl_lap.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_lap.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._tbl_lap.verticalHeader().setVisible(False)
        sp1.addWidget(self._tbl_lap)

        # ラップタイム推移チャート（右）
        self._pw_lap = pg.PlotWidget(
            title="ラップタイム推移",
            axisItems={"left": _LapAxis(orientation="left")},
        )
        self._pw_lap.setMinimumHeight(400)
        self._pw_lap.showGrid(x=True, y=True, alpha=0.3)
        self._pw_lap.setLabel("left", "Lap Time (M'SS.00)")
        self._pw_lap.setLabel("bottom", "Lap No.")
        self._pw_lap.addLegend(offset=(-10, 10))
        sp1.addWidget(self._pw_lap)
        sp1.setSizes([260, 800])
        v1.addWidget(sp1)
        tabs.addTab(w1, "📈 ラップ推移")

        # ── Tab 2: タイム差 ──────────────────────────────────────
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        v2.setContentsMargins(0, 0, 0, 0)

        self._pw_gap_top = pg.PlotWidget(title="対トップ差 (秒)")
        self._pw_gap_top.setMinimumHeight(220)
        self._pw_gap_top.showGrid(x=True, y=True, alpha=0.3)
        self._pw_gap_top.setLabel("left", "Gap to Top (s)")
        self._pw_gap_top.setLabel("bottom", "Lap No.")
        self._pw_gap_top.addLegend(offset=(-10, 10))

        self._pw_gap_da_ja = pg.PlotWidget(title="DA77 vs JA52 差 (秒)")
        self._pw_gap_da_ja.setMinimumHeight(180)
        self._pw_gap_da_ja.showGrid(x=True, y=True, alpha=0.3)
        self._pw_gap_da_ja.setLabel("left", "DA77 − JA52 (s)  ← DA77 faster")
        self._pw_gap_da_ja.setLabel("bottom", "Lap No.")
        self._pw_gap_da_ja.addLine(
            y=0, pen=pg.mkPen("k", width=1, style=Qt.PenStyle.DashLine))

        sp_gap = QSplitter(Qt.Orientation.Vertical)
        sp_gap.addWidget(self._pw_gap_top)
        sp_gap.addWidget(self._pw_gap_da_ja)
        sp_gap.setSizes([420, 220])
        v2.addWidget(sp_gap)
        tabs.addTab(w2, "⏱️  タイム差")

        # ── Tab 3: セクター比較 ──────────────────────────────────
        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        v3.setContentsMargins(0, 0, 0, 0)

        sp_sec = QSplitter(Qt.Orientation.Horizontal)

        self._pw_sec_bar = pg.PlotWidget(title="セクター平均タイム比較")
        self._pw_sec_bar.setMinimumHeight(380)
        self._pw_sec_bar.showGrid(x=False, y=True, alpha=0.3)
        self._pw_sec_bar.setLabel("left", "Avg Sector Time (s)")

        # セクター別4分割グラフ (GraphicsLayoutWidget)
        self._pw_sec_glw = pg.GraphicsLayoutWidget()
        self._pw_sec_glw.setMinimumHeight(380)
        seg_colors_layout = [(220,50,50),(50,150,50),(50,50,220),(180,80,180)]
        self._pw_sec_plots = []
        for si in range(4):
            p = self._pw_sec_glw.addPlot(row=si, col=0,
                                          title=f"<b>Sector {si+1}</b>")
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setLabel("left", "s", units=None)
            p.addLegend(offset=(-10, 10), labelTextSize="7pt")
            if si < 3:
                p.getAxis("bottom").setStyle(showValues=False)
            else:
                p.setLabel("bottom", "Lap No.")
            # 全プロットのX軸を連動
            if si > 0:
                p.setXLink(self._pw_sec_plots[0])
            self._pw_sec_plots.append(p)

        sp_sec.addWidget(self._pw_sec_bar)
        sp_sec.addWidget(self._pw_sec_glw)
        sp_sec.setSizes([380, 820])
        v3.addWidget(sp_sec)
        tabs.addTab(w3, "📊 セクター比較")

        # ── Tab 4: ラウンド間ベスト推移 ──────────────────────────
        w4 = QWidget()
        v4 = QVBoxLayout(w4)
        v4.setContentsMargins(0, 0, 0, 0)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("セッション:"))
        self._combo_round_sess = QComboBox()
        for s in ["FP", "SP", "WUP1", "WUP2", "RACE1", "RACE2"]:
            self._combo_round_sess.addItem(s)
        self._combo_round_sess.currentTextChanged.connect(self._draw_round_best)
        row4.addWidget(self._combo_round_sess)
        row4.addStretch()
        v4.addLayout(row4)

        self._pw_round_best = pg.PlotWidget(
            title="ラウンド間 ベストラップ推移",
            axisItems={"left": _LapAxis(orientation="left")},
        )
        self._pw_round_best.setMinimumHeight(400)
        self._pw_round_best.showGrid(x=True, y=True, alpha=0.3)
        self._pw_round_best.setLabel("left", "Best Lap (M'SS.00)")
        self._pw_round_best.setLabel("bottom", "Round No.")
        self._pw_round_best.addLegend(offset=(-10, 10))
        v4.addWidget(self._pw_round_best)
        tabs.addTab(w4, "🏆 ラウンド間ベスト")

        # ── Tab 5: Statistics ────────────────────────────────────
        w5 = QWidget()
        v5 = QVBoxLayout(w5)
        v5.setContentsMargins(0, 0, 0, 0)
        sp5 = QSplitter(Qt.Orientation.Vertical)

        # スタッツテーブル（上）
        self._tbl_stats = QTableWidget(0, 3)
        self._tbl_stats.setHorizontalHeaderLabels(["", "JA52", "DA77"])
        self._tbl_stats.setMaximumHeight(280)
        self._tbl_stats.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl_stats.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._tbl_stats.verticalHeader().setVisible(False)
        self._tbl_stats.horizontalHeader().setStretchLastSection(True)
        sp5.addWidget(self._tbl_stats)

        # スキャッタープロット（下）
        self._pw_stats_sc = pg.PlotWidget(
            title="Lap Time Scatter",
            axisItems={"left": _LapAxis(orientation="left")},
        )
        self._pw_stats_sc.setMinimumHeight(250)
        self._pw_stats_sc.showGrid(x=True, y=True, alpha=0.3)
        self._pw_stats_sc.setLabel("left", "Lap Time (M'SS.00)")
        self._pw_stats_sc.setLabel("bottom", "Lap No.")
        self._pw_stats_sc.addLegend(offset=(-10, 10))
        sp5.addWidget(self._pw_stats_sc)
        sp5.setSizes([240, 360])
        v5.addWidget(sp5)
        tabs.addTab(w5, "📊 Statistics")

        self._tabs = tabs

    # ─────────────────────────────────────────────────────────────
    # Field カラー設定ダイアログ
    # ─────────────────────────────────────────────────────────────

    def _open_field_color_dialog(self):
        from PyQt6.QtWidgets import QColorDialog, QDialogButtonBox
        from PyQt6.QtGui import QColor

        if not self._field_colors:
            QMessageBox.information(
                self, "Field カラー設定",
                "まずデータを表示してください。\n"
                "フィールドライダーが検出されていません。")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("🎨 Field ライダー カラー設定")
        dlg.setMinimumWidth(340)
        dlg_v = QVBoxLayout(dlg)

        # ライダーごとの行
        swatch_btns: dict[int, QPushButton] = {}
        for rnum, (rname, rgb) in self._field_colors.items():
            row = QHBoxLayout()
            lbl = QLabel(f"#{rnum}  {rname}")
            lbl.setMinimumWidth(180)
            row.addWidget(lbl)
            btn = QPushButton()
            btn.setFixedSize(52, 22)
            r, g, b = rgb
            btn.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border: 1px solid #888;")
            swatch_btns[rnum] = btn

            def _pick(checked=False, _rnum=rnum, _btn=btn):
                cur_r, cur_g, cur_b = self._field_colors[_rnum][1]
                color = QColorDialog.getColor(
                    QColor(cur_r, cur_g, cur_b), dlg, "カラーを選択")
                if color.isValid():
                    new_rgb = (color.red(), color.green(), color.blue())
                    name = self._field_colors[_rnum][0]
                    self._field_colors[_rnum] = (name, new_rgb)
                    r2, g2, b2 = new_rgb
                    _btn.setStyleSheet(
                        f"background-color: rgb({r2},{g2},{b2}); border: 1px solid #888;")

            btn.clicked.connect(_pick)
            row.addWidget(btn)
            dlg_v.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(dlg.accept)
        dlg_v.addWidget(bb)

        if dlg.exec():
            self._refresh_charts()

    # ─────────────────────────────────────────────────────────────
    # メタデータ読み込み
    # ─────────────────────────────────────────────────────────────

    def _load_meta(self):
        rounds = self._query(
            f"SELECT DISTINCT round FROM {self.RACE_LAP_SRC} ORDER BY round")
        sessions = self._query(
            f"SELECT DISTINCT session_type FROM {self.RACE_LAP_SRC} ORDER BY session_type")

        self._combo_round.blockSignals(True)
        self._combo_round.clear()
        self._combo_round.addItem("全ラウンド")
        for r in rounds:
            self._combo_round.addItem(r["round"])
        self._combo_round.blockSignals(False)

        self._combo_session.blockSignals(True)
        self._combo_session.clear()
        self._combo_session.addItem("全セッション")
        for s in sessions:
            self._combo_session.addItem(s["session_type"])
        self._combo_session.blockSignals(False)

    def _on_round_changed(self, _text: str):
        rnd = self._combo_round.currentText()
        if rnd == "全ラウンド":
            rows = self._query(
                f"SELECT DISTINCT session_type FROM {self.RACE_LAP_SRC} ORDER BY session_type")
        else:
            rows = self._query(
                f"SELECT DISTINCT session_type FROM {self.RACE_LAP_SRC} WHERE round=? ORDER BY session_type",
                (rnd,))
        self._combo_session.blockSignals(True)
        self._combo_session.clear()
        self._combo_session.addItem("全セッション")
        for r in rows:
            self._combo_session.addItem(r["session_type"])
        self._combo_session.blockSignals(False)
        self._update_rider_ui()
        self._refresh_charts()

    def _on_session_changed(self, _text: str):
        self._update_rider_ui()
        self._refresh_charts()

    # ─────────────────────────────────────────────────────────────
    # ライダー選択 UI
    # ─────────────────────────────────────────────────────────────

    def _update_rider_ui(self):
        """現在のフィルター条件のライダー一覧を取得して選択パネルを再構築。"""
        where, params = self._where_clause()
        sql = f"""
            SELECT DISTINCT rider_num, rider_name
            FROM {self.RACE_LAP_SRC}
            {where}
            ORDER BY rider_num
        """
        rows = self._query(sql, params)
        seen = {r["rider_num"]: r["rider_name"] for r in rows
                if self._rider_key(r["rider_num"], r["rider_name"]) == "FIELD"}
        self._rebuild_rider_checks(seen)

    def _rebuild_rider_checks(self, seen: dict):
        """seen = {rnum: rname} でコンボボックスを再構築。"""
        self._rider_combo.selectionChanged.disconnect(self._refresh_charts)
        self._rider_combo.clearItems()
        self._rider_checks.clear()   # rnum → combo index

        for i, (rnum, rname) in enumerate(sorted(seen.items())):
            if rnum not in self._field_colors:
                self._field_colors[rnum] = (
                    rname,
                    self._FIELD_DEFAULTS[i % len(self._FIELD_DEFAULTS)],
                )
            self._rider_combo.addCheckItem(
                f"#{rnum} {rname[:14]}", user_data=rnum, checked=True)
            self._rider_checks[rnum] = i   # index記録

        self._rider_combo.selectionChanged.connect(self._refresh_charts)

    def _select_all_riders(self):
        self._rider_combo.selectionChanged.disconnect(self._refresh_charts)
        self._rider_combo.setAllChecked(True)
        self._rider_combo.selectionChanged.connect(self._refresh_charts)
        self._refresh_charts()

    def _deselect_all_riders(self):
        self._rider_combo.selectionChanged.disconnect(self._refresh_charts)
        self._rider_combo.setAllChecked(False)
        self._rider_combo.selectionChanged.connect(self._refresh_charts)
        self._refresh_charts()

    def _select_ts24_only(self):
        # Field ライダーを全解除（JA52/DA77は別チェックボックスで管理）
        self._rider_combo.selectionChanged.disconnect(self._refresh_charts)
        self._rider_combo.setAllChecked(False)
        self._rider_combo.selectionChanged.connect(self._refresh_charts)
        self._refresh_charts()

    def _is_rider_visible(self, rnum: int) -> bool:
        """Field ライダーが選択されているか（コンボボックスで確認）。"""
        checked_rnums = self._rider_combo.checkedData()
        return rnum in checked_rnums

    # ─────────────────────────────────────────────────────────────
    # チャート更新
    # ─────────────────────────────────────────────────────────────

    def refresh(self):
        self._refresh_charts()

    def _refresh_charts(self, *_):
        if not self._haspg:
            return
        self._update_quality()
        self._draw_lap_trend()
        self._draw_lap_table()
        self._draw_gap()
        self._draw_sector()
        self._draw_round_best()
        self._draw_statistics()

    def _update_quality(self):
        """現フィルタのラップ明細データソース品質を1行表示（v2/legacy・件数・抽出器バージョン）。

        データ源は VIEW `race_lap_detail`（RACE は v2 PASS 優先・非RACE は旧 pdf_lap_times フォールバック）。
        `source_tag`(v2/legacy) / `gate_status` / `extractor_version` を要約表示し、欠落を 0 埋めしない。
        """
        if not hasattr(self, "_lbl_quality"):
            return
        where, params = self._where_clause()
        try:
            rows = self._query(
                f"SELECT source_tag, COUNT(*) n, COUNT(DISTINCT rider_num) riders, "
                f"MAX(extractor_version) ev FROM {self.RACE_LAP_SRC} {where} "
                f"GROUP BY source_tag ORDER BY source_tag", params)
        except Exception:
            self._lbl_quality.setText("")
            return
        if not rows:
            self._lbl_quality.setText("lap source: （該当データなし）")
            return
        parts, ev = [], None
        for r in rows:
            parts.append(f"{r['source_tag']} {r['n']}行/{r['riders']}名")
            if r.get("ev"):
                ev = r["ev"]
        txt = "lap source: " + " ・ ".join(parts)
        if ev:
            txt += f"  [{ev}]"
        self._lbl_quality.setText(txt)

    # ─────────────────────────────────────────────────────────────
    # ユーティリティ
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _rider_key(rider_num: int, rider_name: str) -> str:
        if rider_num == 52:
            return "JA52"
        if rider_num == 77:
            return "DA77"
        return "FIELD"

    def _where_clause(self) -> tuple[str, list]:
        """フィルター状態から WHERE 句とパラメータを生成。"""
        clauses, params = [], []
        rnd = self._combo_round.currentText()
        if rnd and rnd != "全ラウンド":
            clauses.append("round = ?")
            params.append(rnd)
        sess = self._combo_session.currentText()
        if sess and sess != "全セッション":
            clauses.append("session_type = ?")
            params.append(sess)
        sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params

    def _pit_filter(self) -> str:
        """ピットイン除外チェックが ON なら AND is_pit=0 を返す。"""
        return "AND is_pit=0" if self._chk_no_pit.isChecked() else ""

    def _field_color(self, rnum: int) -> tuple:
        """Field ライダーの色を返す（ユーザー設定 or デフォルト）。"""
        if rnum in self._field_colors:
            return self._field_colors[rnum][1]
        idx = list(self._field_colors.keys()).index(rnum) \
            if rnum in self._field_colors else 0
        return self._FIELD_DEFAULTS[idx % len(self._FIELD_DEFAULTS)]

    def _register_field_riders(self, rows: list[dict]):
        """クエリ結果からフィールドライダーを登録（初回のみ色割り当て）。"""
        seen: dict[int, str] = {}
        for r in rows:
            if self._rider_key(r["rider_num"], r["rider_name"]) == "FIELD":
                seen[r["rider_num"]] = r["rider_name"]
        for i, (rnum, rname) in enumerate(seen.items()):
            if rnum not in self._field_colors:
                self._field_colors[rnum] = (
                    rname,
                    self._FIELD_DEFAULTS[i % len(self._FIELD_DEFAULTS)],
                )

    @staticmethod
    def _mk_pen(color_rgb: tuple, width: int = 2,
                style=Qt.PenStyle.SolidLine):
        import pyqtgraph as pg
        return pg.mkPen(color=color_rgb, width=width, style=style)

    @staticmethod
    def _mk_brush(color_rgb: tuple, alpha: int = 180):
        import pyqtgraph as pg
        r, g, b = color_rgb
        return pg.mkBrush(r, g, b, alpha)

    # ─────────────────────────────────────────────────────────────
    # Tab 1: ラップ推移
    # ─────────────────────────────────────────────────────────────

    def _draw_lap_trend(self):
        if not self._haspg:
            return
        import pyqtgraph as pg
        pw = self._pw_lap
        pw.clear()
        pw.enableAutoRange()
        pw.addLegend(offset=(-10, 10))

        where, params = self._where_clause()
        pit = self._pit_filter()
        sql = f"""
            SELECT rider_num, rider_name, lap_no, lap_time_s
            FROM {self.RACE_LAP_SRC}
            {where}
            AND is_outlap=0 AND is_cancelled=0 {pit}
            AND lap_time_s IS NOT NULL AND lap_time_s BETWEEN 60 AND 400
            ORDER BY rider_num, lap_no
        """
        rows = self._query(sql, params)
        if not rows:
            self._lbl_status.setText("データなし")
            return

        from collections import defaultdict
        data: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for r in rows:
            key = self._rider_key(r["rider_num"], r["rider_name"])
            data[key].append((r["lap_no"], r["lap_time_s"]))

        show_ja = self._chk_ja52.isChecked()
        show_da = self._chk_da77.isChecked()

        # Field ライダー（個別チェックボックスで表示制御）
        for rnum, (rname, c) in self._field_colors.items():
            if not self._is_rider_visible(rnum):
                continue
            pts = [(r["lap_no"], r["lap_time_s"]) for r in rows
                   if r["rider_num"] == rnum]
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            pw.plot(xs, ys,
                    pen=self._mk_pen(c, 2),
                    symbol="o", symbolSize=5,
                    symbolBrush=self._mk_brush(c, 120),
                    symbolPen=pg.mkPen(None),
                    name=f"#{rnum} {rname[:14]}")

        for key, show, label in [
            ("JA52", show_ja, "JA52 #52"),
            ("DA77", show_da, "DA77 #77"),
        ]:
            if not show or key not in data:
                continue
            pts = sorted(data[key], key=lambda x: x[0])
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            c = self._COLORS[key]
            pw.plot(xs, ys,
                    pen=self._mk_pen(c, 3),
                    symbol="o", symbolSize=7,
                    symbolBrush=self._mk_brush(c),
                    symbolPen=pg.mkPen(None),
                    name=label)

        pit_note = " (ピット除外)" if self._chk_no_pit.isChecked() else ""
        self._lbl_status.setText(
            f"{self._combo_round.currentText()} / "
            f"{self._combo_session.currentText()}{pit_note} — {len(rows)} laps")

    # ─────────────────────────────────────────────────────────────
    # Tab 2: タイム差
    # ─────────────────────────────────────────────────────────────

    def _draw_gap(self):
        if not self._haspg:
            return
        import pyqtgraph as pg
        for pw in (self._pw_gap_top, self._pw_gap_da_ja):
            pw.clear()
            pw.enableAutoRange()
        self._pw_gap_top.addLegend(offset=(-10, 10))
        self._pw_gap_da_ja.addLine(
            y=0, pen=pg.mkPen("k", width=1, style=Qt.PenStyle.DashLine))

        where, params = self._where_clause()
        pit = self._pit_filter()
        sql = f"""
            SELECT rider_num, rider_name, lap_no, lap_time_s
            FROM {self.RACE_LAP_SRC}
            {where}
            AND is_outlap=0 AND is_cancelled=0 {pit}
            AND lap_time_s IS NOT NULL AND lap_time_s > 60
            ORDER BY lap_no, lap_time_s
        """
        rows = self._query(sql, params)
        if not rows:
            return

        from collections import defaultdict
        lap_top: dict[int, float] = {}
        lap_data: dict[int, dict[int, float]] = defaultdict(dict)
        for r in rows:
            ln, lt, rnum = r["lap_no"], r["lap_time_s"], r["rider_num"]
            lap_data[ln][rnum] = lt
            if ln not in lap_top or lt < lap_top[ln]:
                lap_top[ln] = lt

        show_ja = self._chk_ja52.isChecked()
        show_da = self._chk_da77.isChecked()

        for rnum, key, label in [(52, "JA52", "JA52 #52"), (77, "DA77", "DA77 #77")]:
            show = show_ja if key == "JA52" else show_da
            if not show:
                continue
            xs, ys = [], []
            for ln in sorted(lap_data):
                if rnum in lap_data[ln] and ln in lap_top:
                    xs.append(ln)
                    ys.append(lap_data[ln][rnum] - lap_top[ln])
            if not xs:
                continue
            c = self._COLORS[key]
            self._pw_gap_top.plot(
                xs, ys, pen=self._mk_pen(c, 3),
                symbol="o", symbolSize=6,
                symbolBrush=self._mk_brush(c),
                symbolPen=pg.mkPen(None), name=label)

        # DA77 vs JA52
        xs_dj, ys_dj = [], []
        for ln in sorted(lap_data):
            if 77 in lap_data[ln] and 52 in lap_data[ln]:
                xs_dj.append(ln)
                ys_dj.append(lap_data[ln][77] - lap_data[ln][52])
        if xs_dj and (show_ja or show_da):
            c = self._COLORS["DA77"]
            self._pw_gap_da_ja.plot(
                xs_dj, ys_dj, pen=self._mk_pen(c, 3),
                symbol="d", symbolSize=7,
                symbolBrush=self._mk_brush(c),
                symbolPen=pg.mkPen(None))

    # ─────────────────────────────────────────────────────────────
    # Tab 3: セクター比較
    # ─────────────────────────────────────────────────────────────

    def _draw_sector(self):
        if not self._haspg:
            return
        import pyqtgraph as pg
        self._pw_sec_bar.clear()
        self._pw_sec_bar.enableAutoRange()
        for p in self._pw_sec_plots:
            p.clear()
            p.enableAutoRange()

        where, params = self._where_clause()
        pit = self._pit_filter()
        sql = f"""
            SELECT rider_num, rider_name, lap_no,
                   seg1, seg2, seg3, seg4, lap_time_s
            FROM {self.RACE_LAP_SRC}
            {where}
            AND is_outlap=0 AND is_cancelled=0 {pit}
            AND seg1 IS NOT NULL AND seg2 IS NOT NULL
            AND seg3 IS NOT NULL AND lap_time_s > 60
            ORDER BY lap_no
        """
        rows = self._query(sql, params)
        if not rows:
            return

        show_ja = self._chk_ja52.isChecked()
        show_da = self._chk_da77.isChecked()

        from collections import defaultdict
        segs: dict[str, list[list[float]]] = defaultdict(list)
        for r in rows:
            key = self._rider_key(r["rider_num"], r["rider_name"])
            vals = [r["seg1"] or 0, r["seg2"] or 0,
                    r["seg3"] or 0, r.get("seg4") or 0]
            if any(v > 0 for v in vals):
                segs[key].append(vals)

        seg_labels = ["Seg1", "Seg2", "Seg3", "Seg4"]
        n_segs = 4
        active = [(k, show, k) for k, show in [("JA52", show_ja), ("DA77", show_da)]
                  if show and k in segs]
        if not active:
            return
        bar_w = 0.35
        offsets = {0: (-bar_w/2 if len(active)==2 else 0),
                   1:  (bar_w/2 if len(active)==2 else 0)}

        x_ticks = [(i, seg_labels[i]) for i in range(n_segs)]
        for ri, (key, _, label) in enumerate(active):
            avgs = []
            for si in range(n_segs):
                vals = [s[si] for s in segs[key] if s[si] > 0]
                avgs.append(sum(vals)/len(vals) if vals else 0)
            c = self._COLORS[key]
            xs = [si + offsets[ri] for si in range(n_segs)]
            self._pw_sec_bar.addItem(pg.BarGraphItem(
                x=xs, height=avgs, width=bar_w,
                brush=self._mk_brush(c, 180),
                pen=pg.mkPen(c, width=1)))
        self._pw_sec_bar.getAxis("bottom").setTicks([x_ticks])

        # セクター別 4分割グラフ描画
        seg_names  = ["seg1", "seg2", "seg3", "seg4"]
        seg_colors = [(220,50,50),(50,150,50),(50,50,220),(180,80,180)]
        rider_colors = {"JA52": (230,100,30), "DA77": (30,120,210)}

        for key, show, label in [("JA52", show_ja, "JA52"), ("DA77", show_da, "DA77")]:
            if not show:
                continue
            rr = sorted([r for r in rows
                         if self._rider_key(r["rider_num"], r["rider_name"]) == key],
                        key=lambda r: r["lap_no"])
            if not rr:
                continue
            lap_nos = [r["lap_no"] for r in rr]
            style = Qt.PenStyle.SolidLine if key == "JA52" else Qt.PenStyle.DashLine
            rc = rider_colors[key]
            for si, sname in enumerate(seg_names):
                vals = [r[sname] or 0 for r in rr]
                if not any(v > 0 for v in vals):
                    continue
                self._pw_sec_plots[si].plot(
                    lap_nos, vals,
                    pen=pg.mkPen(color=rc, width=2, style=style),
                    symbol="o", symbolSize=4,
                    symbolBrush=self._mk_brush(rc, 170),
                    symbolPen=pg.mkPen(None),
                    name=label)

    # ─────────────────────────────────────────────────────────────
    # Tab 4: ラウンド間ベスト推移
    # ─────────────────────────────────────────────────────────────

    def _draw_round_best(self, *_):
        if not self._haspg:
            return
        import pyqtgraph as pg
        pw = self._pw_round_best
        pw.clear()
        pw.enableAutoRange()
        pw.addLegend(offset=(-10, 10))

        sess = self._combo_round_sess.currentText() \
            if hasattr(self, "_combo_round_sess") else "FP"
        pit = self._pit_filter()

        sql = f"""
            SELECT round, rider_num, rider_name,
                   MIN(lap_time_s) as best
            FROM {self.RACE_LAP_SRC}
            WHERE session_type = ?
              AND is_outlap=0 AND is_cancelled=0 {pit}
              AND lap_time_s IS NOT NULL AND lap_time_s > 60
            GROUP BY round, rider_num
            ORDER BY round, rider_num
        """
        rows = self._query(sql, (sess,))
        if not rows:
            self._lbl_status.setText(f"データなし ({sess})")
            return

        def _rnd_no(s: str) -> int:
            try:
                return int("".join(filter(str.isdigit, s)))
            except Exception:
                return 99

        from collections import defaultdict
        by_key: dict[str, list] = defaultdict(list)
        for r in rows:
            key = self._rider_key(r["rider_num"], r["rider_name"])
            by_key[key].append((_rnd_no(r["round"]), r["best"]))

        show_ja = self._chk_ja52.isChecked()
        show_da = self._chk_da77.isChecked()
        # Field ライダー（ラウンド間ベストはライダー選択パネルで絞らず全表示）
        for rnum, (rname, c) in self._field_colors.items():
            pts = [(_rnd_no(r["round"]), r["best"]) for r in rows
                   if r["rider_num"] == rnum]
            if not pts:
                continue
            pts.sort()
            pw.plot([p[0] for p in pts], [p[1] for p in pts],
                    pen=self._mk_pen(c, 2),
                    symbol="o", symbolSize=5,
                    symbolBrush=self._mk_brush(c, 140),
                    symbolPen=pg.mkPen(None),
                    name=f"#{rnum} {rname[:12]}")

        for key, show, label in [
            ("JA52", show_ja, "JA52 #52"),
            ("DA77", show_da, "DA77 #77"),
        ]:
            if not show or key not in by_key:
                continue
            pts = sorted(by_key[key])
            pw.plot([p[0] for p in pts], [p[1] for p in pts],
                    pen=self._mk_pen(self._COLORS[key], 3),
                    symbol="o", symbolSize=8,
                    symbolBrush=self._mk_brush(self._COLORS[key], 230),
                    symbolPen=pg.mkPen(None),
                    name=label)

        all_rnds = sorted({_rnd_no(r["round"]): r["round"] for r in rows}.items())
        pw.getAxis("bottom").setTicks([[(n, lbl) for n, lbl in all_rnds]])

    # ─────────────────────────────────────────────────────────────
    # Tab 1 補助: ラップ比較テーブル
    # ─────────────────────────────────────────────────────────────

    def _draw_lap_table(self):
        """JA52 vs DA77 のラップ毎タイム比較テーブルを更新。"""
        tbl = self._tbl_lap
        tbl.setRowCount(0)

        where, params = self._where_clause()
        pit = self._pit_filter()
        sql = f"""
            SELECT rider_num, lap_no, lap_time_s
            FROM {self.RACE_LAP_SRC}
            {where}
            AND is_outlap=0 AND is_cancelled=0 {pit}
            AND rider_num IN (52, 77)
            AND lap_time_s IS NOT NULL AND lap_time_s BETWEEN 60 AND 400
            ORDER BY lap_no
        """
        rows = self._query(sql, params)
        if not rows:
            return

        ja_laps = {r["lap_no"]: r["lap_time_s"] for r in rows if r["rider_num"] == 52}
        da_laps = {r["lap_no"]: r["lap_time_s"] for r in rows if r["rider_num"] == 77}
        if not ja_laps and not da_laps:
            return

        show_ja = self._chk_ja52.isChecked()
        show_da = self._chk_da77.isChecked()
        tol = self._spin_tol.value()

        best_ja = min(ja_laps.values()) if ja_laps else None
        best_da = min(da_laps.values()) if da_laps else None

        def _fmt(t):
            try:
                m = int(t) // 60
                return f"{m}:{t - m*60:06.3f}"
            except Exception:
                return "—"

        gold  = QColor(180, 140, 0)
        grey  = QColor(155, 155, 155)
        green = QColor(0, 155, 60)
        red   = QColor(210, 50, 50)
        font_bold = QFont()
        font_bold.setBold(True)

        all_laps = sorted(set(ja_laps.keys()) | set(da_laps.keys()))
        gaps: list[float] = []
        tbl.setRowCount(len(all_laps) + 2)  # +2 for Avg/Tot gap rows

        for i, lap in enumerate(all_laps):
            t1 = ja_laps.get(lap)
            t2 = da_laps.get(lap)

            # Lap #
            it_lap = QTableWidgetItem(f"#{lap}")
            it_lap.setForeground(grey)
            tbl.setItem(i, 0, it_lap)

            # JA52
            if t1 is not None and show_ja:
                is_b1 = best_ja is not None and abs(t1 - best_ja) < 0.001
                in_t1 = best_ja is None or t1 <= best_ja + tol
                it1 = QTableWidgetItem(_fmt(t1))
                if is_b1:
                    it1.setForeground(gold)
                    it1.setFont(font_bold)
                elif not in_t1:
                    it1.setForeground(grey)
                tbl.setItem(i, 1, it1)

            # DA77
            if t2 is not None and show_da:
                is_b2 = best_da is not None and abs(t2 - best_da) < 0.001
                in_t2 = best_da is None or t2 <= best_da + tol
                it2 = QTableWidgetItem(_fmt(t2))
                if is_b2:
                    it2.setForeground(gold)
                    it2.setFont(font_bold)
                elif not in_t2:
                    it2.setForeground(grey)
                tbl.setItem(i, 2, it2)

            # Gap (DA77 − JA52)
            if t1 is not None and t2 is not None and show_ja and show_da:
                gap = t2 - t1
                gaps.append(gap)
                it_g = QTableWidgetItem(f"{gap:+.3f}")
                it_g.setForeground(green if gap < 0 else red)
                it_g.setFont(font_bold)
                tbl.setItem(i, 3, it_g)

        # Avg / Tot gap フッター行
        n = len(all_laps)
        if gaps:
            for ri, (label, val) in enumerate([("Avg Δ", sum(gaps)/len(gaps)),
                                               ("Tot Δ", sum(gaps))]):
                row = n + ri
                tbl.setItem(row, 0, QTableWidgetItem(label))
                it_fg = QTableWidgetItem(f"{val:+.3f}")
                it_fg.setForeground(green if val < 0 else red)
                it_fg.setFont(font_bold)
                tbl.setItem(row, 3, it_fg)

        tbl.setRowCount(n + (2 if gaps else 0))
        tbl.resizeColumnsToContents()

    # ─────────────────────────────────────────────────────────────
    # Tab 5: Statistics
    # ─────────────────────────────────────────────────────────────

    def _draw_statistics(self):
        """Statistics タブのスタッツテーブル & スキャッタープロットを更新。"""
        if not self._haspg:
            return
        import pyqtgraph as pg

        pw = self._pw_stats_sc
        pw.clear()
        pw.enableAutoRange()
        pw.addLegend(offset=(-10, 10))

        tbl = self._tbl_stats

        where, params = self._where_clause()
        pit = self._pit_filter()
        sql = f"""
            SELECT rider_num, lap_no, lap_time_s
            FROM {self.RACE_LAP_SRC}
            {where}
            AND is_outlap=0 AND is_cancelled=0 {pit}
            AND rider_num IN (52, 77)
            AND lap_time_s IS NOT NULL AND lap_time_s BETWEEN 60 AND 400
            ORDER BY rider_num, lap_no
        """
        rows = self._query(sql, params)

        show_ja = self._chk_ja52.isChecked()
        show_da = self._chk_da77.isChecked()
        tol = self._spin_tol.value()

        ja_laps = [(r["lap_no"], r["lap_time_s"]) for r in rows if r["rider_num"] == 52]
        da_laps = [(r["lap_no"], r["lap_time_s"]) for r in rows if r["rider_num"] == 77]

        def _stats(laps_list):
            if not laps_list:
                return None
            ts = sorted(t for _, t in laps_list)
            best = ts[0]
            in_t = [t for t in ts if t <= best + tol]
            if not in_t:
                return None
            n = len(in_t)
            avg = sum(in_t) / n
            mid = n // 2
            median = in_t[mid] if n % 2 else (in_t[mid-1] + in_t[mid]) / 2
            q1 = in_t[max(0, int(n * 0.25))]
            q3 = in_t[min(n-1, int(n * 0.75))]
            iqr = q3 - q1
            uw = min(max(in_t), q3 + 1.5 * iqr)
            lw = max(min(in_t), q1 - 1.5 * iqr)
            return {
                "Best lap":       best,
                "Laps in tol.":   len(in_t),
                "Total valid":    len(ts),
                "Session laps":   len(laps_list),
                "Average":        avg,
                "Median (Q2)":    median,
                "Q1 (25th)":      q1,
                "Q3 (75th)":      q3,
                "IQR":            iqr,
                "Upper whisker":  uw,
                "Lower whisker":  lw,
                "Total (in tol.)": sum(in_t),
                "Total session":  sum(ts),
            }

        def _fmt_val(v, key):
            if key in ("Laps in tol.", "Total valid", "Session laps"):
                return str(int(v))
            if key == "IQR":
                return f"+{v:.3f}"
            try:
                m = int(v) // 60
                return f"{m}:{v - m*60:06.3f}"
            except Exception:
                return "—"

        s_ja = _stats(ja_laps) if show_ja else None
        s_da = _stats(da_laps) if show_da else None

        stat_keys = [
            "Best lap", "Laps in tol.", "Total valid", "Session laps",
            "Average", "Median (Q2)", "Q1 (25th)", "Q3 (75th)", "IQR",
            "Upper whisker", "Lower whisker", "Total (in tol.)", "Total session",
        ]

        # スタッツテーブル
        tbl.setRowCount(len(stat_keys))
        tbl.setColumnCount(3)
        tbl.setHorizontalHeaderLabels(["", "JA52", "DA77"])

        ja_qc = QColor(*self._COLORS["JA52"])
        da_qc = QColor(*self._COLORS["DA77"])
        gold = QColor(180, 140, 0)
        font_bold = QFont()
        font_bold.setBold(True)

        # ヘッダー色
        h = tbl.horizontalHeader()
        for ci, qc in [(1, ja_qc), (2, da_qc)]:
            tbl.horizontalHeaderItem(ci).setForeground(qc) if tbl.horizontalHeaderItem(ci) else None

        for ri, key in enumerate(stat_keys):
            tbl.setItem(ri, 0, QTableWidgetItem(key))
            for ci, stats in [(1, s_ja), (2, s_da)]:
                if stats and key in stats:
                    txt = _fmt_val(stats[key], key)
                    it = QTableWidgetItem(txt)
                    if key == "Best lap":
                        it.setForeground(gold)
                        it.setFont(font_bold)
                    tbl.setItem(ri, ci, it)

        tbl.resizeColumnsToContents()

        # スキャッタープロット（Tolerance で透明度を変える）
        best_ja = min(t for _, t in ja_laps) if ja_laps else None
        best_da = min(t for _, t in da_laps) if da_laps else None

        for rider_laps, best_t, key, show in [
            (ja_laps, best_ja, "JA52", show_ja),
            (da_laps, best_da, "DA77", show_da),
        ]:
            if not show or not rider_laps:
                continue
            c = self._COLORS[key]
            in_laps  = [(l, t) for l, t in rider_laps if best_t is None or t <= best_t + tol]
            out_laps = [(l, t) for l, t in rider_laps if best_t is not None and t > best_t + tol]

            if in_laps:
                pw.plot([p[0] for p in in_laps], [p[1] for p in in_laps],
                        pen=None, symbol="o", symbolSize=9,
                        symbolBrush=self._mk_brush(c, 210),
                        symbolPen=pg.mkPen(None),
                        name=f"{key} (in tol.)")
            if out_laps:
                pw.plot([p[0] for p in out_laps], [p[1] for p in out_laps],
                        pen=None, symbol="o", symbolSize=7,
                        symbolBrush=self._mk_brush(c, 50),
                        symbolPen=pg.mkPen(None))
            # ベストラップに★マーク
            if best_t is not None:
                best_nos = [l for l, t in rider_laps if abs(t - best_t) < 0.001]
                if best_nos:
                    pw.plot([best_nos[0]], [best_t],
                            pen=None, symbol="star", symbolSize=16,
                            symbolBrush=pg.mkBrush(200, 160, 0, 240),
                            symbolPen=pg.mkPen(None))


class CommentAnalysisTab(QWidget):
    """ライダーコメント分析 (Trend Analysis 置換, 2026-06-19 Tatsuki要望)。
    コメントから紐解く: (1)コース特性の特別な問題(再発ハイライト) (2)タイヤ種類変更コメント
    (3)tag/circuit別の問題傾向。データ源: runs.comment + run_tags + runs.tyre/best_lap。"""
    TYRE_KW = ("tyre", "tire", "compound", "grip", "new", "used", "sc0", "sc1", "sc2",
               "bridgestone", "michelin", "pirelli", "soft", "medium", "hard", "rear t", "front t")

    def __init__(self, db: "WorkbenchDB", parent=None):
        super().__init__(parent)
        self._db = db
        self._build_ui()
        self.refresh()

    def _con(self):
        import sqlite3
        c = sqlite3.connect(self._db.db_path); c.row_factory = sqlite3.Row
        return c

    def _build_ui(self):
        lay = QVBoxLayout(self)
        # ── Panel 1: フィルタ ──
        f = QHBoxLayout()
        self._cb_circuit = QComboBox(); self._cb_rider = QComboBox(); self._cb_tag = QComboBox()
        self._ed_kw = QLineEdit(); self._ed_kw.setPlaceholderText("キーワード全文検索")
        self._ck_tyre = QCheckBox("タイヤ関連のみ")
        btn = QPushButton("🔍 検索"); btn.clicked.connect(self.refresh)
        for cb in (self._cb_circuit, self._cb_rider, self._cb_tag):
            cb.addItem("ALL")
        try:
            with self._con() as c:
                for r in c.execute("SELECT DISTINCT circuit FROM runs WHERE circuit IS NOT NULL ORDER BY circuit"):
                    self._cb_circuit.addItem(r[0])
                for r in c.execute("SELECT DISTINCT rider FROM runs WHERE rider IS NOT NULL ORDER BY rider"):
                    self._cb_rider.addItem(r[0])
                for r in c.execute("SELECT DISTINCT tag FROM run_tags ORDER BY tag"):
                    self._cb_tag.addItem(r[0])
        except Exception:
            pass
        for cb in (self._cb_circuit, self._cb_rider, self._cb_tag):
            cb.currentTextChanged.connect(self.refresh)
        self._ck_tyre.toggled.connect(self.refresh)
        for w in (QLabel("Circuit"), self._cb_circuit, QLabel("Rider"), self._cb_rider,
                  QLabel("Tag"), self._cb_tag, self._ed_kw, self._ck_tyre, btn):
            f.addWidget(w)
        f.addStretch(1)
        lay.addLayout(f)
        self._lbl = QLabel(""); self._lbl.setStyleSheet("color:#666;font-size:11px;padding:2px;")
        lay.addWidget(self._lbl)
        # ── Panel 2/3: 再発頻度表 + コメント詳細 ──
        split = QSplitter(Qt.Orientation.Vertical)
        self._tbl_freq = QTableWidget(); self._tbl_detail = QTableWidget()
        split.addWidget(self._wrap("🔴 コース特性の問題: Circuit×Tag 頻度 (3回以上=赤=再発)", self._tbl_freq))
        split.addWidget(self._wrap("💬 コメント詳細 (タイヤ変更/Best Lap/Tag 付き)", self._tbl_detail))
        split.setSizes([260, 460])
        lay.addWidget(split, 1)

    def _wrap(self, title, tbl):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title); lbl.setStyleSheet("font-weight:bold;padding:4px;")
        v.addWidget(lbl); v.addWidget(tbl)
        return w

    def refresh(self):
        try:
            self._load()
        except Exception as e:
            if hasattr(self, "_lbl"):
                self._lbl.setText(f"⚠ {e}")

    def _load(self):
        circ = self._cb_circuit.currentText(); rider = self._cb_rider.currentText()
        tag = self._cb_tag.currentText(); kw = self._ed_kw.text().strip(); tyre = self._ck_tyre.isChecked()
        with self._con() as c:
            # Panel2: Circuit×Tag 頻度
            q = ("SELECT r.circuit, rt.tag, count(*) cnt, group_concat(DISTINCT r.rider) riders "
                 "FROM run_tags rt JOIN runs r ON rt.run_id=r.run_id WHERE 1=1")
            p = []
            if circ != "ALL": q += " AND r.circuit=?"; p.append(circ)
            if rider != "ALL": q += " AND r.rider=?"; p.append(rider)
            if tag != "ALL": q += " AND rt.tag=?"; p.append(tag)
            q += " GROUP BY r.circuit, rt.tag ORDER BY cnt DESC"
            freq = c.execute(q, p).fetchall()
            # Panel3: コメント詳細
            q2 = ("SELECT r.date,r.circuit,r.session,r.rider,r.run_no,r.comment,r.tyre_front,r.tyre_rear,"
                  "r.best_lap_s,(SELECT group_concat(tag) FROM run_tags WHERE run_id=r.run_id) tags "
                  "FROM runs r WHERE r.comment IS NOT NULL AND r.comment<>''")
            p2 = []
            if circ != "ALL": q2 += " AND r.circuit=?"; p2.append(circ)
            if rider != "ALL": q2 += " AND r.rider=?"; p2.append(rider)
            if tag != "ALL": q2 += " AND r.run_id IN (SELECT run_id FROM run_tags WHERE tag=?)"; p2.append(tag)
            if kw: q2 += " AND lower(r.comment) LIKE ?"; p2.append(f"%{kw.lower()}%")
            q2 += " ORDER BY r.date DESC, r.circuit, r.rider, r.run_no"
            det = c.execute(q2, p2).fetchall()
        if tyre:
            det = [d for d in det if any(k in (d["comment"] or "").lower() for k in self.TYRE_KW)]
        self._fill_freq(freq); self._fill_detail(det)
        self._lbl.setText(f"再発tag(3+): {sum(1 for r in freq if r['cnt']>=3)} 種 / コメント {len(det)} 件")

    def _fill_freq(self, rows):
        cols = ["Circuit", "Tag", "Count", "Riders"]
        self._tbl_freq.clear(); self._tbl_freq.setColumnCount(len(cols))
        self._tbl_freq.setHorizontalHeaderLabels(cols); self._tbl_freq.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["circuit"] or "", r["tag"] or "", str(r["cnt"]), r["riders"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if r["cnt"] >= 3:
                    it.setBackground(QColor("#FFC7CE"))
                self._tbl_freq.setItem(i, j, it)
        self._tbl_freq.resizeColumnsToContents()

    def _fill_detail(self, rows):
        cols = ["Date", "Circuit", "Session", "Rider", "Run", "Tyre F/R", "Best", "Tags", "Comment"]
        self._tbl_detail.clear(); self._tbl_detail.setColumnCount(len(cols))
        self._tbl_detail.setHorizontalHeaderLabels(cols); self._tbl_detail.setRowCount(len(rows))

        def _fmt(s):
            if s is None: return ""
            m = int(s // 60); return f"{m}:{s-60*m:06.3f}"
        for i, r in enumerate(rows):
            vals = [r["date"] or "", r["circuit"] or "", r["session"] or "", r["rider"] or "",
                    str(r["run_no"] or ""), f"{r['tyre_front'] or ''}/{r['tyre_rear'] or ''}",
                    _fmt(r["best_lap_s"]), r["tags"] or "", (r["comment"] or "").replace("\n", " ")]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 8 and any(k in (r["comment"] or "").lower() for k in self.TYRE_KW):
                    it.setBackground(QColor("#FFF2CC"))   # タイヤ言及コメントを淡色強調
                self._tbl_detail.setItem(i, j, it)
        self._tbl_detail.resizeColumnsToContents()


class ImportQualityTab(QWidget):
    """📥 Import / Quality — Phase 2A 未処理データ表示（読み取り専用）。
    管理テーブル(source_file_registry / import_queue / data_quality_log)のみ参照し、
    業務テーブルには触れない。検出キュー・要確認(incomplete/gated/unknown)・検出チェックを可視化。
    """
    _MGMT = ("source_file_registry", "import_queue", "data_quality_log")

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._lbl = QLabel("…")
        self._lbl.setStyleSheet("font-weight: bold;")
        bar.addWidget(self._lbl)
        bar.addStretch()
        btn = QPushButton("↻ 再読込")
        btn.clicked.connect(self.refresh)
        bar.addWidget(btn)
        lay.addLayout(bar)

        note = QLabel("Phase 2A: 検出→registry→queue の可視化のみ（業務テーブル不変・抽出なし）。"
                      "再評価/承認は将来。FAIL/WARNING は data_quality_log の detect_* に基づく。")
        note.setStyleSheet("color:#666; font-size:11px;")
        note.setWordWrap(True)
        lay.addWidget(note)

        inner = QTabWidget()
        self._tbl_queue = QTableWidget()
        self._tbl_queue.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        inner.addTab(self._wrap(self._tbl_queue), "📋 未処理キュー")
        self._tbl_doubt = QTableWidget()
        self._tbl_doubt.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        inner.addTab(self._wrap(self._tbl_doubt), "⚠ 要確認（疑い）")
        self._tbl_checks = QTableWidget()
        self._tbl_checks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        inner.addTab(self._wrap(self._tbl_checks), "🔎 検出チェック (detect_*)")
        lay.addWidget(inner)
        self.refresh()

    @staticmethod
    def _wrap(w):
        box = QWidget(); l = QVBoxLayout(box); l.setContentsMargins(0, 0, 0, 0); l.addWidget(w)
        return box

    def _con(self):
        c = sqlite3.connect(self._db.db_path)
        c.row_factory = sqlite3.Row
        return c

    def refresh(self):
        try:
            self._load()
        except Exception as e:
            self._lbl.setText(f"⚠ {e}")

    def _load(self):
        with self._con() as c:
            have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(self._MGMT) <= have:
                self._lbl.setText("管理テーブル未作成。create_quality_tables.py / extraction_scan.py を先に実行してください。")
                for t in (self._tbl_queue, self._tbl_doubt, self._tbl_checks):
                    t.setRowCount(0)
                return
            reg = c.execute("SELECT status, COUNT(*) n FROM source_file_registry GROUP BY status").fetchall()
            q = c.execute("SELECT status, COUNT(*) n FROM import_queue GROUP BY status").fetchall()
            reg_s = " ".join(f"{r['status']}={r['n']}" for r in reg) or "—"
            q_s = " ".join(f"{r['status']}={r['n']}" for r in q) or "—"
            queue_rows = c.execute(
                """SELECT q.queue_id, q.status, q.target_kind, q.enqueued_at,
                          r.file_type, r.file_name, r.round, r.rider, r.circuit, r.session, q.file_path
                   FROM import_queue q LEFT JOIN source_file_registry r ON q.file_id=r.file_id
                   ORDER BY (q.status='pending') DESC, q.target_kind, q.queue_id"""
            ).fetchall()
            doubt_rows = c.execute(
                """SELECT status, file_type, file_name, round, rider, circuit, notes, file_path
                   FROM source_file_registry WHERE status IN ('incomplete','gated','unknown')
                   ORDER BY status, file_type"""
            ).fetchall()
            last_run = c.execute(
                "SELECT analysis_run_id FROM analysis_run_log WHERE status='success' "
                "ORDER BY started_at DESC LIMIT 1").fetchone()
            arid = last_run["analysis_run_id"] if last_run else ""
            check_rows = c.execute(
                """SELECT check_name, result, severity, scope_id, detail FROM data_quality_log
                   WHERE check_name LIKE 'detect_%' AND (?='' OR analysis_run_id=?)
                   ORDER BY (result='FAIL') DESC, (result='WARNING') DESC, check_name""",
                (arid, arid),
            ).fetchall()

        self._lbl.setText(f"registry: {reg_s}   |   queue: {q_s}   |   要確認 {len(doubt_rows)} / 検出チェック {len(check_rows)}")
        self._fill_queue(queue_rows)
        self._fill_doubt(doubt_rows)
        self._fill_checks(check_rows)

    def _fill_queue(self, rows):
        cols = ["queue_id", "status", "種別", "type", "Round", "Rider", "Circuit", "Session", "enqueued", "file"]
        t = self._tbl_queue
        t.clear(); t.setColumnCount(len(cols)); t.setHorizontalHeaderLabels(cols); t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [str(r["queue_id"]), r["status"] or "", r["target_kind"] or "", r["file_type"] or "",
                    r["round"] or "", r["rider"] or "", r["circuit"] or "", r["session"] or "",
                    (r["enqueued_at"] or "")[:19], r["file_name"] or r["file_path"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if r["status"] == "failed":
                    it.setBackground(QColor("#FFC7CE"))
                elif r["status"] == "awaiting_gate":
                    it.setBackground(QColor("#FFF2CC"))
                t.setItem(i, j, it)
        t.resizeColumnsToContents()

    def _fill_doubt(self, rows):
        cols = ["status", "type", "name", "Round", "Rider", "Circuit", "notes", "file"]
        t = self._tbl_doubt
        t.clear(); t.setColumnCount(len(cols)); t.setHorizontalHeaderLabels(cols); t.setRowCount(len(rows))
        color = {"gated": "#FFC7CE", "unknown": "#FFD9A0", "incomplete": "#FFF2CC"}
        for i, r in enumerate(rows):
            vals = [r["status"] or "", r["file_type"] or "", r["file_name"] or "", r["round"] or "",
                    r["rider"] or "", r["circuit"] or "", r["notes"] or "", r["file_path"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setBackground(QColor(color.get(r["status"], "#FFFFFF")))
                t.setItem(i, j, it)
        t.resizeColumnsToContents()

    def _fill_checks(self, rows):
        cols = ["check_name", "result", "severity", "scope_id", "detail"]
        t = self._tbl_checks
        t.clear(); t.setColumnCount(len(cols)); t.setHorizontalHeaderLabels(cols); t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["check_name"] or "", r["result"] or "", r["severity"] or "",
                    r["scope_id"] or "", r["detail"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if r["result"] == "FAIL":
                    it.setBackground(QColor("#FFC7CE"))
                elif r["result"] == "WARNING":
                    it.setBackground(QColor("#FFF2CC"))
                t.setItem(i, j, it)
        t.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self, db: WorkbenchDB):
        super().__init__()
        self._db = db
        self.setWindowTitle("TS24 Engineer Workbench v2.0")
        self.resize(1400, 800)
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 上部ツールバー ────────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("background: #1E1E1E; border-bottom: 1px solid #333;")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(8, 4, 8, 4)

        lbl_title = QLabel("TS24 Engineer Workbench v2.0")
        lbl_title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF;")
        tb_lay.addWidget(lbl_title)
        tb_lay.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #888; font-size: 10px;")
        tb_lay.addWidget(self._lbl_status)

        root.addWidget(toolbar)

        # ── タブエリア ────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()

        self._tab_quick       = QuickLogTab(db=self._db)
        self._tab_problem     = ProblemLogTab(db=self._db)
        self._tab_comment     = CommentAnalysisTab(db=self._db)   # Trend Analysis 置換(2026-06-19)
        self._tab_setup       = SetupDecisionTab(db=self._db)
        self._tab_posture     = PostureAnalysisTab(db=self._db)
        self._tab_race        = RaceAnalysisTab(db=self._db)
        self._tab_import      = ImportQualityTab(db=self._db)      # Phase 2A 未処理データ(2026-06-21)

        self._tabs.addTab(self._tab_quick,       "⚡ Quick Log")
        self._tabs.addTab(self._tab_problem,     "📋 Problem Log")
        self._tabs.addTab(self._tab_comment,     "💬 Comment Analysis")
        self._tabs.addTab(self._tab_setup,       "🔧 Setup Decision")
        self._tabs.addTab(self._tab_posture,     "🦾 Suspension/Posture")
        self._tabs.addTab(self._tab_race,        "🏁 Race Analysis")
        self._tabs.addTab(self._tab_import,      "📥 Import / Quality")

        root.addWidget(self._tabs)

        # ── DB ファイル監視 ──────────────────────────────────────────────────────
        self._fs_watcher = QFileSystemWatcher([str(DB_PATH)])
        self._fs_watcher.fileChanged.connect(self._on_db_changed)

    def _on_db_changed(self, _path: str) -> None:
        """DB ファイルが更新されたとき全タブを自動リフレッシュする。"""
        self._lbl_status.setText("🔄 DB更新検出 — リフレッシュ中…")
        for tab in (self._tab_quick, self._tab_problem, self._tab_comment, self._tab_setup,
                    self._tab_posture, self._tab_race, self._tab_import):
            try:
                tab.refresh()
            except Exception:
                pass
        # watchdog が rename-replace でファイルを再作成する場合、パスが消える
        if str(DB_PATH) not in self._fs_watcher.files():
            self._fs_watcher.addPath(str(DB_PATH))
        self._lbl_status.setText("✅ リフレッシュ完了")

    def _on_run_selected(self, run_id: str, meta: dict) -> None:
        """RunBrowserでRunが選択されたとき全タブに伝播する。"""
        self._tab_quick.set_run(run_id, meta)
        self._tab_problem.set_run(run_id, meta)
        self._tab_setup.set_run(run_id, meta)
        self._lbl_status.setText(
            f"Run: {run_id}  |  {meta.get('circuit','')}  {meta.get('rider','')}  "
            f"Run#{meta.get('run_no','')}"
        )
        self._tabs.setCurrentWidget(self._tab_problem)




# ════════════════════════════════════════════════════════════════════
# エントリーポイント
# ════════════════════════════════════════════════════════════════════

def main():
    if not DB_PATH.exists():
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "DB not found",
            f"ts24_unified.db が見つかりません:\n{DB_PATH}\n\n"
            "02_DATABASE フォルダを確認してください。",
        )
        sys.exit(1)

    db = WorkbenchDB(DB_PATH, XL_PATH)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 10))

    # macOS ダークモードでも常にライトテーマを使用する
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,           QColor(245, 245, 245))
    pal.setColor(QPalette.ColorRole.WindowText,       QColor(20,  20,  20))
    pal.setColor(QPalette.ColorRole.Base,             QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.AlternateBase,    QColor(233, 233, 233))
    pal.setColor(QPalette.ColorRole.ToolTipBase,      QColor(255, 255, 220))
    pal.setColor(QPalette.ColorRole.ToolTipText,      QColor(0,   0,   0))
    pal.setColor(QPalette.ColorRole.Text,             QColor(20,  20,  20))
    pal.setColor(QPalette.ColorRole.Button,           QColor(240, 240, 240))
    pal.setColor(QPalette.ColorRole.ButtonText,       QColor(20,  20,  20))
    pal.setColor(QPalette.ColorRole.BrightText,       QColor(255, 0,   0))
    pal.setColor(QPalette.ColorRole.Link,             QColor(0,   100, 200))
    pal.setColor(QPalette.ColorRole.Highlight,        QColor(42,  130, 218))
    pal.setColor(QPalette.ColorRole.HighlightedText,  QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.PlaceholderText,  QColor(160, 160, 160))
    app.setPalette(pal)

    window = MainWindow(db)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
