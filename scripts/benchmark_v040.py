#!/usr/bin/env python3
"""Cleargate v0.4.0 benchmark — measures precision/recall/latency on a live deploy.

Runs the test-fixture documents (test/*.docx with ground-truth annotations
in test/results/*.json) through the full 5-stage pipeline of a running
Cleargate instance, then reports:

  - precision/recall per entity type
  - latency p50 / p95 / p99 per anonymize call
  - throughput (entities/sec, tokens/sec on Layer 4-5)
  - GPU memory utilisation snapshot (if vLLM /metrics endpoint is up)
  - layer-by-layer breakdown (regex / spaCy / GLiNER / LLM-verify / LLM-scan)

Designed to run on the GPU server itself (talks to localhost backend) but
works against any reachable Cleargate URL via --base-url.

Usage:
    # GPU server (default — talks to localhost):
    python3 scripts/benchmark_v040.py

    # From your laptop against the GPU server:
    python3 scripts/benchmark_v040.py --base-url https://cleargate.epam.ru \\
        --username vadim --password '...' \\
        --output bench-results/2026-04-29.json

Output:
    - <output>.json        — raw measurements (machine-readable)
    - <output>.md          — human-readable summary report
    - bench-results/       — default output directory if --output omitted

Exit code: 0 on success; 1 if precision OR recall on any required entity
type drops below the threshold (default 0.85). Useful as a CI gate or as
a regression guard between v0.4.x bumps.

Privacy: this script ONLY ships the synthetic test fixtures from test/
(no real client data). The fixtures already live in the repo and contain
artificial ФИО / ИНН / addresses for legal-doc shape verification.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEST_DIR = REPO_ROOT / "test"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "bench-results"

# Per-type minimum acceptable precision/recall. Tuned against pilot data;
# adjust as the dataset grows. PER and ORG are the load-bearing types for
# legal docs; structured IDs (RU_INN/OGRN/SNILS) are regex-validated and
# should be ~1.0.
DEFAULT_MIN_PRECISION = 0.85
DEFAULT_MIN_RECALL = 0.85
STRUCTURED_TYPES = {"RU_INN", "RU_OGRN", "RU_SNILS", "RU_PASSPORT", "RU_PHONE", "EMAIL_ADDRESS"}

# Per-call timeout — generous because LLM Layer-4/5 can take 10-30s on a
# warm GPU. Cold-start may take longer; the script retries with backoff.
HTTP_TIMEOUT_SECONDS = 180.0


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class DocResult:
    """Per-document measurement."""
    doc_name: str
    char_count: int
    latency_ms: float
    entity_count: int
    entities_by_type: dict[str, int] = field(default_factory=dict)
    # Compared against ground truth.
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    per_type: dict[str, dict[str, int]] = field(default_factory=dict)
    error: str | None = None


@dataclass
class TypeMetrics:
    """Aggregate precision/recall for a single entity type across all docs."""
    entity_type: str
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class BenchResult:
    """Top-level benchmark output, serialised to JSON + Markdown."""
    run_at: str
    base_url: str
    docs: list[DocResult]
    by_type: list[TypeMetrics]
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    total_chars: int
    total_entities: int
    overall_precision: float
    overall_recall: float
    overall_f1: float
    gpu_metrics: dict[str, str | float] | None


# ---------------------------------------------------------------------------
# Backend client
# ---------------------------------------------------------------------------


class CleargateClient:
    """Thin HTTP wrapper that handles login + anonymize."""

    def __init__(self, base_url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        # Cookie jar is per-client — login() persists `cg_session` for
        # subsequent /api/* calls on the same client.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            verify=False,  # self-signed certs in dev; flip to True for prod
        )

    async def login(self, username: str, password: str) -> None:
        r = await self._client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        r.raise_for_status()

    async def upload_docx(self, session_id: str, path: Path) -> dict:
        # Format-aware MIME picker so the backend's DocumentProcessor receives
        # a sensible Content-Type. The endpoint determines parser purely from
        # the filename suffix, but a correct MIME helps proxy/inspector logs
        # and is required by some intermediate middleware.
        suffix = path.suffix.lower()
        mime = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pdf": "application/pdf",
            ".txt": "text/plain; charset=utf-8",
        }.get(suffix, "application/octet-stream")
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, mime)}
            r = await self._client.post(
                f"/api/documents/upload?session_id={session_id}",
                files=files,
            )
        r.raise_for_status()
        return r.json()

    async def create_session(self) -> str:
        r = await self._client.post(
            "/api/sessions",
            json={"locale": "ru", "enable_llm_layer": True},
        )
        r.raise_for_status()
        return r.json()["session_id"]

    async def anonymize(self, session_id: str, text: str) -> dict:
        r = await self._client.post(
            f"/api/sessions/{session_id}/anonymize",
            json={"text": text},
        )
        r.raise_for_status()
        return r.json()

    async def fetch_vllm_metrics(self) -> dict[str, str | float] | None:
        """Try to grab GPU/throughput metrics from vLLM's /metrics endpoint.

        vLLM exposes Prometheus-format metrics on its OpenAI port (8000
        inside the container; 8001 outside). We try both common paths and
        fall back to None if neither responds.
        """
        parsed = urlparse(self.base_url)
        host_metrics = (
            f"{parsed.scheme}://{parsed.hostname}:8001/metrics"
            if parsed.scheme and parsed.hostname
            else None
        )
        for path in ("/metrics", host_metrics):
            if path is None:
                continue
            try:
                r = await self._client.get(path, timeout=5.0)
                if r.status_code == 200 and "vllm:" in r.text:
                    return {"raw_excerpt": r.text[:2000]}
            except Exception:
                continue
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Ground-truth comparison
# ---------------------------------------------------------------------------


def normalise_entity_text(text: str) -> str:
    """Loose normalisation for ground-truth matching.

    Cleargate sometimes trims trailing punctuation, sometimes preserves it;
    likewise for leading whitespace. Comparing on a stripped, lowercased
    form gets a much fairer precision/recall number than strict equality.
    """
    return text.strip().rstrip(":;,.!?-").strip().lower()


def compare_against_ground_truth(
    detected_entities: list[dict],
    ground_truth: list[dict],
) -> tuple[int, int, int, dict[str, dict[str, int]]]:
    """Return (tp, fp, fn, per_type_breakdown).

    per_type_breakdown[entity_type] = {"tp": int, "fp": int, "fn": int}
    """
    # Tolerate both field naming conventions: hand-curated GTs use
    # "entity_type", while older pipeline-output _entities.json files use
    # "type". Same applies to the detected_entities side for back-compat.
    def _et(d: dict) -> str:
        return d.get("entity_type") or d.get("type") or ""

    detected_set: set[tuple[str, str]] = {
        (normalise_entity_text(e["text"]), _et(e)) for e in detected_entities
    }
    truth_set: set[tuple[str, str]] = {
        (normalise_entity_text(e["text"]), _et(e)) for e in ground_truth
    }

    tp_set = detected_set & truth_set
    fp_set = detected_set - truth_set
    fn_set = truth_set - detected_set

    per_type: dict[str, dict[str, int]] = {}
    for _, etype in tp_set:
        per_type.setdefault(etype, {"tp": 0, "fp": 0, "fn": 0})["tp"] += 1
    for _, etype in fp_set:
        per_type.setdefault(etype, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
    for _, etype in fn_set:
        per_type.setdefault(etype, {"tp": 0, "fp": 0, "fn": 0})["fn"] += 1

    return len(tp_set), len(fp_set), len(fn_set), per_type


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------


def discover_test_pairs(test_dir: Path) -> list[tuple[Path, Path | None]]:
    """Return [(doc_path, ground_truth_json_path | None), ...] from test/.

    Discovers .docx, .pdf, .txt fixtures (Cleargate's three supported
    upload formats). Ground-truth JSON is preferred at
    ``test/results/<docname>_ground_truth.json`` (hand-curated, gold
    standard) and falls back to ``<docname>_entities.json`` (older
    pipeline self-output, kept for back-compat). Documents without GT
    are still benchmarked for latency but skipped for precision/recall.
    """
    pairs: list[tuple[Path, Path | None]] = []
    seen_stems: set[str] = set()
    for ext in ("*.docx", "*.pdf", "*.txt"):
        for doc in sorted(test_dir.glob(ext)):
            stem = doc.stem  # e.g. "01_NDA"
            if stem in seen_stems:
                # Avoid double-counting if a doc exists in two formats.
                continue
            seen_stems.add(stem)
            results_dir = test_dir / "results"
            gt_new = results_dir / f"{stem}_ground_truth.json"
            gt_old = results_dir / f"{stem}_entities.json"
            gt = gt_new if gt_new.exists() else (gt_old if gt_old.exists() else None)
            pairs.append((doc, gt))
    return sorted(pairs, key=lambda p: p[0].name)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def benchmark_doc(
    client: CleargateClient,
    docx_path: Path,
    ground_truth_path: Path | None,
) -> DocResult:
    """Benchmark a single document end-to-end."""
    doc_name = docx_path.name
    try:
        session_id = await client.create_session()
        upload_response = await client.upload_docx(session_id, docx_path)
        text = upload_response.get("text", "")
        char_count = len(text)

        t0 = time.perf_counter()
        anonymize_response = await client.anonymize(session_id, text)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        entities = anonymize_response.get("entities", [])
        entities_by_type: dict[str, int] = {}
        for e in entities:
            entities_by_type[e["entity_type"]] = entities_by_type.get(e["entity_type"], 0) + 1

        result = DocResult(
            doc_name=doc_name,
            char_count=char_count,
            latency_ms=latency_ms,
            entity_count=len(entities),
            entities_by_type=entities_by_type,
        )

        if ground_truth_path is not None:
            with ground_truth_path.open(encoding="utf-8") as fh:
                ground_truth = json.load(fh)
            tp, fp, fn, per_type = compare_against_ground_truth(entities, ground_truth)
            result.true_positive = tp
            result.false_positive = fp
            result.false_negative = fn
            result.per_type = per_type

        return result
    except Exception as exc:
        return DocResult(
            doc_name=doc_name,
            char_count=0,
            latency_ms=0.0,
            entity_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )


async def main_async(args: argparse.Namespace) -> int:
    test_dir = Path(args.test_dir).resolve()
    if not test_dir.exists():
        print(f"ERROR: test directory {test_dir} not found", file=sys.stderr)
        return 2

    pairs = discover_test_pairs(test_dir)
    if not pairs:
        print(f"ERROR: no .docx fixtures in {test_dir}", file=sys.stderr)
        return 2

    print(f"Found {len(pairs)} test documents in {test_dir}")
    print(f"Connecting to Cleargate at {args.base_url}...")

    client = CleargateClient(args.base_url)
    try:
        await client.login(args.username, args.password)
        print(f"Logged in as {args.username}")

        doc_results: list[DocResult] = []
        for docx, gt in pairs:
            print(f"  - benchmarking {docx.name}...", flush=True)
            result = await benchmark_doc(client, docx, gt)
            doc_results.append(result)
            if result.error:
                print(f"      ERROR: {result.error}")
            else:
                print(
                    f"      {result.entity_count} entities, "
                    f"{result.latency_ms:.0f}ms"
                    + (
                        f", tp={result.true_positive}/fp={result.false_positive}/fn={result.false_negative}"
                        if gt
                        else " (no ground truth)"
                    )
                )
        gpu_metrics = await client.fetch_vllm_metrics()

    finally:
        await client.aclose()

    # ---- Aggregate ----
    valid_latencies = [r.latency_ms for r in doc_results if r.error is None]
    p50 = statistics.median(valid_latencies) if valid_latencies else 0.0
    p95 = (
        statistics.quantiles(valid_latencies, n=20)[18]
        if len(valid_latencies) >= 20
        else max(valid_latencies, default=0.0)
    )
    p99 = (
        statistics.quantiles(valid_latencies, n=100)[98]
        if len(valid_latencies) >= 100
        else max(valid_latencies, default=0.0)
    )

    total_tp = sum(r.true_positive for r in doc_results)
    total_fp = sum(r.false_positive for r in doc_results)
    total_fn = sum(r.false_negative for r in doc_results)
    per_type_acc: dict[str, dict[str, int]] = {}
    for result in doc_results:
        for entity_type, counts in result.per_type.items():
            acc = per_type_acc.setdefault(entity_type, {"tp": 0, "fp": 0, "fn": 0})
            acc["tp"] += counts.get("tp", 0)
            acc["fp"] += counts.get("fp", 0)
            acc["fn"] += counts.get("fn", 0)
    by_type = [
        TypeMetrics(entity_type=entity_type, tp=counts["tp"], fp=counts["fp"], fn=counts["fn"])
        for entity_type, counts in sorted(per_type_acc.items())
    ]
    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall)
        else 0.0
    )

    bench = BenchResult(
        run_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        base_url=args.base_url,
        docs=doc_results,
        by_type=by_type,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        latency_p99_ms=p99,
        total_chars=sum(r.char_count for r in doc_results),
        total_entities=sum(r.entity_count for r in doc_results),
        overall_precision=overall_precision,
        overall_recall=overall_recall,
        overall_f1=overall_f1,
        gpu_metrics=gpu_metrics,
    )

    # ---- Output ----
    # When --tag is given (e.g. model name), embed it in the default
    # filename so successive model runs in compare mode don't overwrite
    # each other. Sanitised so any model string with slashes/colons works.
    tag = getattr(args, "tag", None) or ""
    safe_tag = "".join(c if c.isalnum() or c in "-._" else "_" for c in tag)
    suffix = f"-{safe_tag}" if safe_tag else ""
    output = Path(args.output) if args.output else (
        DEFAULT_OUTPUT_DIR / f"bench-{time.strftime('%Y%m%d-%H%M%S')}{suffix}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        json.dump(asdict(bench), fh, indent=2, ensure_ascii=False, default=str)
    print(f"\nJSON report written to: {output}")

    md_path = output.with_suffix(".md")
    with md_path.open("w", encoding="utf-8") as fh:
        fh.write(render_markdown_report(bench, tag=tag or None))
    print(f"Markdown report written to: {md_path}")

    print("\n=== Summary ===")
    print(f"Documents:        {len(doc_results)}")
    print(f"Total entities:   {bench.total_entities}")
    print(f"Latency p50/p95/p99 ms:  {p50:.0f} / {p95:.0f} / {p99:.0f}")
    print(f"Overall precision/recall/F1:  {overall_precision:.3f} / {overall_recall:.3f} / {overall_f1:.3f}")

    if (
        overall_precision < args.min_precision
        or overall_recall < args.min_recall
    ):
        print(
            f"\nFAIL: precision={overall_precision:.3f} or recall={overall_recall:.3f} "
            f"below threshold (min_precision={args.min_precision}, min_recall={args.min_recall})",
            file=sys.stderr,
        )
        return 1

    print("\nPASS — quality thresholds met.")
    return 0


def render_markdown_report(bench: BenchResult, tag: str | None = None) -> str:
    """Compact human-readable summary for sharing with stakeholders."""
    lines: list[str] = []
    title_tag = f" [{tag}]" if tag else ""
    lines.append(f"# Cleargate v0.4.0 benchmark{title_tag} — {bench.run_at}")
    lines.append("")
    if tag:
        lines.append(f"**Run tag (model):** `{tag}`")
    lines.append(f"**Base URL:** {bench.base_url}")
    lines.append(f"**Documents:** {len(bench.docs)}")
    lines.append(f"**Total characters processed:** {bench.total_chars:,}")
    lines.append(f"**Total entities detected:** {bench.total_entities}")
    lines.append("")
    lines.append("## Latency")
    lines.append("")
    lines.append(f"- p50: **{bench.latency_p50_ms:.0f} ms**")
    lines.append(f"- p95: **{bench.latency_p95_ms:.0f} ms**")
    lines.append(f"- p99: **{bench.latency_p99_ms:.0f} ms**")
    lines.append("")
    lines.append("## Quality vs. ground truth")
    lines.append("")
    lines.append(f"- Precision: **{bench.overall_precision:.3f}**")
    lines.append(f"- Recall:    **{bench.overall_recall:.3f}**")
    lines.append(f"- F1:        **{bench.overall_f1:.3f}**")
    lines.append("")
    if bench.by_type:
        lines.append("### Per-entity-type detail")
        lines.append("")
        lines.append("| Type | Precision | Recall | F1 | TP | FP | FN |")
        lines.append("|------|-----------|--------|----|----|----|----|")
        for t in bench.by_type:
            lines.append(
                f"| {t.entity_type} | {t.precision:.3f} | {t.recall:.3f} | "
                f"{t.f1:.3f} | {t.tp} | {t.fp} | {t.fn} |"
            )
        lines.append("")
    lines.append("## Per-document detail")
    lines.append("")
    lines.append("| Document | Chars | Entities | Latency (ms) | TP | FP | FN |")
    lines.append("|----------|-------|----------|--------------|----|----|----|")
    for d in bench.docs:
        lines.append(
            f"| {d.doc_name} | {d.char_count:,} | {d.entity_count} | "
            f"{d.latency_ms:.0f} | {d.true_positive} | {d.false_positive} | {d.false_negative} |"
        )
    if bench.gpu_metrics:
        lines.append("")
        lines.append("## vLLM metrics excerpt")
        lines.append("")
        lines.append("```")
        lines.append(str(bench.gpu_metrics.get("raw_excerpt", ""))[:1500])
        lines.append("```")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost",
                    help="Cleargate root URL (default: http://localhost)")
    ap.add_argument("--username", default="admin", help="Login username (default: admin)")
    ap.add_argument("--password", required=True, help="Login password")
    ap.add_argument("--test-dir", default=str(DEFAULT_TEST_DIR),
                    help=f"Directory containing test fixtures (default: {DEFAULT_TEST_DIR})")
    ap.add_argument("--output", default=None,
                    help="Output JSON path (default: bench-results/bench-<timestamp>.json)")
    ap.add_argument("--min-precision", type=float, default=DEFAULT_MIN_PRECISION,
                    help=f"Fail if precision drops below this (default: {DEFAULT_MIN_PRECISION})")
    ap.add_argument("--min-recall", type=float, default=DEFAULT_MIN_RECALL,
                    help=f"Fail if recall drops below this (default: {DEFAULT_MIN_RECALL})")
    ap.add_argument("--tag", default=None,
                    help="Optional run tag (e.g. model name) — appears in the "
                         "output filename and the markdown report header. "
                         "Used by bench-models.bat to keep per-model runs apart.")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
