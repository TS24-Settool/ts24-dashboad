"""
ts24_workbench.py — TS24 Engineer Workbench v0.1
=================================================
PyQt6製ローカルデスクトップアプリ。
ラップデータを見ながら Problem Log / Setup Decision を DB に記録する作業台。

読み取り: ts24_unified.db, lap_overlay_data.json, turn_templates.json
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
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QLineEdit, QFrame, QScrollArea,
)

# ── パス設定 ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DB_PATH      = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
OVERLAY_JSON = SCRIPT_DIR / "lap_overlay_data.json"
TEMPLATES_JSON = SCRIPT_DIR / "turn_templates.json"

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


# ════════════════════════════════════════════════════════════════════
# DB アクセス層
# ════════════════════════════════════════════════════════════════════

class WorkbenchDB:
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        try:
            with self._conn() as conn:
                self._migrate_problem_log(conn)
        except Exception:
            pass

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

    def get_setup_decisions(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute(
                """SELECT * FROM setup_decision_log WHERE run_id_from = ?
                   ORDER BY created_at DESC""",
                (run_id,),
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


# ════════════════════════════════════════════════════════════════════
# 波形ビュー (Speed / Brake / Gas — Reference only)
# ════════════════════════════════════════════════════════════════════

class WaveformView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlay_data: list[dict] = []
        self._templates: dict = {}
        self._circuit: str = ""
        self._csv_x_mode: str = "progress"   # "time" | "progress"
        self._laps_cache: list[dict] = []
        self._problem_tab: "ProblemLogTab | None" = None
        self._run_id_wave: str = ""
        self._setup_ui()
        self._load_static_data()

    def set_problem_tab(self, tab: "ProblemLogTab") -> None:
        """MainWindow から呼ばれ、Problem Log タブへの参照を設定する。"""
        self._problem_tab = tab

    def _setup_ui(self):
        try:
            import pyqtgraph as pg
            self._pg = pg
            self._has_pg = True
        except ImportError:
            self._has_pg = False

        layout = QVBoxLayout(self)

        # Reference warning (hidden in time mode, visible in progress mode)
        self._lbl_warn = QLabel(
            "⚠️  Reference only — time-normalized data, not track-position aligned."
        )
        self._lbl_warn.setStyleSheet("color: #D83B01; font-style: italic; padding: 4px;")
        layout.addWidget(self._lbl_warn)

        # X-axis mode indicator
        self._lbl_xmode = QLabel("X axis: Lap Progress (0–1)")
        self._lbl_xmode.setStyleSheet(
            "color: #107C10; font-size: 10px; padding: 2px 4px;"
            " background: #F0FFF0; border-radius: 3px;"
        )
        layout.addWidget(self._lbl_xmode)

        # Lap selectors
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Lap A:"))
        self._combo_a = QComboBox()
        self._combo_a.setMinimumWidth(260)
        sel_row.addWidget(self._combo_a)
        sel_row.addSpacing(16)
        sel_row.addWidget(QLabel("Lap B:"))
        self._combo_b = QComboBox()
        self._combo_b.setMinimumWidth(260)
        sel_row.addWidget(self._combo_b)
        btn = QPushButton("表示更新")
        btn.clicked.connect(self._draw)
        sel_row.addWidget(btn)
        btn_send_log = QPushButton("📋  Problem Log へ送る")
        btn_send_log.setToolTip(
            "選択範囲（青いハイライト）の座標情報を Problem Log に自動入力します。\n"
            "Lap A の run_id / lap_no / time / distance が入力されます。"
        )
        btn_send_log.setStyleSheet(
            "QPushButton { background: #107C10; color: white; padding: 4px 12px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #0D6A0D; }"
        )
        btn_send_log.clicked.connect(self._send_to_problem_log)
        sel_row.addSpacing(24)
        sel_row.addWidget(btn_send_log)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        if self._has_pg:
            pg = self._pg
            pg.setConfigOption("background", "w")
            pg.setConfigOption("foreground", "k")
            self._plot_widget = pg.GraphicsLayoutWidget()
            self._p_speed  = self._plot_widget.addPlot(row=0, col=0, title="Speed (km/h)")
            self._p_brake  = self._plot_widget.addPlot(row=1, col=0, title="Brake (bar)")
            self._p_gas    = self._plot_widget.addPlot(row=2, col=0, title="Gas (%)")
            self._p_suspf  = self._plot_widget.addPlot(row=3, col=0, title="SUSP_FRONT (mm)")
            self._p_suspr  = self._plot_widget.addPlot(row=4, col=0, title="SUSP_REAR (mm)")
            self._all_plots = (
                self._p_speed, self._p_brake, self._p_gas,
                self._p_suspf, self._p_suspr,
            )
            for p in self._all_plots:
                p.setLabel("bottom", "Lap Progress")
                p.showGrid(x=True, y=True, alpha=0.3)
                p.setXRange(0, 1)
            # Link all X axes to Speed panel
            for p in (self._p_brake, self._p_gas, self._p_suspf, self._p_suspr):
                p.setXLink(self._p_speed)
            # ── LinearRegionItem（選択範囲）────────────────────────
            self._region = pg.LinearRegionItem(
                values=[0.2, 0.4],
                brush=pg.mkBrush(0, 120, 212, 30),
                pen=pg.mkPen("#0078D4", width=1.5),
                movable=True,
            )
            self._region.setZValue(10)
            self._p_speed.addItem(self._region)
            layout.addWidget(self._plot_widget)
        else:
            layout.addWidget(QLabel(
                "pyqtgraph が見つかりません。\n"
                "pip install pyqtgraph でインストールしてください。"
            ))

    def _load_static_data(self):
        if OVERLAY_JSON.exists():
            try:
                self._overlay_data = json.loads(OVERLAY_JSON.read_text(encoding="utf-8"))
            except Exception:
                self._overlay_data = []
        if TEMPLATES_JSON.exists():
            try:
                self._templates = json.loads(TEMPLATES_JSON.read_text(encoding="utf-8"))
            except Exception:
                self._templates = {}

    def set_run(self, run_id: str, circuit: str):
        self._run_id_wave = run_id
        self._circuit = circuit
        self._csv_x_mode = "progress"
        self._lbl_warn.setVisible(True)
        self._lbl_xmode.setText("X axis: Lap Progress (0–1)")
        self._lbl_xmode.setStyleSheet(
            "color: #107C10; font-size: 10px; padding: 2px 4px;"
            " background: #F0FFF0; border-radius: 3px;"
        )
        if self._has_pg:
            for p in self._all_plots:
                p.setLabel("bottom", "Lap Progress")
        self._combo_a.clear()
        self._combo_b.clear()
        if not self._overlay_data:
            return
        laps = [r for r in self._overlay_data if r.get("run_id") == run_id]
        labels = [
            f"Lap {r.get('lap_no','?')}  {r.get('lap_time_s','?')}s"
            for r in laps
        ]
        self._combo_a.addItems(labels)
        self._combo_b.addItems(labels)
        if len(labels) > 1:
            self._combo_b.setCurrentIndex(1)
        self._laps_cache = laps

    def set_csv_laps(self, laps: list[dict]):
        """CSV インポートからのラップデータを波形に設定する（§0 参考値）。

        laps 要素の形式:
          {"x": [...], "speed": [...], "brake": [...],
           "gas": [...], "susp_front": [...], "susp_rear": [...],
           "x_mode": "time" | "progress", "lap_no": int, "lap_time_s": float}
        """
        self._laps_cache = laps
        self._circuit = ""
        self._csv_x_mode = laps[0].get("x_mode", "progress") if laps else "progress"
        if self._has_pg:
            if self._csv_x_mode == "distance":
                x_label    = "Distance (m)"
                mode_text  = "X axis: Distance (m)  [CSV]"
                mode_style = (
                    "color: #107C10; font-size: 10px; padding: 2px 4px;"
                    " background: #F0FFF0; border-radius: 3px;"
                )
                self._lbl_warn.setVisible(False)
            elif self._csv_x_mode == "time":
                x_label    = "Time (s)"
                mode_text  = "X axis: Time (s)  [CSV]"
                mode_style = (
                    "color: #0078D4; font-size: 10px; padding: 2px 4px;"
                    " background: #EFF6FF; border-radius: 3px;"
                )
                self._lbl_warn.setVisible(False)
            else:
                x_label    = "Lap Progress (0–1)  [fallback]"
                mode_text  = "X axis: Normalized Progress (0–1)  [CSV — Dist/Time not found]"
                mode_style = (
                    "color: #797673; font-size: 10px; padding: 2px 4px;"
                    " background: #FAF9F8; border-radius: 3px;"
                )
                self._lbl_warn.setVisible(True)
            for p in self._all_plots:
                p.setLabel("bottom", x_label)
            self._lbl_xmode.setText(mode_text)
            self._lbl_xmode.setStyleSheet(mode_style)
        self._combo_a.clear()
        self._combo_b.clear()
        labels = []
        for i, r in enumerate(laps):
            lap_no = r.get("lap_no", i + 1)
            lt = r.get("lap_time_s")
            lt_str = format_laptime(float(lt)) if lt else "?:??,-"
            x_mode_r = r.get("x_mode", "progress")
            if x_mode_r == "distance":
                dist_m = r.get("dist_span_m", 0.0)
                labels.append(f"CSV Lap {lap_no}  {dist_m:.0f}m  ({lt_str})")
            else:
                labels.append(f"CSV Lap {lap_no}  {lt_str}")
        self._combo_a.addItems(labels)
        self._combo_b.addItems(labels)
        if len(labels) > 1:
            self._combo_b.setCurrentIndex(1)

    def _send_to_problem_log(self) -> None:
        """選択範囲の座標情報を ProblemLogTab に送り、自動入力させる。"""
        if self._problem_tab is None:
            QMessageBox.warning(self, "未接続", "Problem Log タブが接続されていません。")
            return
        if not self._laps_cache:
            QMessageBox.warning(self, "データなし", "波形データがありません。先に CSV を送信してください。")
            return

        ia = self._combo_a.currentIndex()
        if ia < 0 or ia >= len(self._laps_cache):
            QMessageBox.warning(self, "Lap未選択", "Lap A を選択してください。")
            return

        lap_a = self._laps_cache[ia]
        x_start, x_end = self._region.getRegion()
        if x_start > x_end:
            x_start, x_end = x_end, x_start

        x_mode = self._csv_x_mode

        data: dict = {
            "run_id":  self._run_id_wave,
            "lap_no":  lap_a.get("lap_no"),
            "x_mode":  x_mode,
        }

        if x_mode == "distance":
            data["distance_start_m"] = round(float(x_start), 1)
            data["distance_end_m"]   = round(float(x_end),   1)
            data["time_start_s"]     = None
            data["time_end_s"]       = None
        elif x_mode == "time":
            data["time_start_s"]     = round(float(x_start), 3)
            data["time_end_s"]       = round(float(x_end),   3)
            data["distance_start_m"] = None
            data["distance_end_m"]   = None
        else:
            data["time_start_s"]     = round(float(x_start), 4)
            data["time_end_s"]       = round(float(x_end),   4)
            data["distance_start_m"] = None
            data["distance_end_m"]   = None

        data["data_source_file"] = lap_a.get("source_file", "")

        self._problem_tab.prefill_from_waveform(data)

        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "_tabs"):
                idx = parent._tabs.indexOf(self._problem_tab)
                if idx >= 0:
                    parent._tabs.setCurrentIndex(idx)
                break
            parent = parent.parent()

    def _draw(self):
        if not self._has_pg or not self._laps_cache:
            return
        pg = self._pg
        import numpy as np

        ia = self._combo_a.currentIndex()
        ib = self._combo_b.currentIndex()
        if ia < 0 or ia >= len(self._laps_cache):
            return
        lap_a = self._laps_cache[ia]
        lap_b = self._laps_cache[ib] if (0 <= ib < len(self._laps_cache)) else None

        colors = {"a": pg.mkPen("#0078D4", width=2), "b": pg.mkPen("#E74C3C", width=1.5)}
        x_mode = self._csv_x_mode

        for p in self._all_plots:
            p.clear()

        def _get_x(lap):
            ch = lap.get("channels", {})
            # CSV laps use "x" key; overlay laps use "lap_progress"
            return (ch.get("x") or lap.get("x")
                    or ch.get("lap_progress") or lap.get("lap_progress"))

        def _get_y(lap, channel):
            ch = lap.get("channels", {})
            return ch.get(channel) or lap.get(channel)

        def _normalize(xs_raw):
            arr = np.array(xs_raw, dtype=float)
            lo, hi = arr.min(), arr.max()
            return (arr - lo) / (hi - lo) if hi > lo else np.zeros_like(arr)

        def _plot(lap, label, pen, channel, plot_obj):
            xs_raw = _get_x(lap)
            ys_raw = _get_y(lap, channel)
            if not xs_raw or not ys_raw or len(xs_raw) != len(ys_raw):
                return
            xs = np.array(xs_raw, dtype=float) if x_mode in ("time", "distance") else _normalize(xs_raw)
            ys = np.array(ys_raw, dtype=float)
            plot_obj.plot(x=xs, y=ys, pen=pen, name=label)

        _CHAN_PANELS = [
            ("speed",      self._p_speed),
            ("brake",      self._p_brake),
            ("gas",        self._p_gas),
            ("susp_front", self._p_suspf),
            ("susp_rear",  self._p_suspr),
        ]
        for ch, p in _CHAN_PANELS:
            _plot(lap_a, f"A Lap{lap_a.get('lap_no', '')}", colors["a"], ch, p)
            if lap_b:
                _plot(lap_b, f"B Lap{lap_b.get('lap_no', '')}", colors["b"], ch, p)

        # Y auto-range; X range depends on mode
        for p in self._all_plots:
            p.enableAutoRange(axis="y")
            if x_mode in ("time", "distance"):
                p.enableAutoRange(axis="x")
            else:
                p.setXRange(0.0, 1.0, padding=0.01)

        # Turn markers — progress mode only
        if x_mode not in ("time", "distance"):
            tmpl_raw = self._templates.get(self._circuit, [])
            if isinstance(tmpl_raw, dict):
                tmpl_raw = [{"name": k, **v} for k, v in tmpl_raw.items()
                             if isinstance(v, dict)]
            for turn in tmpl_raw:
                prog = turn.get("progress")
                if prog is None:
                    continue
                for p in self._all_plots:
                    line = pg.InfiniteLine(
                        pos=prog, angle=90,
                        pen=pg.mkPen("#107C10", width=1, style=Qt.PenStyle.DashLine),
                        label=turn.get("name", ""),
                        labelOpts={"color": "#107C10", "position": 0.9,
                                   "rotateAxis": (1, 0)},
                    )
                    p.addItem(line)


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

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run.setText(run_id or "（未選択）")
        self._refresh_table()

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
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 一覧テーブル ──────────────────────────────────
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Component", "From", "To", "Rationale", "Result"]
        )
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 280)
        self._table.setColumnWidth(5, 80)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, stretch=2)

        # 区切り
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        form_label = QLabel("▼ セットアップ変更を記録")
        form_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(form_label)

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
        btn_add   = QPushButton("追加")
        btn_clear = QPushButton("クリア")
        btn_add.clicked.connect(self._add_entry)
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

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

    def _refresh_table(self):
        rows = self._db.get_setup_decisions(self._run_id) if self._run_id else []
        self._table.setRowCount(0)
        for r in rows:
            ri = self._table.rowCount()
            self._table.insertRow(ri)
            for ci, val in enumerate([
                r.get("decision_id", ""),
                r.get("component", ""),
                r.get("from_value", ""),
                r.get("to_value", ""),
                r.get("rationale", ""),
                r.get("result_eval", ""),
            ]):
                self._table.setItem(ri, ci, QTableWidgetItem(str(val) if val is not None else "—"))

    def _add_entry(self):
        if not self._run_id:
            QMessageBox.warning(self, "未選択", "左パネルでRunを選択してください。")
            return
        run_to_idx = self._combo_run_to.currentIndex()
        run_to_data = self._combo_run_to.itemData(run_to_idx)
        run_to_val = run_to_data if run_to_data else None

        data = {
            "run_id_from":    self._run_id,
            "run_id_to":      run_to_val,
            "round":          self._run_meta.get("round"),
            "circuit":        self._run_meta.get("circuit"),
            "session":        self._run_meta.get("session"),
            "rider":          self._run_meta.get("rider"),
            "change_type":    self._combo_chg_type.currentText(),
            "component":      self._combo_comp.currentText(),
            "from_value":     self._edit_from.text().strip(),
            "to_value":       self._edit_to.text().strip(),
            "rationale":      self._txt_rationale.toPlainText().strip(),
            "expected_effect": self._txt_expected.toPlainText().strip(),
            "actual_effect":  None,
            "result_eval":    self._combo_result.currentText(),
        }
        self._db.add_setup_decision(data)
        self._clear_form()
        self._refresh_table()

    def _clear_form(self):
        self._combo_chg_type.setCurrentIndex(0)
        self._combo_comp.setCurrentIndex(0)
        self._edit_from.clear()
        self._edit_to.clear()
        self._txt_rationale.clear()
        self._txt_expected.clear()
        self._combo_result.setCurrentText("UNKNOWN")


# ════════════════════════════════════════════════════════════════════
# 2D CSV Import タブ
# ════════════════════════════════════════════════════════════════════

class CsvImportTab(QWidget):
    """2Dロガー CSV インポートタブ（§0 データソース原則: 参考値のみ）。

    対応フォーマット:
      - セミコロン区切り・カンマ小数点（2Dデータロガー標準）
      - 1行目=ヘッダー、2行目=単位（自動スキップ）
      - UTF-8 / Shift-JIS 自動判定
    """

    CHANNEL_MAP: dict[str, list[str]] = {
        "time":       ["time", "time2d"],
        "distance":   ["dist", "distance"],
        "lap_no":     ["lap", "lapno", "lap_no", "lapcounter", "lap_counter",
                       "laptrigger", "lap_trigger", "lapmarker", "lap_marker"],
        "speed":      ["speed_front", "speed"],
        "brake":      ["brake_front"],
        "gas":        ["gas", "gas_smooth", "tps"],
        "susp_front": ["susp_front"],
        "susp_rear":  ["susp_rear"],
        "lean_angle": ["bike_angle", "lean_angle"],
    }

    _TARGETS = [
        "(ignore)", "time", "distance", "lap_no", "speed", "brake", "gas",
        "susp_front", "susp_rear", "lean_angle",
    ]

    def __init__(self, wave_view: "WaveformView", db: "WorkbenchDB", parent=None):
        super().__init__(parent)
        self._wave   = wave_view
        self._db     = db
        self._run_id: str = ""
        self._df: "pd.DataFrame | None" = None
        self._col_combos: dict[str, QComboBox] = {}
        self._setup_ui()

    def set_run(self, run_id: str):
        """左パネルで Run が選択されたときに呼ばれる。"""
        self._run_id = run_id
        lbl = f"DB Run: {run_id}" if run_id else "DB Run: 未選択"
        if hasattr(self, "_lbl_split_mode"):
            current = self._lbl_split_mode.text()
            if not current or current.startswith("DB Run:"):
                self._lbl_split_mode.setText(lbl)
                self._lbl_split_mode.setStyleSheet(
                    "color: #0078D4; font-size: 10px;"
                )

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # §0 reference warning
        warn = QLabel(
            "⚠️  Reference only（§0 データソース原則）"
            " — CSV データは参考値です。権威源ではありません。"
        )
        warn.setStyleSheet("color: #D83B01; font-style: italic; padding: 4px;")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        note = QLabel(
            "CSV data is shown on Time axis when available. "
            "Progress axis is fallback only."
        )
        note.setStyleSheet("color: #605E5C; font-size: 10px; padding: 2px 0;")
        layout.addWidget(note)

        # File select
        file_row = QHBoxLayout()
        btn_browse = QPushButton("📂  CSV を開く")
        btn_browse.clicked.connect(self._browse)
        self._lbl_file = QLabel("ファイル未選択")
        self._lbl_file.setStyleSheet("color: #444;")
        file_row.addWidget(btn_browse)
        file_row.addWidget(self._lbl_file, stretch=1)
        layout.addLayout(file_row)

        self._lbl_info = QLabel("")
        self._lbl_info.setStyleSheet("color: #0078D4; font-size: 10px;")
        layout.addWidget(self._lbl_info)

        # Distance validity warning
        self._lbl_dist = QLabel("Distance invalid: Time axis only")
        self._lbl_dist.setStyleSheet(
            "color: #D83B01; font-size: 10px; padding: 2px 4px;"
            " background: #FFF4CE; border-radius: 3px;"
        )
        self._lbl_dist.setVisible(False)
        layout.addWidget(self._lbl_dist)

        # ── Lap分割設定（DB優先・fallback用距離入力）────────────────
        lap_len_row = QHBoxLayout()
        lap_len_row.addWidget(QLabel("1周距離 (m):"))
        self._spin_circuit_len = QSpinBox()
        self._spin_circuit_len.setRange(0, 20000)
        self._spin_circuit_len.setValue(4555)
        self._spin_circuit_len.setSingleStep(100)
        self._spin_circuit_len.setSpecialValueText("0 = 時間ギャップ法")
        self._spin_circuit_len.setToolTip(
            "DBにLapデータがない場合の近似分割基準距離（fallback）。\n"
            "左パネルでRunを選択するとDBから自動分割します。\n"
            "Assen = 4555m / 0 = 時間ギャップ法（>5s）"
        )
        self._spin_circuit_len.setFixedWidth(90)
        lap_len_row.addWidget(self._spin_circuit_len)
        self._lbl_split_mode = QLabel("DB Run: 未選択")
        self._lbl_split_mode.setStyleSheet("color: #0078D4; font-size: 10px;")
        lap_len_row.addWidget(self._lbl_split_mode)
        lap_len_row.addStretch()
        layout.addLayout(lap_len_row)

        # Channel mapping (scrollable)
        map_lbl = QLabel("▼ チャンネルマッピング（自動検出・手動修正可）")
        map_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(map_lbl)

        self._map_inner = QWidget()
        self._map_layout = QFormLayout(self._map_inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._map_inner)
        scroll.setMaximumHeight(180)
        layout.addWidget(scroll)

        # Preview table
        prev_lbl = QLabel("▼ データプレビュー（先頭 50 行）")
        prev_lbl.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(prev_lbl)
        self._preview = QTableWidget(0, 0)
        self._preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._preview, stretch=1)

        # Send button
        btn_row = QHBoxLayout()
        self._btn_send = QPushButton("📊  波形に送る")
        self._btn_send.setEnabled(False)
        self._btn_send.clicked.connect(self._send)
        self._btn_send.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; padding: 6px 16px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #106EBE; }"
            "QPushButton:disabled { background: #ccc; color: #888; }"
        )
        btn_row.addWidget(self._btn_send)
        self._lbl_sent = QLabel("")
        self._lbl_sent.setStyleSheet("color: #107C10; font-size: 10px; padding: 0 8px;")
        btn_row.addWidget(self._lbl_sent)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── CSV 読み込み ─────────────────────────────────────────────────

    def _browse(self):
        default = Path.home() / "Desktop" / "Data TS24 Claude" / "06_CSV"
        if not default.exists():
            default = SCRIPT_DIR.parent
        path, _ = QFileDialog.getOpenFileName(
            self, "CSV ファイルを選択", str(default),
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not path:
            return
        self._lbl_file.setText(Path(path).name)
        self._load_csv(Path(path))

    def _load_csv(self, path: Path):
        df = None
        for enc in ("utf-8-sig", "shift_jis"):
            for sep in (";", ","):
                try:
                    candidate = pd.read_csv(
                        path, encoding=enc, sep=sep,
                        decimal="," if sep == ";" else ".",
                        skiprows=[1], header=0,
                    )
                    # Accept if we get more than 1 column
                    if len(candidate.columns) > 1:
                        df = candidate
                        break
                except Exception:
                    pass
            if df is not None:
                break
        if df is None:
            QMessageBox.critical(self, "CSV 読み込みエラー", f"読み込めませんでした: {path.name}")
            return

        df.columns = [str(c).strip() for c in df.columns]
        self._df = df
        n_rows, n_cols = df.shape
        self._lbl_info.setText(f"{n_rows} 行 × {n_cols} 列 を読み込みました。")

        # Dist column validity check
        dist_col = next(
            (c for c in df.columns if c.lower().strip() in ("dist", "distance")), None
        )
        if dist_col:
            try:
                vals = pd.to_numeric(df[dist_col], errors="coerce").fillna(0).values
                self._lbl_dist.setVisible(float(vals.max()) < 10.0)
            except Exception:
                self._lbl_dist.setVisible(False)
        else:
            self._lbl_dist.setVisible(False)

        # Rebuild channel mapping
        while self._map_layout.rowCount():
            self._map_layout.removeRow(0)
        self._col_combos.clear()

        for col in df.columns:
            combo = QComboBox()
            combo.addItems(self._TARGETS)
            combo.setCurrentText(self._auto_detect(col))
            self._col_combos[col] = combo
            self._map_layout.addRow(f"{col}:", combo)

        # Preview
        preview = df.head(50)
        self._preview.setColumnCount(len(preview.columns))
        self._preview.setHorizontalHeaderLabels(list(preview.columns))
        self._preview.setRowCount(len(preview))
        for ri, row_data in enumerate(preview.itertuples(index=False)):
            for ci, val in enumerate(row_data):
                self._preview.setItem(ri, ci, QTableWidgetItem(str(val)))
        self._preview.resizeColumnsToContents()
        self._btn_send.setEnabled(True)

    def _auto_detect(self, col_name: str) -> str:
        lower = col_name.lower().strip()
        for target, aliases in self.CHANNEL_MAP.items():
            for alias in aliases:
                if alias in lower or lower in alias:
                    return target
        return "(ignore)"

    # ── 波形に送る ────────────────────────────────────────────────────

    def _send(self):
        if self._df is None:
            return

        channel_to_col: dict[str, str] = {}
        for col, combo in self._col_combos.items():
            ch = combo.currentText()
            if ch != "(ignore)":
                channel_to_col[ch] = col

        data_chs = {k for k in channel_to_col if k != "time"}
        if not data_chs:
            QMessageBox.warning(
                self, "マッピング不足",
                "speed / brake などのデータチャンネルを1つ以上割り当ててください。",
            )
            return

        has_time = "time" in channel_to_col
        has_dist = "distance" in channel_to_col

        df = self._df.copy()
        n = len(df)
        if n == 0:
            QMessageBox.warning(self, "データなし", "CSV にデータ行がありません。")
            return

        # x_mode 決定（優先順位: distance > time > progress）
        x_mode = "progress"
        if has_time:
            x_mode = "time"
        if has_dist:
            try:
                d_check = pd.to_numeric(
                    df[channel_to_col["distance"]], errors="coerce"
                ).fillna(0).values
                if float(d_check.max()) > 10.0:
                    x_mode = "distance"
            except Exception:
                pass

        # ── 時間配列の取得 ────────────────────────────────────────────
        if has_time:
            try:
                t_raw = pd.to_numeric(
                    df[channel_to_col["time"]], errors="coerce"
                ).fillna(0).values
            except Exception:
                t_raw = None
        else:
            t_raw = None

        # ── 距離配列の取得 ────────────────────────────────────────────
        d_raw = None
        if x_mode == "distance":
            try:
                d_raw = pd.to_numeric(
                    df[channel_to_col["distance"]], errors="coerce"
                ).fillna(0).values
            except Exception:
                d_raw = None
                x_mode = "time" if t_raw is not None else "progress"

        if t_raw is None and x_mode == "time":
            x_mode = "progress"

        # ── Lap分割（優先順位制御）────────────────────────────────────
        import numpy as np

        circuit_len_m = self._spin_circuit_len.value() if hasattr(self, "_spin_circuit_len") else 0
        split_mode = "unknown"

        # ─ Step A: CSV時間ギャップでセグメント境界を検出（全優先度で共通）
        segments: list[tuple[int, int]] = []
        csv_gap_durations: list[float] = []
        if t_raw is not None:
            seg_start = 0
            for i in range(1, len(t_raw)):
                if (t_raw[i] - t_raw[i - 1]) > 5.0:
                    segments.append((seg_start, i - 1))
                    csv_gap_durations.append(float(t_raw[i] - t_raw[i - 1]))
                    seg_start = i
            segments.append((seg_start, len(t_raw) - 1))
        else:
            segments = [(0, n - 1)]

        lap_indices: list[list[int]] = []

        # ─ 優先1: CSV内のLap列で分割 ─────────────────────────────────
        has_lap_col = "lap_no" in channel_to_col
        if has_lap_col:
            try:
                lap_col = pd.to_numeric(
                    df[channel_to_col["lap_no"]], errors="coerce"
                ).fillna(0).values.astype(int)
                cur_lap = lap_col[0]
                cur: list[int] = [0]
                for i in range(1, len(lap_col)):
                    if lap_col[i] != cur_lap:
                        lap_indices.append(cur)
                        cur = [i]
                        cur_lap = lap_col[i]
                    else:
                        cur.append(i)
                lap_indices.append(cur)
                lap_indices = [seg for seg in lap_indices if len(seg) >= 2]
                split_mode = "lap_col"
            except Exception:
                has_lap_col = False
                lap_indices = []

        # ─ 優先2: DBのlapsテーブルを使った精確分割 ─────────────────
        if not lap_indices and self._run_id and t_raw is not None:
            try:
                db_laps = self._db.get_laps(self._run_id)
                timed_laps = [
                    (r["lap_no"], float(r["lap_time_s"]))
                    for r in db_laps
                    if not r.get("is_outlap") and r.get("lap_time_s")
                ]
                if timed_laps:
                    GAP_TOLERANCE = 2.0
                    gap_lap_nos: set[int] = set()
                    for gap_dur in csv_gap_durations:
                        for lap_no_db, lt in timed_laps:
                            if abs(lt - gap_dur) < GAP_TOLERANCE:
                                gap_lap_nos.add(lap_no_db)
                                break
                    valid_laps = [
                        (lap_no_db, lt)
                        for lap_no_db, lt in timed_laps
                        if lap_no_db not in gap_lap_nos
                    ]
                    if valid_laps:
                        result: list[list[int]] = []
                        lap_cursor = 0
                        for s_start, s_end in segments:
                            t_cursor = float(t_raw[s_start])
                            s_dur = float(t_raw[s_end]) - t_cursor
                            accumulated = 0.0
                            while lap_cursor < len(valid_laps):
                                _, lt = valid_laps[lap_cursor]
                                if accumulated + lt > s_dur + 1.0:
                                    break
                                accumulated += lt
                                lap_cursor += 1
                                t_lap_end = t_cursor + lt
                                start_i = int(np.searchsorted(t_raw, t_cursor, side="left"))
                                end_i = int(np.searchsorted(t_raw, t_lap_end, side="right")) - 1
                                end_i = min(end_i, s_end)
                                if end_i > start_i:
                                    result.append(list(range(start_i, end_i + 1)))
                                t_cursor = float(t_raw[end_i + 1]) if end_i + 1 <= s_end else t_lap_end
                        if result:
                            lap_indices = result
                            split_mode = "db_driven"
            except Exception:
                lap_indices = []

        # ─ 優先3: 固定距離での近似分割 ───────────────────────────────
        if not lap_indices and d_raw is not None and circuit_len_m > 0:
            all_segs: list[list[int]] = []
            start_dist_val = float(d_raw[0])
            cur_d: list[int] = [0]
            for i in range(1, len(d_raw)):
                if (d_raw[i] - start_dist_val) >= circuit_len_m:
                    all_segs.append(cur_d)
                    cur_d = [i]
                    start_dist_val = float(d_raw[i])
                else:
                    cur_d.append(i)
            all_segs.append(cur_d)
            min_span = circuit_len_m * 0.5
            lap_indices = [
                seg for seg in all_segs
                if len(seg) >= 2 and (d_raw[seg[-1]] - d_raw[seg[0]]) >= min_span
            ]
            split_mode = "distance_approx"

        # ─ 優先4: 時間ギャップ法（最終fallback）────────────────────
        if not lap_indices:
            if t_raw is not None:
                for s_start, s_end in segments:
                    seg = list(range(s_start, s_end + 1))
                    if len(seg) >= 10:
                        lap_indices.append(seg)
                split_mode = "time_gap"
            else:
                lap_indices = [list(range(n))]
                split_mode = "full"

        # ─ split_mode の UI表示 ────────────────────────────────────
        mode_labels = {
            "lap_col":         ("✅ Lap列で正確分割",              "#107C10"),
            "db_driven":       ("✅ DBラップで正確分割",            "#107C10"),
            "distance_approx": ("⚠ 距離で近似分割（Approximate）", "#D83B01"),
            "time_gap":        ("⚠ 時間ギャップ分割",              "#797673"),
            "full":            ("— セッション全体",                "#797673"),
        }
        if hasattr(self, "_lbl_split_mode"):
            mode_txt, mode_clr = mode_labels.get(split_mode, ("", "#000"))
            self._lbl_split_mode.setText(mode_txt)
            self._lbl_split_mode.setStyleSheet(f"color: {mode_clr}; font-size: 10px;")

        # ── 各Lap dict を構築 ─────────────────────────────────────────
        laps: list[dict] = []
        for lap_no, idx in enumerate(lap_indices, start=1):
            if len(idx) < 2:
                continue

            if x_mode == "distance" and d_raw is not None:
                d_lap = d_raw[idx]
                x_vals = (d_lap - float(d_lap[0])).tolist()   # Lap内0始まりにリセット
                dist_span_m = round(float(d_lap[-1]) - float(d_lap[0]), 1)
                lap_time_s: float = (
                    round(float(t_raw[idx][-1]) - float(t_raw[idx][0]), 3)
                    if t_raw is not None else 0.0
                )
            elif x_mode == "time" and t_raw is not None:
                t_lap = t_raw[idx]
                x_vals = (t_lap - float(t_lap[0])).tolist()
                lap_time_s = round(float(t_lap[-1]) - float(t_lap[0]), 3)
                dist_span_m = 0.0
            else:
                x_vals = [i / max(len(idx) - 1, 1) for i in range(len(idx))]
                lap_time_s = 0.0
                dist_span_m = 0.0

            lap: dict = {
                "x":           x_vals,
                "x_mode":      x_mode,
                "lap_no":      lap_no,
                "lap_time_s":  lap_time_s,
                "dist_span_m": dist_span_m,
                "split_mode":  split_mode,
            }
            # distance modeの場合、time配列もraw保存（Problem Log記録用）
            if x_mode == "distance" and t_raw is not None:
                t_lap_arr = t_raw[idx]
                lap["time_raw"] = (t_lap_arr - float(t_lap_arr[0])).tolist()

            for ch_name, col_name in channel_to_col.items():
                if ch_name in ("time", "distance") or col_name not in df.columns:
                    continue
                try:
                    vals = pd.to_numeric(
                        df[col_name], errors="coerce"
                    ).fillna(0).values
                    lap[ch_name] = vals[idx].tolist()
                except Exception:
                    pass

            laps.append(lap)

        if not laps:
            QMessageBox.warning(self, "データなし", "有効なLapデータが見つかりません。")
            return

        self._wave.set_csv_laps(laps)

        n_laps = len(laps)
        if x_mode == "distance":
            axis_str = "Distance axis (m) ✅"
        elif x_mode == "time":
            axis_str = "Time axis (s) ✅"
        else:
            axis_str = "Progress axis (0–1) ⚠"
        self._lbl_sent.setText(f"送信: {n_laps} Lap / {axis_str}")
        QMessageBox.information(
            self, "送信完了",
            f"CSV データを波形ビューに送りました。\n"
            f"検出Lap数: {n_laps}\n"
            f"X軸: {axis_str}\n\n"
            "「📊 波形 (Reference)」タブに切り替えて確認してください。",
        )


# ════════════════════════════════════════════════════════════════════
# メインウィンドウ
# ════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self, db: WorkbenchDB):
        super().__init__()
        self._db = db
        self._run_meta: dict = {}
        self.setWindowTitle("TS24 Engineer Workbench v0.1")
        self.resize(1400, 800)
        self._setup_ui()
        self._load_circuits()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ── 左パネル ─────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(280)
        left_lay = QVBoxLayout(left)

        title = QLabel("TS24 Engineer Workbench")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        left_lay.addWidget(title)

        lbl_circ = QLabel("Circuit:")
        self._combo_circuit = QComboBox()
        self._combo_circuit.currentTextChanged.connect(self._on_circuit_changed)
        left_lay.addWidget(lbl_circ)
        left_lay.addWidget(self._combo_circuit)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Session / Rider / Run")
        self._tree.itemClicked.connect(self._on_run_selected)
        left_lay.addWidget(self._tree, stretch=1)

        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet("color: #666; font-size: 10px;")
        left_lay.addWidget(self._lbl_status)

        # ── 右パネル (タブ) ───────────────────────────────
        self._tabs = QTabWidget()
        self._tab_wave    = WaveformView()
        self._tab_problem = ProblemLogTab(db=self._db)
        self._tab_setup   = SetupDecisionTab(db=self._db)
        self._tab_csv     = CsvImportTab(wave_view=self._tab_wave, db=self._db)
        self._tab_wave.set_problem_tab(self._tab_problem)
        self._tabs.addTab(self._tab_wave,    "📊 波形 (Reference)")
        self._tabs.addTab(self._tab_problem, "⚠️  Problem Log")
        self._tabs.addTab(self._tab_setup,   "🔧 Setup Decision")
        self._tabs.addTab(self._tab_csv,     "📂 2D CSV")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

    def _load_circuits(self):
        try:
            circuits = self._db.get_circuits()
        except Exception as e:
            self._lbl_status.setText(f"DB error: {e}")
            circuits = []
        self._combo_circuit.blockSignals(True)
        self._combo_circuit.clear()
        self._combo_circuit.addItems(circuits)
        self._combo_circuit.blockSignals(False)
        if circuits:
            self._on_circuit_changed(circuits[0])

    def _on_circuit_changed(self, circuit: str):
        self._tree.clear()
        try:
            runs = self._db.get_runs(circuit=circuit)
        except Exception as e:
            self._lbl_status.setText(f"DB error: {e}")
            return

        # Group by session
        by_session: dict[str, list[dict]] = {}
        for r in runs:
            s = r.get("session") or "—"
            by_session.setdefault(s, []).append(r)

        for session, run_list in sorted(by_session.items()):
            sess_item = QTreeWidgetItem([session])
            sess_item.setFont(0, QFont("Arial", 10, QFont.Weight.Bold))
            for r in run_list:
                best = r.get("perf_best_lap")
                best_str = format_laptime(float(best)) if best else "—"
                label = f"{r.get('rider','')}  R{r.get('run_no','')}  [{best_str}]"
                run_item = QTreeWidgetItem([label])
                run_item.setData(0, Qt.ItemDataRole.UserRole, r)
                sess_item.addChild(run_item)
            self._tree.addTopLevelItem(sess_item)
        self._tree.expandAll()

    def _on_run_selected(self, item: QTreeWidgetItem, _col: int):
        meta = item.data(0, Qt.ItemDataRole.UserRole)
        if not meta:
            return
        run_id = meta.get("run_id", "")
        self._run_meta = meta
        circuit = self._combo_circuit.currentText()
        self._lbl_status.setText(f"Selected: {run_id}")
        self._tab_wave.set_run(run_id, circuit)
        self._tab_problem.set_run(run_id, meta)
        self._tab_setup.set_run(run_id, meta)
        self._tab_csv.set_run(run_id)


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

    db = WorkbenchDB(DB_PATH)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 10))

    window = MainWindow(db)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
