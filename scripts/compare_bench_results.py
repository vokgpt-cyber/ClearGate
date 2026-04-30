"""Compare two or more benchmark JSON outputs side-by-side.

Each input file must be the JSON produced by ``benchmark_v040.py`` (run
once per model with ``--tag <model_name>``).  This script reads them all
and emits a single Markdown comparison report:

    | Metric                | qwen2.5:7b | gemma3:27b | Δ        |
    | Overall precision     |     0.872  |     0.834  | -0.038   |
    | Overall recall        |     0.910  |     0.927  | +0.017   |
    | F1                    |     0.891  |     0.878  | -0.013   |
    | Latency p50 (ms)      |     6 800  |     9 100  | +2 300   |
    | ...                                                          |

    | Document             | Qwen TP/FP/FN | Gemma TP/FP/FN | F1 Δ |
    | 01_NDA               |   28/2/4      |   30/1/2       | +0.07 |
    | ...                                                          |

Usage:
    python compare_bench_results.py \
        --inputs bench-results/bench-20260430-150000-qwen2.5_7b-instruct-q4_K_M.json \
                 bench-results/bench-20260430-153000-gemma3_27b.json \
        --output bench-results/comparison-20260430.md

The first input is treated as the baseline; deltas are relative to it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_run(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _label_for(path: Path, run: dict[str, Any]) -> str:
    """Pick a short, readable label for a benchmark run.

    Prefers any leading-h1 hint embedded by the renderer's tag, falling
    back to the filename stem so the operator at least sees something
    meaningful in the comparison columns.
    """
    # The JSON shape doesn't directly contain the tag, but
    # benchmark_v040.py embeds it in the filename: "bench-<ts>-<tag>.json".
    # We extract the tag back out, since that's the most useful label.
    stem = path.stem  # e.g. "bench-20260430-150000-qwen2.5_7b-instruct-q4_K_M"
    parts = stem.split("-", 3)  # ["bench", "20260430", "150000", "qwen2.5_..."]
    if len(parts) == 4 and parts[3]:
        return parts[3]
    return stem


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _doc_f1(d: dict[str, Any]) -> float:
    tp, fp, fn = d.get("true_positive", 0), d.get("false_positive", 0), d.get("false_negative", 0)
    if tp + fp + fn == 0:
        return 0.0
    p = tp / (tp + fp) if (tp + fp) else 1.0
    r = tp / (tp + fn) if (tp + fn) else 1.0
    return _f1(p, r)


def render_comparison(runs: list[tuple[Path, dict[str, Any]]]) -> str:
    """Build the Markdown comparison.

    Layout:
      1) Run summary card (one line per run)
      2) Aggregate metrics table (precision/recall/F1/latencies)
      3) Per-document table — F1 per model + Δ vs baseline
      4) Per-entity-type breakdown if computable
    """
    labels = [_label_for(p, r) for p, r in runs]
    lines: list[str] = []

    # ---- 1) Header ----
    lines.append("# Cleargate model comparison")
    lines.append("")
    lines.append("| Run | Tag | Run-at | Documents | Total entities |")
    lines.append("|-----|-----|--------|-----------|----------------|")
    for (p, run), label in zip(runs, labels):
        lines.append(
            f"| {p.name} | `{label}` | {run.get('run_at', '?')} "
            f"| {len(run.get('docs', []))} | {run.get('total_entities', 0)} |"
        )
    lines.append("")

    # ---- 2) Aggregate metrics ----
    lines.append("## Overall quality and latency")
    lines.append("")
    header = "| Metric | " + " | ".join(labels)
    if len(labels) >= 2:
        header += " | Δ (last vs first) |"
    else:
        header += " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(labels) + (2 if len(labels) >= 2 else 1)))

    def _row(metric: str, fmt: str, getter):
        vals = [getter(r) for _, r in runs]
        cells = [fmt.format(v) for v in vals]
        row = f"| {metric} | " + " | ".join(cells)
        if len(vals) >= 2:
            delta = vals[-1] - vals[0]
            sign = "+" if delta >= 0 else ""
            row += f" | {sign}{fmt.format(delta).strip()} |"
        else:
            row += " |"
        lines.append(row)

    _row("Precision", "{:.3f}", lambda r: r.get("overall_precision", 0.0))
    _row("Recall",    "{:.3f}", lambda r: r.get("overall_recall", 0.0))
    _row("F1",        "{:.3f}", lambda r: r.get("overall_f1", 0.0))
    _row("Latency p50 (ms)", "{:.0f}", lambda r: r.get("latency_p50_ms", 0.0))
    _row("Latency p95 (ms)", "{:.0f}", lambda r: r.get("latency_p95_ms", 0.0))
    _row("Latency p99 (ms)", "{:.0f}", lambda r: r.get("latency_p99_ms", 0.0))
    lines.append("")

    # ---- 3) Per-document detail ----
    # Build map: doc_name -> per-model {tp, fp, fn, latency, f1}
    doc_names: list[str] = []
    seen: set[str] = set()
    for _, run in runs:
        for d in run.get("docs", []):
            n = d.get("doc_name", "?")
            if n not in seen:
                seen.add(n)
                doc_names.append(n)

    lines.append("## Per-document detail")
    lines.append("")
    head = "| Document | "
    for label in labels:
        head += f"{label} F1 | {label} TP/FP/FN | {label} ms | "
    if len(labels) >= 2:
        head += "F1 Δ |"
    lines.append(head)
    lines.append("|" + "---|" * (1 + 3 * len(labels) + (1 if len(labels) >= 2 else 0)))
    for doc_name in doc_names:
        row = f"| {doc_name} | "
        f1s: list[float] = []
        for _, run in runs:
            d = next((x for x in run.get("docs", []) if x.get("doc_name") == doc_name), None)
            if d is None or d.get("error"):
                row += "— | — | — | "
                f1s.append(float("nan"))
            else:
                f = _doc_f1(d)
                f1s.append(f)
                tp = d.get("true_positive", 0)
                fp = d.get("false_positive", 0)
                fn = d.get("false_negative", 0)
                ms = d.get("latency_ms", 0.0)
                row += f"{f:.2f} | {tp}/{fp}/{fn} | {ms:.0f} | "
        if len(labels) >= 2:
            try:
                delta = f1s[-1] - f1s[0]
                sign = "+" if delta >= 0 else ""
                row += f"{sign}{delta:.2f} |"
            except (TypeError, ValueError):
                row += "— |"
        lines.append(row)
    lines.append("")

    # ---- 4) Notes ----
    lines.append("## Notes")
    lines.append("")
    lines.append("- All metrics are set-based: an entity matches ground truth "
                 "if its (lowercased text, type) tuple is present in the "
                 "ground-truth set. Position offsets are ignored.")
    lines.append("- Δ columns are computed as `last_run − first_run`. Positive "
                 "Δ on F1/precision/recall means the *later* model is better; "
                 "positive Δ on latency means the later model is *slower*.")
    lines.append("- 'TP/FP/FN' counts include the LLM-verifier pass — "
                 "differences between models reflect both layer-4 verify and "
                 "layer-5 scan-for-missed quality.")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", required=True, nargs="+",
                    help="Two or more bench JSON files produced by benchmark_v040.py")
    ap.add_argument("--output", required=True,
                    help="Output Markdown comparison path")
    args = ap.parse_args()

    paths = [Path(p) for p in args.inputs]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: input not found: {p}", file=sys.stderr)
        return 2
    if len(paths) < 2:
        print("WARN: only one input given — comparison will be one column wide.", file=sys.stderr)

    runs = [(p, _load_run(p)) for p in paths]
    text = render_comparison(runs)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"Comparison written to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
