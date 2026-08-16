#!/usr/bin/env python3
"""Compile Python source in memory without creating __pycache__ artifacts."""

from __future__ import annotations

import sys
from pathlib import Path


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: check_syntax.py FILE...", file=sys.stderr)
        return 2
    for raw in paths:
        path = Path(raw)
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
