"""Compare CLEARGATE entity engines on the golden corpus.

This is an experiment runner, not an application endpoint. It lets us compare
the stable classic pipeline with Gemma entity-map variants on the same safe
synthetic documents before touching the pilot deployment.

Example:
    python scripts/evaluate_entity_engines.py \
        --engines classic_no_llm,gemma_primary,hybrid_consensus \
        --output reports/entity-engine-eval.json
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.entities import DetectedEntity  # noqa: E402
from app.services.ner_pipeline import EntityEngineMode, NERPipeline  # noqa: E402

GOLDEN_DIR = BACKEND / "tests" / "fixtures" / "golden"


@dataclass
class CaseResult:
    case_id: str
    expected_total: int
    expected_found: int
    expected_missing: list[dict[str, str]]
    forbidden_hits: list[dict[str, str]]
    count_violations: list[str]
    detected_count: int
    detected_counts: dict[str, int]
    extra_detected_count: int
    extra_detected: list[str]
    duration_ms: int


@dataclass
class EngineResult:
    engine: str
    cases: list[CaseResult]
    duration_ms: int

    @property
    def expected_total(self) -> int:
        return sum(case.expected_total for case in self.cases)

    @property
    def expected_found(self) -> int:
        return sum(case.expected_found for case in self.cases)

    @property
    def forbidden_hit_count(self) -> int:
        return sum(len(case.forbidden_hits) for case in self.cases)

    @property
    def count_violation_count(self) -> int:
        return sum(len(case.count_violations) for case in self.cases)

    @property
    def extra_detected_count(self) -> int:
        return sum(case.extra_detected_count for case in self.cases)


def _load_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted(GOLDEN_DIR.glob("*.expected.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        spec["_expected_path"] = str(path)
        spec["_text"] = (GOLDEN_DIR / spec["text_file"]).read_text(encoding="utf-8")
        specs.append(spec)
    return specs


def _entity_key(entity: DetectedEntity) -> tuple[str, str]:
    return (entity.text, entity.entity_type)


def _expected_key(item: dict[str, str]) -> tuple[str, str]:
    return (item["text"], item["entity_type"])


def _format_entity(entity: DetectedEntity) -> str:
    return f"{entity.entity_type}:{entity.text}@{entity.start}-{entity.end}"


def _case_result(spec: dict[str, Any], entities: list[DetectedEntity], duration_ms: int) -> CaseResult:
    entity_keys = {_entity_key(entity) for entity in entities}
    expected = list(spec.get("expected_entities", []))
    forbidden = list(spec.get("forbidden_entities", []))

    missing = [
        item
        for item in expected
        if _expected_key(item) not in entity_keys
    ]
    forbidden_hits = [
        item
        for item in forbidden
        if _expected_key(item) in entity_keys
    ]

    counts = Counter(entity.entity_type for entity in entities)
    violations: list[str] = []
    for entity_type, bounds in spec.get("expected_type_counts", {}).items():
        actual = counts[entity_type]
        if "min" in bounds and actual < bounds["min"]:
            violations.append(f"{entity_type}={actual} < min {bounds['min']}")
        if "max" in bounds and actual > bounds["max"]:
            violations.append(f"{entity_type}={actual} > max {bounds['max']}")

    expected_keys = {_expected_key(item) for item in expected}
    forbidden_keys = {_expected_key(item) for item in forbidden}
    extra_all = [
        _format_entity(entity)
        for entity in entities
        if _entity_key(entity) not in expected_keys and _entity_key(entity) not in forbidden_keys
    ]

    return CaseResult(
        case_id=spec["id"],
        expected_total=len(expected),
        expected_found=len(expected) - len(missing),
        expected_missing=missing,
        forbidden_hits=forbidden_hits,
        count_violations=violations,
        detected_count=len(entities),
        detected_counts=dict(counts),
        extra_detected_count=len(extra_all),
        extra_detected=extra_all[:40],
        duration_ms=duration_ms,
    )


def _build_pipeline(
    engine: str,
    *,
    spacy_model: str,
    gliner_model: str | None,
    ollama_model: str,
    ollama_host: str,
) -> NERPipeline:
    if engine == "classic_no_llm":
        return NERPipeline(
            spacy_model=spacy_model,
            gliner_model=gliner_model,
            enable_llm_layer=False,
        )

    mode: EntityEngineMode
    if engine == "classic_llm":
        mode = "classic"
    elif engine in {"gemma_shadow", "gemma_primary", "hybrid_consensus"}:
        mode = engine  # type: ignore[assignment]
    else:
        raise ValueError(f"Unknown engine: {engine}")

    return NERPipeline(
        spacy_model=spacy_model,
        gliner_model=gliner_model,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
        enable_llm_layer=True,
        entity_engine=mode,
    )


async def _run_engine(
    engine: str,
    specs: list[dict[str, Any]],
    *,
    spacy_model: str,
    gliner_model: str | None,
    ollama_model: str,
    ollama_host: str,
) -> EngineResult:
    pipeline = _build_pipeline(
        engine,
        spacy_model=spacy_model,
        gliner_model=gliner_model,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
    )

    started = time.perf_counter()
    cases: list[CaseResult] = []
    for spec in specs:
        case_started = time.perf_counter()
        entities = await pipeline.analyze(spec["_text"])
        case_ms = int((time.perf_counter() - case_started) * 1000)
        cases.append(_case_result(spec, entities, case_ms))

    return EngineResult(
        engine=engine,
        cases=cases,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _to_json_payload(results: list[EngineResult]) -> dict[str, Any]:
    engines: list[dict[str, Any]] = []
    for result in results:
        expected_total = result.expected_total
        recall = result.expected_found / expected_total if expected_total else 1.0
        engines.append(
            {
                "engine": result.engine,
                "expected_found": result.expected_found,
                "expected_total": expected_total,
                "expected_recall": round(recall, 4),
                "forbidden_hit_count": result.forbidden_hit_count,
                "count_violation_count": result.count_violation_count,
                "extra_detected_count": result.extra_detected_count,
                "duration_ms": result.duration_ms,
                "cases": [asdict(case) for case in result.cases],
            }
        )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "golden_dir": str(GOLDEN_DIR),
        "engines": engines,
    }


def _write_markdown(payload: dict[str, Any], output: Path) -> Path:
    md_path = output.with_suffix(".md")
    lines = [
        "# CLEARGATE Entity Engine Evaluation",
        "",
        f"Created: `{payload['created_at']}`",
        "",
        "| Engine | Expected recall | Forbidden hits | Extra detections | Count violations | Duration |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for engine in payload["engines"]:
        lines.append(
            "| {engine} | {found}/{total} ({recall:.1%}) | {forbidden} | {extra} | {violations} | {duration} ms |".format(
                engine=engine["engine"],
                found=engine["expected_found"],
                total=engine["expected_total"],
                recall=engine["expected_recall"],
                forbidden=engine["forbidden_hit_count"],
                extra=engine["extra_detected_count"],
                violations=engine["count_violation_count"],
                duration=engine["duration_ms"],
            )
        )

    lines.append("")
    lines.append("## Problem Cases")
    for engine in payload["engines"]:
        for case in engine["cases"]:
            if (
                not case["expected_missing"]
                and not case["forbidden_hits"]
                and not case["count_violations"]
                and not case["extra_detected_count"]
            ):
                continue
            lines.append("")
            lines.append(f"### {engine['engine']} / {case['case_id']}")
            if case["expected_missing"]:
                lines.append(f"- Missing: `{case['expected_missing']}`")
            if case["forbidden_hits"]:
                lines.append(f"- Forbidden hits: `{case['forbidden_hits']}`")
            if case["count_violations"]:
                lines.append(f"- Count violations: `{case['count_violations']}`")
            if case["extra_detected_count"]:
                lines.append(
                    f"- Extra detections ({case['extra_detected_count']}): `{case['extra_detected'][:10]}`"
                )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


async def _main_async(args: argparse.Namespace) -> int:
    specs = _load_specs()
    engines = [item.strip() for item in args.engines.split(",") if item.strip()]
    gliner_model = None if args.gliner_model.lower() in {"", "none", "off", "false"} else args.gliner_model
    results: list[EngineResult] = []

    for engine in engines:
        print(f"Running {engine} on {len(specs)} golden cases...", flush=True)
        results.append(
            await _run_engine(
                engine,
                specs,
                spacy_model=args.spacy_model,
                gliner_model=gliner_model,
                ollama_model=args.ollama_model,
                ollama_host=args.ollama_host,
            )
        )

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = _to_json_payload(results)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = _write_markdown(payload, output)

    print(f"Wrote {output}")
    print(f"Wrote {md_path}")

    if args.fail_on_regression:
        for engine in payload["engines"]:
            if engine["expected_found"] < engine["expected_total"]:
                return 2
            if engine["forbidden_hit_count"] or engine["count_violation_count"] or engine["extra_detected_count"]:
                return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engines",
        default="classic_no_llm,classic_llm,gemma_primary,hybrid_consensus",
        help="Comma-separated engines: classic_no_llm, classic_llm, gemma_shadow, gemma_primary, hybrid_consensus.",
    )
    parser.add_argument("--spacy-model", default="ru_core_news_sm")
    parser.add_argument("--gliner-model", default="none")
    parser.add_argument("--ollama-model", default="gemma4:26b")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--output", default="reports/entity-engine-eval.json")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
