#!/usr/bin/env python3
"""Checker del design system (U2): cero estilos hardcodeados en ui/.

Falla (exit 1) si encuentra en ui/**.py fuera de la whitelist:
  • la fuente "Segoe UI" (no existe en Linux — usar theme.get_font/FONT_*)
  • colores hex literales ("#RGB", "#RRGGBB", "#RRGGBBAA") — usar tokens
    de ui/theme.py

Whitelist: theme.py (define los tokens) e icons.py (dibuja con PIL).
Corre solo:  python tools/check_ui_tokens.py
y en la suite vía tests/test_ui_tokens.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parents[1] / "ui"
WHITELIST_FILES = {"theme.py", "icons.py"}
HEX_RE = re.compile(r'["\']#[0-9A-Fa-f]{3,8}["\']')


def find_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(UI_DIR.rglob("*.py")):
        if path.name in WHITELIST_FILES:
            continue
        rel = path.relative_to(UI_DIR.parent)
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if '"Segoe UI"' in line or "'Segoe UI'" in line:
                violations.append(
                    f"{rel}:{lineno}: fuente hardcodeada 'Segoe UI' — usa theme.get_font()")
            for match in HEX_RE.finditer(line):
                violations.append(
                    f"{rel}:{lineno}: color hex {match.group()} fuera de theme.py — usa un token")
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print(f"check_ui_tokens: {len(violations)} violaciones del design system:\n")
        for v in violations:
            print(f"  {v}")
        return 1
    print("check_ui_tokens: OK — sin fuentes ni colores hardcodeados en ui/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
