# Task 06: Anonymize API Routes

## Контекст

Бэкенд должен предоставлять REST API для frontend: загрузка документа, запуск анонимизации, просмотр сущностей, деанонимизация, управление сессиями.

## Зависимости

- Task 03 (NER pipeline)
- Task 04 (EntityRegistry)
- Прочитать `docs/API.md`

## Цель

Реализовать FastAPI роутеры для всех операций анонимизации с правильной валидацией, error handling и логированием (без PII).

## Требования

### Endpoints

```
POST   /api/sessions                  — создать новую сессию
GET    /api/sessions/{id}             — получить состояние сессии
DELETE /api/sessions/{id}             — закрыть сессию (zero-out memory)

POST   /api/documents/upload          — загрузить документ (multipart)
POST   /api/documents/parse-text      — отправить plain text напрямую

POST   /api/sessions/{id}/anonymize   — запустить pipeline анонимизации
GET    /api/sessions/{id}/entities    — получить список сущностей
PATCH  /api/sessions/{id}/entities/{entity_id}  — обновить сущность (accept/reject/edit)
POST   /api/sessions/{id}/entities    — добавить сущность вручную

POST   /api/sessions/{id}/deanonymize — деанонимизировать произвольный текст
GET    /api/sessions/{id}/export-mapping  — экспорт зашифрованного mapping
POST   /api/sessions/{id}/import-mapping  — импорт зашифрованного mapping
```

### Pydantic schemas

```python
# backend/app/models/api.py

from pydantic import BaseModel, Field
from typing import Literal
from app.models.entities import DetectedEntity, EntityType


class CreateSessionRequest(BaseModel):
    locale: Literal["ru", "en"] = "ru"
    enable_llm_layer: bool = True
    custom_entities: list[str] = []


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str
    expires_at: str


class UploadResponse(BaseModel):
    text: str
    format: Literal["docx", "pdf", "txt"]
    page_count: int | None = None
    char_count: int


class AnonymizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000_000)


class AnonymizeResponse(BaseModel):
    anonymized_text: str
    entities: list[DetectedEntity]
    stats: dict[str, int]  # {"PER": 5, "ORG": 3, ...}


class UpdateEntityRequest(BaseModel):
    action: Literal["accept", "reject", "edit"]
    new_value: str | None = None


class DeanonymizeRequest(BaseModel):
    text: str
```

### Router: sessions.py

```python
# backend/app/routers/sessions.py

from fastapi import APIRouter, HTTPException, Depends, status
from datetime import datetime, timedelta, UTC
import secrets

from app.models.api import CreateSessionRequest, CreateSessionResponse
from app.services.session_manager import SessionManager
from app.config import settings

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def get_session_manager() -> SessionManager:
    """Dependency to get session manager (singleton)."""
    return SessionManager.instance()


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    sm: SessionManager = Depends(get_session_manager),
) -> CreateSessionResponse:
    """Create a new anonymization session."""
    session_id = secrets.token_urlsafe(16)
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.SESSION_TTL_MINUTES)

    sm.create_session(
        session_id=session_id,
        locale=request.locale,
        enable_llm_layer=request.enable_llm_layer,
        custom_entities=request.custom_entities,
    )

    return CreateSessionResponse(
        session_id=session_id,
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat(),
    )


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    sm: SessionManager = Depends(get_session_manager),
):
    """Get session state (without exposing mapping table)."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "created_at": session.created_at.isoformat(),
        "entity_count": session.registry.entity_count(),
        "stats": session.registry.stats(),
    }


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_session(
    session_id: str,
    sm: SessionManager = Depends(get_session_manager),
):
    """Close session and securely clear all data."""
    sm.close_session(session_id)
```

### Router: anonymize.py

```python
# backend/app/routers/anonymize.py

from fastapi import APIRouter, HTTPException, Depends
from app.models.api import (
    AnonymizeRequest, AnonymizeResponse,
    UpdateEntityRequest, DeanonymizeRequest,
)
from app.services.session_manager import SessionManager
from app.routers.sessions import get_session_manager
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/sessions/{session_id}", tags=["anonymize"])


@router.post("/anonymize", response_model=AnonymizeResponse)
async def anonymize(
    session_id: str,
    request: AnonymizeRequest,
    sm: SessionManager = Depends(get_session_manager),
):
    """Run NER pipeline and return anonymized text."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # КРИТИЧЕСКИ: НЕ логировать request.text!
    logger.info(
        "anonymize.start",
        session_id=session_id,
        text_length=len(request.text),
    )

    try:
        entities = await session.pipeline.analyze(
            text=request.text,
            language=session.locale,
            custom_entities=session.custom_entities,
        )
        anonymized = session.registry.anonymize_text(request.text, entities)

        stats: dict[str, int] = {}
        for e in entities:
            stats[e.entity_type] = stats.get(e.entity_type, 0) + 1

        logger.info(
            "anonymize.done",
            session_id=session_id,
            entity_count=len(entities),
            stats=stats,
        )
        return AnonymizeResponse(
            anonymized_text=anonymized,
            entities=entities,
            stats=stats,
        )
    except Exception as e:
        logger.error("anonymize.error", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Anonymization failed")


@router.post("/deanonymize")
async def deanonymize(
    session_id: str,
    request: DeanonymizeRequest,
    sm: SessionManager = Depends(get_session_manager),
):
    """Replace placeholders in text with original values."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"text": session.registry.deanonymize_text(request.text)}


@router.patch("/entities/{entity_id}")
async def update_entity(
    session_id: str,
    entity_id: str,
    request: UpdateEntityRequest,
    sm: SessionManager = Depends(get_session_manager),
):
    """Accept, reject, or edit a detected entity."""
    session = sm.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.action == "edit" and request.new_value is None:
        raise HTTPException(status_code=400, detail="new_value required for edit action")

    session.registry.handle_user_action(entity_id, request.action, request.new_value)
    return {"ok": True}
```

### Router: documents.py

```python
# backend/app/routers/documents.py

from fastapi import APIRouter, UploadFile, HTTPException, status
from app.models.api import UploadResponse
from app.services.doc_processor import DocumentProcessor
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile):
    """Parse uploaded document and return plain text."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = file.filename.lower().split(".")[-1]
    if suffix not in {"docx", "pdf", "txt"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported format: {suffix}",
        )

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50 MB
        raise HTTPException(status_code=413, detail="File too large")

    processor = DocumentProcessor()
    try:
        result = processor.parse(content, format=suffix)
    except Exception as e:
        # НЕ логировать содержимое
        logger.error("parse.error", filename=file.filename, error=str(e))
        raise HTTPException(status_code=400, detail="Failed to parse document")

    return UploadResponse(
        text=result.text,
        format=suffix,
        page_count=result.page_count,
        char_count=len(result.text),
    )
```

### SessionManager service

```python
# backend/app/services/session_manager.py

from threading import Lock
from datetime import datetime, timedelta, UTC
from app.services.ner_pipeline import NERPipeline
from app.services.entity_registry import EntityRegistry
from app.config import settings


class Session:
    def __init__(
        self,
        session_id: str,
        locale: str,
        enable_llm_layer: bool,
        custom_entities: list[str],
        master_key: bytes,
    ) -> None:
        self.session_id = session_id
        self.locale = locale
        self.custom_entities = custom_entities
        self.created_at = datetime.now(UTC)
        self.pipeline = NERPipeline(
            spacy_model=settings.SPACY_MODEL,
            gliner_model=settings.GLINER_MODEL,
            ollama_model=settings.OLLAMA_MODEL,
            enable_llm_layer=enable_llm_layer,
        )
        self.registry = EntityRegistry(
            master_key=master_key,
            session_id=session_id,
            locale=locale,
        )


class SessionManager:
    _instance: "SessionManager | None" = None
    _lock = Lock()

    @classmethod
    def instance(cls) -> "SessionManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create_session(self, session_id: str, **kwargs) -> Session:
        session = Session(session_id=session_id, master_key=settings.master_key_bytes, **kwargs)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session and self._is_expired(session):
            self.close_session(session_id)
            return None
        return session

    def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            session.registry.clear()

    def _is_expired(self, session: Session) -> bool:
        ttl = timedelta(minutes=settings.SESSION_TTL_MINUTES)
        return datetime.now(UTC) - session.created_at > ttl
```

## Файлы для создания

```
backend/app/routers/sessions.py
backend/app/routers/anonymize.py
backend/app/routers/documents.py
backend/app/services/session_manager.py
backend/app/services/doc_processor.py
backend/app/models/api.py
backend/tests/routers/test_sessions.py
backend/tests/routers/test_anonymize.py
backend/tests/routers/test_documents.py
```

## Тесты

Использовать FastAPI TestClient. Каждый endpoint:
- Happy path
- Validation errors (400, 422)
- Not found (404)
- Idempotency где применимо
- Логирование НЕ содержит PII (проверка через caplog)

## Acceptance Criteria

- [ ] Все endpoints работают
- [ ] OpenAPI документация генерируется автоматически (`/docs`)
- [ ] Логи НЕ содержат оригинального текста или mapping
- [ ] Round-trip тест: upload → anonymize → deanonymize
- [ ] mypy strict без ошибок
- [ ] Test coverage ≥ 80%

## Команды

```powershell
cd backend
uvicorn app.main:app --reload
# Открыть http://localhost:8000/docs
pytest tests/routers/ -v
```

## Коммит

```
feat(backend): implement anonymize API routes

- Sessions: create/get/close with secure cleanup
- Documents: upload (DOCX/PDF/TXT) with format detection
- Anonymize: run pipeline, return entities and anonymized text
- Deanonymize: reverse mapping for arbitrary text
- Entity updates: accept/reject/edit user actions
- All endpoints log metadata only (no PII)

Closes task #6
```
