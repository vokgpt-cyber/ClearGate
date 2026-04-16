"""
CLEARGATE truncation scan.

Walks backend/ and frontend/src and flags files that look silently
truncated (incomplete Python AST, unbalanced TS/TSX braces, missing
trailing newline + ending mid-word).

Run from repo root:
    .\backend\.venv\Scripts\python.exe scripts\truncation_scan.py
"""

from __future__ import annotations

import ast
from pathlib import Path


SKIP_PARTS = {".venv", "__pycache__", "node_modules", ".next", ".git", "dist", "build"}


def is_skipped(p: Path) -> bool:
    return any(part in SKIP_PARTS for part in p.parts)


def scan_python(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    count = 0
    for p in root.rglob("*.py"):
        if is_skipped(p):
            continue
        count += 1
        try:
            src = p.read_text(encoding="utf-8")
        except Exception as e:
            out.append((str(p), f"read error: {e!r}"))
            continue
        try:
            ast.parse(src)
        except SyntaxError as e:
            out.append((str(p), f"SyntaxError line {e.lineno}: {e.msg}"))
    print(f"[python] checked {count} files, {len(out)} broken")
    return out


def balanced(src: str, pair: tuple[str, str]) -> int:
    """Return final bracket depth; non-zero means unbalanced."""
    depth = 0
    in_s = in_d = in_b = False
    in_line = in_block = False
    i = 0
    o, c = pair
    while i < len(src):
        ch = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_line:
            if ch == "\n":
                in_line = False
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_s:
            if ch == "\\":
                i += 1
            elif ch == "'":
                in_s = False
        elif in_d:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_d = False
        elif in_b:
            if ch == "\\":
                i += 1
            elif ch == "`":
                in_b = False
        else:
            if ch == "/" and nxt == "/":
                in_line = True
            elif ch == "/" and nxt == "*":
                in_block = True
                i += 1
            elif ch == "'":
                in_s = True
            elif ch == '"':
                in_d = True
            elif ch == "`":
                in_b = True
            elif ch == o:
                depth += 1
            elif ch == c:
                depth -= 1
        i += 1
    return depth


def scan_ts(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    count = 0
    for ext in ("ts", "tsx", "js", "jsx", "mjs", "cjs"):
        for p in root.rglob(f"*.{ext}"):
            if is_skipped(p):
                continue
            count += 1
            try:
                src = p.read_text(encoding="utf-8")
            except Exception as e:
                out.append((str(p), f"read error: {e!r}"))
                continue
            for pair in [("{", "}"), ("(", ")"), ("[", "]")]:
                d = balanced(src, pair)
                if d != 0:
                    out.append((str(p), f"unbalanced {pair[0]}{pair[1]}: depth={d}"))
                    break
    print(f"[ts/js]  checked {count} files, {len(out)} broken")
    return out


def scan_text(root: Path) -> list[tuple[str, str]]:
    """Flag plain text files ending mid-word (no trailing newline + alphanumeric last char)."""
    out: list[tuple[str, str]] = []
    count = 0
    for ext in ("md", "toml", "yml", "yaml", "json", "css"):
        for p in root.rglob(f"*.{ext}"):
            if is_skipped(p):
                continue
            count += 1
            try:
                src = p.read_text(encoding="utf-8")
            except Exception:
                continue
            if not src:
                continue
            if not src.endswith("\n"):
                last = src[-1]
                if last.isalnum() or last in ":,-":
                    out.append((str(p), f"ends mid-content with {last!r}"))
    print(f"[text]   checked {count} files, {len(out)} suspicious")
    return out


def main() -> int:
    root = Path(".")
    results: list[tuple[str, str]] = []
    results += scan_python(root / "backend")
    results += scan_ts(root / "frontend" / "src")
    results += scan_text(root)

    print()
    if not results:
        print("CLEAN — no broken files detected.")
        return 0

    print(f"FOUND {len(results)} suspicious file(s):")
    for path, reason in results:
        print(f"  {path}")
        print(f"    -> {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
