"""Local LLM verification layer for the NER pipeline.

Uses Ollama (Qwen 2.5) to verify entity candidates from layers 1-2,
resolve coreferences, and find entities missed by regex and NER.
This is Layer 3 — the slowest but most context-aware layer.
"""

from __future__ import annotations

import asyncio
import json
import os

import structlog

from app.models.entities import DetectedEntity

logger = structlog.get_logger(__name__)

# Cold-start retry knobs — on `docker compose up` the backend often races
# ollama. Rather than fail the very first verification call, wait for the
# server to come up. Only the first attempt retries; steady-state latency
# is unaffected.
_FIRST_CALL_RETRIES = 6
_FIRST_CALL_BACKOFF_SECONDS = 5.0

VERIFICATION_PROMPT = """Ты эксперт по обработке юридических текстов на русском языке. Тебе дан текст и список кандидатов в чувствительные сущности, найденных автоматически.

Твоя задача:
1. Проверь каждого кандидата — действительно ли это чувствительная сущность (ФИО, организация, адрес, ИНН, и т.п.)
2. Найди упущенные сущности (кореференции типа "он", "указанная организация", упоминания через должность)
3. Удали ложные срабатывания

Верни строго JSON:
{{
  "verified": [
    {{"text": "...", "entity_type": "PER|ORG|LOC|ADDR|MON|DATE|POSITION", "start": N, "end": N, "score": 0.0-1.0}}
  ],
  "added": [
    {{"text": "...", "entity_type": "...", "start": N, "end": N, "score": 0.0-1.0}}
  ],
  "removed_indices": []
}}

ТЕКСТ:
{text}

КАНДИДАТЫ:
{candidates}"""

_MAX_TEXT_LEN = 8000  # Cap text length for 7B model context window


class LocalLLMVerifier:
    """Verifies and refines NER results using a local LLM via Ollama.

    Args:
        model: Ollama model name (e.g., "qwen2.5:7b-instruct-q4_K_M").
        host: Explicit Ollama HTTP host (e.g., "http://ollama:11434").
            If not given, falls back to the OLLAMA_HOST env var, then to
            http://localhost:11434.

    The verifier is optional — the pipeline works without it (degraded mode).
    """

    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct-q4_K_M",
        host: str | None = None,
    ) -> None:
        self.model = model
        # Resolve and freeze the host once. We pass it explicitly to the
        # AsyncClient (instead of relying on the OLLAMA_HOST env var) so
        # that the value we *log* matches the value the client actually
        # talks to — IT can compare the two during diagnosis.
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self._client: object | None = None
        self._first_call_done = False
        logger.info("llm_verifier.configured", host=self.host, model=self.model)

    def _get_client(self) -> object:
        """Lazy-init Ollama async client."""
        if self._client is None:
            import ollama

            self._client = ollama.AsyncClient(host=self.host)
        return self._client

    async def verify_and_refine(
        self,
        text: str,
        candidates: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Send candidates to local LLM for verification.

        Args:
            text: Original text.
            candidates: Entity candidates from layers 1-2.

        Returns:
            Refined list of entities (verified + newly found by LLM).
            On error, returns the original candidates unchanged.
        """
        if not candidates:
            return candidates

        candidate_data = [
            {"text": c.text, "entity_type": c.entity_type, "start": c.start, "end": c.end, "score": c.score}
            for c in candidates
        ]

        prompt = VERIFICATION_PROMPT.format(
            text=text[:_MAX_TEXT_LEN],
            candidates=json.dumps(candidate_data, ensure_ascii=False, indent=2),
        )

        try:
            response = await self._generate_with_retry(prompt)

            result = json.loads(response["response"])
            verified = self._parse_llm_results(result, candidates)

            logger.info(
                "llm_verifier.done",
                original_count=len(candidates),
                verified_count=len(verified),
            )
            return verified

        except Exception:
            logger.warning(
                "llm_verifier.failed",
                candidate_count=len(candidates),
                host=self.host,
                model=self.model,
                exc_info=True,
            )
            return candidates  # graceful degradation

    async def _generate_with_retry(self, prompt: str) -> dict:
        """Call ollama.generate(), retrying the very first call.

        Subsequent calls go through immediately. Only the cold-start case
        (where ollama is still warming up after `docker compose up`) gets
        the retry treatment, so steady-state latency is unaffected.
        """
        client = self._get_client()
        attempts = 1 if self._first_call_done else _FIRST_CALL_RETRIES
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await client.generate(  # type: ignore[union-attr]
                    model=self.model,
                    prompt=prompt,
                    format="json",
                    options={"temperature": 0.0},
                )
                self._first_call_done = True
                return response
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "llm_verifier.retry",
                    attempt=attempt,
                    of=attempts,
                    host=self.host,
                    model=self.model,
                    error=str(exc),
                )
                await asyncio.sleep(_FIRST_CALL_BACKOFF_SECONDS)
        assert last_exc is not None
        raise last_exc

    def _parse_llm_results(
        self,
        result: dict,
        original_candidates: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Parse LLM JSON response into DetectedEntity list."""
        entities: list[DetectedEntity] = []

        # Verified entities from LLM
        for item in result.get("verified", []):
            try:
                entities.append(
                    DetectedEntity(
                        text=item["text"],
                        entity_type=item.get("entity_type", "UNKNOWN"),
                        start=item.get("start", 0),
                        end=item.get("end", 0),
                        score=min(float(item.get("score", 0.8)), 1.0),
                        source_layer="llm",
                    )
                )
            except (KeyError, ValueError):
                continue

        # Newly added entities from LLM
        for item in result.get("added", []):
            try:
                entities.append(
                    DetectedEntity(
                        text=item["text"],
                        entity_type=item.get("entity_type", "UNKNOWN"),
                        start=item.get("start", 0),
                        end=item.get("end", 0),
                        score=min(float(item.get("score", 0.7)), 1.0),
                        source_layer="llm",
                    )
                )
            except (KeyError, ValueError):
                continue

        # If LLM returned nothing useful, keep originals
        if not entities:
            return original_candidates

        return entities
