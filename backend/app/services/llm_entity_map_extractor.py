"""Gemma-backed entity-map extraction for rollback-safe quality experiments.

The important architectural difference from the old verifier is that the LLM
never rewrites the document. It may only propose spans in the source text. Each
proposal is accepted only if it can be aligned back to the exact source text and
then still passes the deterministic policy gate in ``NERPipeline.post_process``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
from typing import Any, Literal

import httpx
import structlog

from app.models.entities import KNOWN_ENTITY_TYPES, DetectedEntity
from app.services.local_llm_verifier import _normalize_entity_type

logger = structlog.get_logger(__name__)

EntityMapAction = Literal["auto", "review", "ignore"]

_DEFAULT_CHUNK_CHARS = 6500
_DEFAULT_OVERLAP_CHARS = 500
_DEFAULT_TIMEOUT_SECONDS = 180.0
_MAX_REALIGN_WINDOW = 160

_SYSTEM_PROMPT = """
You are the CLEARGATE legal-document anonymization entity mapper.

Return only a JSON object with an "entities" array. Do not rewrite the document.
Prefer selecting from KNOWN CANDIDATES by candidate_id. You may add a new span
only when it is clearly sensitive and absent from KNOWN CANDIDATES.

Hard rules:
- "text" must exactly equal chunk[start:end].
- start/end are character offsets inside the current chunk, not the full document.
- If you are unsure about the exact span or type, omit it.
- Extract concrete legal entities, people, addresses, money amounts, document
  numbers, IDs, phones and calendar dates.
- ORG means a specific organization with a distinctive name, e.g.
  "АО «Норд-Хим»", "Адвокатское бюро ЕПАМ", "Meridian Advisory LLC".
- Do not mark generic descriptors without distinctive names, e.g.
  "Адвокатское бюро", "Бюро", "Сотрудник", "Застрахованный",
  "Доверитель", "Реквизиты", "Банк".
- Do not mark public AI products/services or public authorities as ORG:
  ChatGPT, Claude, Gemini, DeepSeek, Alice AI, GigaChat, Роспатент, ФНС.
- PER means only a concrete person name, not a role or category of persons.
- LOC/ADDR must be real places or addresses, not generic words like "Интернет"
  or "Бюро".
- RU_DATE means calendar dates only; do not mark durations such as "10 дней",
  "11 месяцев" or "30 дней" as dates.
- MON means money amounts and meaningful rates. Do not mark VAT percentages,
  penalty words or small template penalties like "0,1%" unless they are a real
  contract amount or fee.

Allowed entity_type values:
PER, ORG, LOC, ADDR, MON, RU_DATE, POSITION, RU_INN, RU_OGRN, RU_KPP,
RU_BANK_ACCOUNT, RU_BIK, RU_PHONE, EMAIL_ADDRESS, RU_CASE_NUMBER,
RU_CONTRACT_NUMBER, RU_POLICY_NUMBER.

Output schema:
{"entities":[{"candidate_id":"c1","action":"auto","reason":"specific legal entity"},{"text":"exact text","entity_type":"ORG","start":0,"end":10,"score":0.9,"action":"auto","reason":"missed sensitive span"}]}
"""


@dataclass(frozen=True)
class TextChunk:
    text: str
    start: int
    index: int


class LLMEntityMapExtractor:
    """Extract entity spans from Gemma/Ollama with strict local validation."""

    def __init__(
        self,
        model: str = "gemma4:26b",
        base_url: str | None = None,
        *,
        chunk_chars: int = _DEFAULT_CHUNK_CHARS,
        overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.base_url = self._normalize_ollama_url(base_url or "http://localhost:11434")
        self.chunk_chars = chunk_chars
        self.overlap_chars = overlap_chars
        self.timeout_seconds = timeout_seconds

    async def extract(
        self,
        text: str,
        *,
        known_entities: list[DetectedEntity] | None = None,
    ) -> list[DetectedEntity]:
        """Return validated LLM span proposals for ``text``.

        Invalid JSON, invalid offsets and hallucinated text are counted in logs
        and dropped. This method never raises for model-quality errors because
        the classic pipeline must remain available as the rollback path.
        """
        if not text.strip():
            return []

        known_entities = known_entities or []
        results: list[DetectedEntity] = []
        invalid_count = 0
        chunks = self._chunk_text(text)
        candidate_by_id = {
            f"c{index}": entity
            for index, entity in enumerate(known_entities)
        }

        for chunk in chunks:
            payload = self._build_user_payload(chunk, candidate_by_id)
            try:
                raw = await self._call_ollama(payload)
                data = self._parse_json_object(raw)
            except Exception as exc:
                logger.warning(
                    "llm_entity_map.chunk_failed",
                    chunk_index=chunk.index,
                    error=str(exc),
                    model=self.model,
                    base_url=self.base_url,
                )
                continue

            for item in data.get("entities", []):
                entity = self._validated_entity(text, chunk, item, candidate_by_id)
                if entity is None:
                    invalid_count += 1
                    continue
                results.append(entity)

        deduped = self._dedupe(results)
        logger.info(
            "llm_entity_map.done",
            model=self.model,
            chunks=len(chunks),
            raw_count=len(results),
            deduped_count=len(deduped),
            invalid_count=invalid_count,
        )
        return deduped

    async def _call_ollama(self, user_payload: str) -> str:
        url = f"{self.base_url}/api/chat"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            "stream": False,
            "format": "json",
            # The local Gemma4 build can expose a separate ``thinking`` field.
            # For entity extraction we need the final JSON in message.content.
            "think": False,
            "keep_alive": "24h",
            "options": {
                "temperature": 0,
                "num_ctx": 8192,
                "num_predict": 2048,
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        message = payload.get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            raise ValueError("Ollama returned empty message.content")
        return str(content)

    def _build_user_payload(
        self,
        chunk: TextChunk,
        candidate_by_id: dict[str, DetectedEntity],
    ) -> str:
        local_known: list[dict[str, Any]] = []
        chunk_end = chunk.start + len(chunk.text)
        for candidate_id, entity in candidate_by_id.items():
            if chunk.start <= entity.start and entity.end <= chunk_end:
                local_known.append(
                    {
                        "candidate_id": candidate_id,
                        "text": entity.text,
                        "entity_type": entity.entity_type,
                        "start": entity.start - chunk.start,
                        "end": entity.end - chunk.start,
                        "source_layer": entity.source_layer,
                    }
                )

        return (
            f"CHUNK_INDEX: {chunk.index}\n"
            f"CHUNK_GLOBAL_START: {chunk.start}\n\n"
            "Task: build the final anonymization entity map for this TEXT CHUNK.\n"
            "Step 1: select all sensitive spans from KNOWN CANDIDATES by returning "
            "their candidate_id. This is the preferred path.\n"
            "Step 2: add extra spans only if a sensitive span is missing from "
            "KNOWN CANDIDATES. Extra spans must include exact text and offsets.\n"
            "Do not select generic descriptors or public product names.\n\n"
            "Example output:\n"
            '{"entities":[{"candidate_id":"c0","action":"auto","reason":"specific legal entity"},{"text":"31 декабря 2024 г.","entity_type":"RU_DATE","start":70,"end":88,"score":0.95,"action":"auto","reason":"calendar date"}]}\n\n'
            "KNOWN CANDIDATES IN THIS CHUNK:\n"
            f"{json.dumps(local_known, ensure_ascii=False)}\n\n"
            "TEXT CHUNK:\n"
            f"{chunk.text}"
        )

    def _validated_entity(
        self,
        full_text: str,
        chunk: TextChunk,
        item: object,
        candidate_by_id: dict[str, DetectedEntity] | None = None,
    ) -> DetectedEntity | None:
        if not isinstance(item, dict):
            return None
        candidate_by_id = candidate_by_id or {}

        action = str(item.get("action") or "auto").strip().lower()
        if action == "ignore":
            return None
        if action not in {"auto", "review"}:
            action = "review"

        candidate_id = item.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id in candidate_by_id:
            return self._validated_candidate_entity(item, candidate_by_id[candidate_id])

        entity_type_value = item.get("entity_type", item.get("type"))
        entity_type = _normalize_entity_type(entity_type_value)
        if entity_type is None or entity_type not in KNOWN_ENTITY_TYPES:
            return None

        text_value = item.get("text")
        start_value = self._coerce_int(item.get("start"))
        end_value = self._coerce_int(item.get("end"))
        if not isinstance(text_value, str) or not text_value.strip():
            return None
        if start_value is None or end_value is None:
            return None

        text_value = text_value.strip()
        local_start, local_end = self._align_local_span(
            chunk.text,
            text_value,
            start_value,
            end_value,
        )
        if local_start is None or local_end is None:
            return None

        global_start = chunk.start + local_start
        global_end = chunk.start + local_end
        if not (0 <= global_start < global_end <= len(full_text)):
            return None
        if full_text[global_start:global_end] != chunk.text[local_start:local_end]:
            return None

        try:
            score = float(item.get("score", 0.82))
        except (TypeError, ValueError):
            score = 0.82
        score = max(0.0, min(score, 1.0))

        metadata = {
            "llm_entity_map_action": action,
            "llm_entity_map_reason": str(item.get("reason") or "")[:240],
            "llm_entity_map_chunk_index": chunk.index,
        }
        if (local_start, local_end) != (start_value, end_value):
            metadata["llm_entity_map_realigned"] = True

        return DetectedEntity(
            text=full_text[global_start:global_end],
            entity_type=entity_type,
            start=global_start,
            end=global_end,
            score=score,
            source_layer="llm-map",
            metadata=metadata,
        )

    def _validated_candidate_entity(
        self,
        item: dict[str, Any],
        candidate: DetectedEntity,
    ) -> DetectedEntity | None:
        try:
            score = float(item.get("score", max(candidate.score, 0.82)))
        except (TypeError, ValueError):
            score = max(candidate.score, 0.82)
        score = max(candidate.score, min(score, 1.0))

        metadata = {
            **(candidate.metadata or {}),
            "llm_entity_map_action": str(item.get("action") or "auto")[:40],
            "llm_entity_map_reason": str(item.get("reason") or "")[:240],
            "llm_entity_map_candidate_selected": True,
            "llm_entity_map_source_layer": candidate.source_layer,
        }
        return candidate.model_copy(
            update={
                "score": score,
                "source_layer": "hybrid",
                "metadata": metadata,
            }
        )

    def _align_local_span(
        self,
        chunk_text: str,
        text_value: str,
        start: int,
        end: int,
    ) -> tuple[int | None, int | None]:
        if 0 <= start < end <= len(chunk_text) and chunk_text[start:end] == text_value:
            return start, end

        # Allow one safe repair: if the model's text appears exactly once near
        # its claimed position, use that. Global arbitrary search would make
        # hallucinated offsets look valid, so keep the window tight.
        window_start = max(0, start - _MAX_REALIGN_WINDOW)
        window_end = min(len(chunk_text), end + _MAX_REALIGN_WINDOW)
        window = chunk_text[window_start:window_end]
        matches = [m.start() for m in re.finditer(re.escape(text_value), window)]
        if len(matches) == 1:
            repaired_start = window_start + matches[0]
            return repaired_start, repaired_start + len(text_value)
        return None, None

    def _parse_json_object(self, raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Some local models still wrap JSON in prose despite format hints.
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if match is None:
                raise
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("LLM entity-map response is not a JSON object")
        if not isinstance(parsed.get("entities"), list):
            parsed["entities"] = []
        return parsed

    def _chunk_text(self, text: str) -> list[TextChunk]:
        if len(text) <= self.chunk_chars:
            return [TextChunk(text=text, start=0, index=0)]

        chunks: list[TextChunk] = []
        start = 0
        index = 0
        while start < len(text):
            hard_end = min(len(text), start + self.chunk_chars)
            end = hard_end
            if hard_end < len(text):
                newline = text.rfind("\n", start + int(self.chunk_chars * 0.75), hard_end)
                if newline > start:
                    end = newline + 1
            chunks.append(TextChunk(text=text[start:end], start=start, index=index))
            if end >= len(text):
                break
            start = max(end - self.overlap_chars, start + 1)
            index += 1
        return chunks

    def _dedupe(self, entities: list[DetectedEntity]) -> list[DetectedEntity]:
        best_by_key: dict[tuple[int, int, str], DetectedEntity] = {}
        for entity in entities:
            key = (entity.start, entity.end, entity.entity_type)
            existing = best_by_key.get(key)
            if existing is None or entity.score > existing.score:
                best_by_key[key] = entity
        return sorted(best_by_key.values(), key=lambda entity: (entity.start, -entity.score))

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    @staticmethod
    def _normalize_ollama_url(raw: str) -> str:
        value = raw.rstrip("/")
        if value.endswith("/v1"):
            value = value[:-3]
        return value
