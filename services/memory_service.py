"""
services/memory_service.py — Persistent race engineering knowledge base
========================================================================
Reads/writes race_memory.json.  No Streamlit dependency.

Schema (version 2):
{
  "version": 2,
  "circuit_insights":      {CIRCUIT: {RIDER: ["[date] insight", ...]}},
  "global_insights":       ["[date] insight", ...],
  "setup_learnings":       [{date, circuit, rider, run_no, insight, source}],
  "conversation_summaries":[{date, page, rider, circuit, summary}]
}

# PRODUCT-CANDIDATE: E_AI_CLIENT — This entire module.
"""

import json
from pathlib import Path


_DEFAULT_MEMORY = {
    "version": 2,
    "circuit_insights":       {},
    "global_insights":        [],
    "setup_learnings":        [],
    "conversation_summaries": [],
}


def load_race_memory(primary_path: Path, fallback_path: Path = None) -> dict:
    """Load race memory from disk.

    Tries ``fallback_path`` first (writable /tmp on Streamlit Cloud), then
    ``primary_path`` (repo file).  Returns a default structure if neither exists.

    # PRODUCT-CANDIDATE: E_AI_CLIENT
    """
    paths = [p for p in [fallback_path, primary_path] if p is not None]
    for path in paths:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for k, v in _DEFAULT_MEMORY.items():
                    if k not in data:
                        data[k] = v
                return data
            except Exception:
                pass
    return dict(_DEFAULT_MEMORY)


def save_race_memory(memory: dict, *paths: Path) -> None:
    """Write memory JSON to all supplied paths (ignores write errors silently).

    # PRODUCT-CANDIDATE: E_AI_CLIENT
    """
    blob = json.dumps(memory, ensure_ascii=False, indent=2)
    for path in paths:
        try:
            path.write_text(blob, encoding="utf-8")
        except Exception:
            pass


def build_memory_context(memory: dict, circuit: str, rider: str) -> str:
    """Build a text block summarising past insights for injection into a system prompt.

    Args:
        memory:  Loaded race memory dict.
        circuit: Active circuit filter (or "All").
        rider:   Active rider filter (or "All").

    Returns:
        Multi-line string prefixed with a header, or "" if no relevant data.

    # PRODUCT-CANDIDATE: E_AI_CLIENT
    """
    lines: list = []

    if circuit and circuit != "All":
        c_insights = memory.get("circuit_insights", {}).get(circuit, {})
        riders = [rider] if rider != "All" else list(c_insights.keys())
        for r in riders:
            r_ins = c_insights.get(r, [])
            if r_ins:
                lines.append(f"[{circuit} / {r} — past insights]")
                lines.extend(f"  • {i}" for i in r_ins[-5:])

    g_ins = memory.get("global_insights", [])
    if g_ins:
        lines.append("[Cross-circuit learnings]")
        lines.extend(f"  • {i}" for i in g_ins[-4:])

    summaries = memory.get("conversation_summaries", [])
    recent = [
        s for s in summaries[-6:]
        if circuit == "All" or s.get("circuit") in ("All", circuit)
    ]
    if recent:
        lines.append("[Recent analysis sessions]")
        for s in recent[-3:]:
            lines.append(f"  • [{s['date']}] {s['summary']}")

    if not lines:
        return ""
    return "\n\nPAST KNOWLEDGE BASE (use this to give more contextual answers):\n" + "\n".join(lines)
