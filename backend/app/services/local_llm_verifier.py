"""Local LLM verification layer for the NER pipeline (v0.4.0).

Uses OpenAI-compatible async client (works with Ollama and vLLM) for:
- Layer 4: verify entity candidates from layers 1-3
- Layer 5: find entities missed by regex and NER (via new find_missed_entities method)

Supports both Ollama and vLLM backends through the OpenAI SDK abstraction.
This is Layers 4-5 — the slowest but most context-aware layers.
"""

from __future__ import annotations

import asyncio
import json
import os

import structlog

from app.models.entities import KNOWN_ENTITY_TYPES, DetectedEntity

logger = structlog.get_logger(__name__)

# Cold-start retry knobs — on `docker compose up` the backend often races
# ollama/vLLM. Rather than fail the very first verification call, wait for the
# server to come up. Only the first attempt retries; steady-state latency
# is unaffected.
_FIRST_CALL_RETRIES = 6
_FIRST_CALL_BACKOFF_SECONDS = 5.0
_LLM_CALL_TIMEOUT_SECONDS = 90

# Static prompt prefix for KV cache hits (Layer 4)
_PROMPT_PREFIX = """Ты эксперт по обработке юридических текстов на русском языке. Тебе дан текст и список кандидатов в чувствительные сущности, найденных автоматически.

Твоя задача:
1. Проверь каждого кандидата — действительно ли это чувствительная сущность (ФИО, организация, адрес, ИНН, и т.п.)
2. Найди упущенные сущности (кореференции типа "он", "указанная организация", упоминания через должность)
3. Удали ложные срабатывания

Правила качества:
- ORG ставь только на конкретное наименование юридического лица или профессиональной фирмы с отличительным названием: "ООО Ромашка", "АО «Норд-Хим»", "Адвокатское бюро ЕПАМ", "EPAM Systems, Inc.".
- Не помечай как ORG родовые описания и роли без названия: "Адвокатское бюро", "Бюро", "компания", "банк", "поставщик", "арендодатель", "реквизиты".
- Не помечай бренды, продукты и сервисы как ORG без явного юридического контекста стороны договора.
- DATE/RU_DATE ставь только на календарные даты, а не на сроки вроде "10 дней", "11 месяцев", "30 дней".
- Если сомневаешься, лучше не добавляй сущность.

entity_type должен быть ровно одним значением из списка:
PER, ORG, LOC, ADDR, MON, RU_DATE, POSITION, RU_INN, RU_OGRN, RU_KPP,
RU_BANK_ACCOUNT, RU_BIK, RU_PHONE, EMAIL_ADDRESS, RU_CASE_NUMBER,
RU_CONTRACT_NUMBER.

Верни строго JSON:
{
  "verified": [
    {"text": "...", "entity_type": "PER", "start": N, "end": N, "score": 0.0-1.0}
  ],
  "added": [
    {"text": "...", "entity_type": "ORG", "start": N, "end": N, "score": 0.0-1.0}
  ],
  "removed_indices": []
}

=== ВХОДНЫЕ ДАННЫЕ ===
"""

# Prompt prefix for Layer 5 (find missed entities)
_PROMPT_PREFIX_FIND_MISSED = """Ты эксперт по обработке юридических текстов на русском языке. Тебе дан текст и список уже найденных чувствительных сущностей.

Твоя задача:
1. Внимательно прочитай весь текст
2. Найди ВСЕ чувствительные сущности, которые НЕ в списке найденных (ФИО, организации, адреса, должности, номера дел, реквизиты, даты важных событий)
3. Особое внимание на кореференции ("он", "она", "компания", "истец", "ответчик") и неполные упоминания

Правила качества:
- Добавляй ORG только для конкретных названий юридических лиц или профессиональных фирм с отличительным названием.
- Не добавляй родовые фразы без названия: "Адвокатское бюро", "Бюро", "компания", "банк", "поставщик", "арендодатель", "реквизиты".
- Не добавляй бренды/продукты/сервисы вроде "Alice AI" как ORG, если они не являются стороной договора или юридическим лицом в реквизитах.
- Не добавляй сроки исполнения как даты: "10 дней", "11 месяцев", "30 дней".
- Если находка спорная, не добавляй ее.

entity_type должен быть ровно одним значением из списка:
PER, ORG, LOC, ADDR, MON, RU_DATE, POSITION, RU_INN, RU_OGRN, RU_KPP,
RU_BANK_ACCOUNT, RU_BIK, RU_PHONE, EMAIL_ADDRESS, RU_CASE_NUMBER,
RU_CONTRACT_NUMBER.

Верни строго JSON БЕЗ дополнительных пояснений:
{
  "added": [
    {"text": "...", "entity_type": "RU_CONTRACT_NUMBER", "start": N, "end": N, "score": 0.7-1.0}
  ]
}

=== ВХОДНЫЕ ДАННЫЕ ===
"""

_FIND_MISSED_PAYLOAD_TEMPLATE = """ТЕКСТ:
{text}

УЖЕ НАЙДЕННЫЕ:
{known_entities}"""

_MAX_TEXT_LEN = 8000  # Cap text length for 7B model context window
_KNOWN_ENTITY_TYPES = set(KNOWN_ENTITY_TYPES)
_ENTITY_TYPE_ALIASES = {
    "DATE": "RU_DATE",
    "PHONE": "RU_PHONE",
    "EMAIL": "EMAIL_ADDRESS",
    "INN": "RU_INN",
    "OGRN": "RU_OGRN",
    "KPP": "RU_KPP",
    "BIK": "RU_BIK",
    "ACCOUNT": "RU_BANK_ACCOUNT",
    "BANK_ACCOUNT": "RU_BANK_ACCOUNT",
    "CONTRACT": "RU_CONTRACT_NUMBER",
    "CONTRACT_NUMBER": "RU_CONTRACT_NUMBER",
    "CASE": "RU_CASE_NUMBER",
    "CASE_NUMBER": "RU_CASE_NUMBER",
    "MONEY": "MON",
    "AMOUNT": "MON",
}


def _normalize_entity_type(raw: object) -> str | None:
    """Map LLM labels to known CLEARGATE entity types, drop malformed ones."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().upper()
    # The prompt lists alternatives as PER|ORG|..., and small models
    # sometimes echo the whole alternatives string as the answer.
    if not value or "|" in value or "/" in value:
        return None
    value = _ENTITY_TYPE_ALIASES.get(value, value)
    if value in _KNOWN_ENTITY_TYPES:
        return value
    return None


class LocalLLMVerifier:
    """Verifies and refines NER results using a local LLM via OpenAI-compat API.

    Supports both Ollama and vLLM backends through the OpenAI SDK.

    Args:
        model: Model name (e.g., "qwen2.5:7b-instruct-q4_K_M").
        base_url: Explicit HTTP base URL (e.g., "http://ollama:11434" or "http://vllm:8000").
            If not given, falls back to the OLLAMA_HOST env var, then to
            http://localhost:11434/v1. The URL is normalized to include /v1.

    The verifier is optional — the pipeline works without it (degraded mode).
    """

    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct-q4_K_M",
        base_url: str | None = None,
    ) -> None:
        self.model = model
        # Resolve and normalize the base_url once. We pass it explicitly to the
        # AsyncOpenAI client (instead of relying on env vars) so that the value
        # we *log* matches what the client actually talks to.
        raw_url = base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        # Normalize: strip trailing slash, ensure /v1 suffix
        self.base_url = raw_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url = f"{self.base_url}/v1"
        self._client: object | None = None
        self._first_call_done = False
        logger.info("llm_verifier.configured", base_url=self.base_url, model=self.model)

    def _get_client(self) -> object:
        """Lazy-init OpenAI async client for local LLM."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(base_url=self.base_url, api_key="cleargate-local-not-used")
        return self._client

    async def verify_and_refine(
        self,
        text: str,
        candidates: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Send candidates to local LLM for verification (Layer 4).

        Args:
            text: Original text.
            candidates: Entity candidates from layers 1-3.

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

        prompt = _PROMPT_PREFIX + f"""ТЕКСТ:
{text[:_MAX_TEXT_LEN]}

КАНДИДАТЫ:
{json.dumps(candidate_data, ensure_ascii=False, indent=2)}"""

        try:
            response_text = await self._generate_with_retry(prompt)
            result = json.loads(response_text)
            verified = self._parse_llm_results(result, candidates)

            logger.info(
                "llm_verifier.verify.done",
                original_count=len(candidates),
                verified_count=len(verified),
            )
            return verified

        except Exception:
            logger.warning(
                "llm_verifier.verify.failed",
                candidate_count=len(candidates),
                base_url=self.base_url,
                model=self.model,
                exc_info=True,
            )
            return candidates  # graceful degradation

    async def _generate_with_retry(self, prompt: str) -> str:
        """Call OpenAI-compat chat API, retrying the very first call.

        Subsequent calls go through immediately. Only the cold-start case
        (where ollama/vLLM is still warming up) gets the retry treatment,
        so steady-state latency is unaffected.

        Returns the JSON response text (not parsed).
        """
        client = self._get_client()
        attempts = 1 if self._first_call_done else _FIRST_CALL_RETRIES
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                completion = await client.chat.completions.create(  # type: ignore[union-attr]
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=1024,
                    extra_body={"keep_alive": "24h", "options": {"num_ctx": 3072, "num_predict": 1024}},
                )
                self._first_call_done = True
                return completion.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                logger.warning(
                    "llm_verifier.retry",
                    attempt=attempt,
                    of=attempts,
                    base_url=self.base_url,
                    model=self.model,
                    error=str(exc),
                )
                await asyncio.sleep(_FIRST_CALL_BACKOFF_SECONDS)

        assert last_exc is not None
        raise last_exc

    async def find_missed_entities(
        self,
        text: str,
        known_entities: list[DetectedEntity],
    ) -> list[DetectedEntity]:
        """Find entities missed by layers 1-4 (Layer 5).

        Args:
            text: Original text.
            known_entities: Entities already found by prior layers.

        Returns:
            List of newly discovered DetectedEntity objects (empty on error).
        """
        known_entities_str = json.dumps(
            [
                {"text": e.text, "entity_type": e.entity_type, "start": e.start, "end": e.end}
                for e in known_entities
            ],
            ensure_ascii=False,
            indent=2,
        )

        prompt = (
            _PROMPT_PREFIX_FIND_MISSED
            + _FIND_MISSED_PAYLOAD_TEMPLATE.format(
                text=text[:_MAX_TEXT_LEN],
                known_entities=known_entities_str,
            )
        )

        try:
            response_text = await asyncio.wait_for(
                self._generate_with_retry(prompt),
                timeout=_LLM_CALL_TIMEOUT_SECONDS,
            )
            result = json.loads(response_text)
            missed: list[DetectedEntity] = []

            for item in result.get("added", []):
                try:
                    entity_type = _normalize_entity_type(item.get("entity_type"))
                    if entity_type is None:
                        continue
                    missed.append(
                        DetectedEntity(
                            text=item["text"],
                            entity_type=entity_type,
                            start=item.get("start", 0),
                            end=item.get("end", 0),
                            score=min(float(item.get("score", 0.8)), 1.0),
                            source_layer="llm-scan",
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    continue

            logger.info("llm_verifier.find_missed.done", count=len(missed))
            return missed

        except asyncio.TimeoutError:
            logger.warning(
                "llm_verifier.find_missed.timeout",
                base_url=self.base_url,
                model=self.model,
            )
            return []
        except Exception:
            logger.warning(
                "llm_verifier.find_missed.failed",
                base_url=self.base_url,
                model=self.model,
                exc_info=True,
            )
            return []

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
                entity_type = _normalize_entity_type(item.get("entity_type"))
                if entity_type is None:
                    continue
                entities.append(
                    DetectedEntity(
                        text=item["text"],
                        entity_type=entity_type,
                        start=item.get("start", 0),
                        end=item.get("end", 0),
                        score=min(float(item.get("score", 0.8)), 1.0),
                        source_layer="llm",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue

        # Newly added entities from LLM
        for item in result.get("added", []):
            try:
                entity_type = _normalize_entity_type(item.get("entity_type"))
                if entity_type is None:
                    continue
                entities.append(
                    DetectedEntity(
                        text=item["text"],
                        entity_type=entity_type,
                        start=item.get("start", 0),
                        end=item.get("end", 0),
                        score=min(float(item.get("score", 0.7)), 1.0),
                        source_layer="llm",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue

        # If LLM returned nothing useful, keep originals
        if not entities:
            return original_candidates

        return entities
