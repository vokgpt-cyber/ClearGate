# Task 08: WebSocket Streaming for LLM Responses

## Контекст

REST API подходит для коротких операций, но ответы LLM с extended thinking могут идти десятки секунд. Нужен WebSocket endpoint, через который backend стримит токены к frontend в реальном времени, а после завершения автоматически деанонимизирует ответ.

## Зависимости

- Task 06 (REST API)
- Task 07 (Claude adapter)

## Цель

Реализовать WebSocket endpoint `/ws/stream` и React-хук `useLLMStream` для стриминга ответов LLM с автоматической деанонимизацией.

## Требования

### Backend WebSocket endpoint

```python
# backend/app/routers/llm_ws.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import BaseModel, ValidationError
from typing import Literal
import structlog

from app.services.session_manager import SessionManager
from app.services.llm_adapters.registry import LLMAdapterRegistry

logger = structlog.get_logger()
router = APIRouter()


class StreamRequest(BaseModel):
    session_id: str
    anonymized_text: str
    prompt: str
    provider: Literal["claude", "openai", "gemini"]
    model: str
    thinking_level: Literal["off", "low", "medium", "high", "max"] = "high"
    max_tokens: int = 8192


class StreamMessage(BaseModel):
    type: Literal["thinking_delta", "text_delta", "final", "error", "metadata"]
    content: str = ""
    metadata: dict = {}


@router.websocket("/ws/stream")
async def llm_stream(websocket: WebSocket):
    await websocket.accept()
    sm = SessionManager.instance()
    registry = LLMAdapterRegistry.instance()

    try:
        # Получаем запрос
        raw = await websocket.receive_json()
        try:
            request = StreamRequest(**raw)
        except ValidationError as e:
            await websocket.send_json({"type": "error", "content": f"Invalid request: {e}"})
            await websocket.close()
            return

        session = sm.get_session(request.session_id)
        if not session:
            await websocket.send_json({"type": "error", "content": "Session not found"})
            await websocket.close()
            return

        adapter = registry.get(request.provider)
        if not adapter:
            await websocket.send_json({"type": "error", "content": f"Provider {request.provider} not available"})
            await websocket.close()
            return

        logger.info(
            "ws.stream.start",
            session_id=request.session_id,
            provider=request.provider,
            model=request.model,
            thinking_level=request.thinking_level,
        )

        # Стримим ответ
        accumulated_text = ""
        accumulated_thinking = ""
        async for chunk in adapter.generate(
            anonymized_text=request.anonymized_text,
            prompt=request.prompt,
            model=request.model,
            thinking_level=request.thinking_level,
            max_tokens=request.max_tokens,
        ):
            if chunk.type == "thinking":
                accumulated_thinking += chunk.content
                await websocket.send_json({
                    "type": "thinking_delta",
                    "content": chunk.content,
                })
            elif chunk.type == "text":
                accumulated_text += chunk.content
                await websocket.send_json({
                    "type": "text_delta",
                    "content": chunk.content,
                })
            elif chunk.type == "done":
                # Деанонимизируем накопленный ответ
                deanonymized = session.registry.deanonymize_text(accumulated_text)
                await websocket.send_json({
                    "type": "final",
                    "content": deanonymized,
                    "metadata": chunk.metadata,
                })
            elif chunk.type == "error":
                await websocket.send_json({
                    "type": "error",
                    "content": chunk.content,
                })

        logger.info("ws.stream.done", session_id=request.session_id)
        await websocket.close()

    except WebSocketDisconnect:
        logger.info("ws.stream.disconnected")
    except Exception as e:
        logger.error("ws.stream.error", error=str(e))
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
            await websocket.close()
        except Exception:
            pass
```

### Frontend hook

```typescript
// frontend/src/hooks/useLLMStream.ts
import { useState, useCallback, useRef } from 'react';

export interface StreamRequest {
  sessionId: string;
  anonymizedText: string;
  prompt: string;
  provider: 'claude' | 'openai' | 'gemini';
  model: string;
  thinkingLevel?: 'off' | 'low' | 'medium' | 'high' | 'max';
  maxTokens?: number;
}

export interface StreamState {
  isStreaming: boolean;
  thinking: string;
  text: string;
  finalText: string | null;
  error: string | null;
  metadata: Record<string, unknown> | null;
}

export function useLLMStream() {
  const [state, setState] = useState<StreamState>({
    isStreaming: false,
    thinking: '',
    text: '',
    finalText: null,
    error: null,
    metadata: null,
  });
  const wsRef = useRef<WebSocket | null>(null);

  const start = useCallback((request: StreamRequest) => {
    setState({
      isStreaming: true,
      thinking: '',
      text: '',
      finalText: null,
      error: null,
      metadata: null,
    });

    const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'}/ws/stream`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({
        session_id: request.sessionId,
        anonymized_text: request.anonymizedText,
        prompt: request.prompt,
        provider: request.provider,
        model: request.model,
        thinking_level: request.thinkingLevel ?? 'high',
        max_tokens: request.maxTokens ?? 8192,
      }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case 'thinking_delta':
          setState((s) => ({ ...s, thinking: s.thinking + msg.content }));
          break;
        case 'text_delta':
          setState((s) => ({ ...s, text: s.text + msg.content }));
          break;
        case 'final':
          setState((s) => ({
            ...s,
            finalText: msg.content,
            metadata: msg.metadata,
            isStreaming: false,
          }));
          break;
        case 'error':
          setState((s) => ({ ...s, error: msg.content, isStreaming: false }));
          break;
      }
    };

    ws.onerror = () => {
      setState((s) => ({ ...s, error: 'Connection failed', isStreaming: false }));
    };

    ws.onclose = () => {
      setState((s) => ({ ...s, isStreaming: false }));
    };
  }, []);

  const cancel = useCallback(() => {
    wsRef.current?.close();
    setState((s) => ({ ...s, isStreaming: false }));
  }, []);

  const reset = useCallback(() => {
    cancel();
    setState({
      isStreaming: false,
      thinking: '',
      text: '',
      finalText: null,
      error: null,
      metadata: null,
    });
  }, [cancel]);

  return { state, start, cancel, reset };
}
```

## Файлы для создания

```
backend/app/routers/llm_ws.py
backend/app/services/llm_adapters/registry.py
backend/tests/routers/test_llm_ws.py
frontend/src/hooks/useLLMStream.ts
frontend/src/hooks/__tests__/useLLMStream.test.ts
```

## Тесты

### Backend
- WS handshake successful
- Invalid request → error message
- Session not found → error
- Streaming chunks proxy correctly
- Final message contains deanonymized text
- Disconnect mid-stream → cleanup корректно

Использовать `fastapi.testclient.TestClient` который поддерживает WebSocket.

### Frontend
- Mock WebSocket
- Test state transitions
- Test error handling
- Test cancel/reset

## Acceptance Criteria

- [ ] WS endpoint работает с реальным Claude adapter
- [ ] Стриминг thinking и text приходит инкрементально на фронтенд
- [ ] Финальный ответ деанонимизирован
- [ ] Cancel закрывает соединение и останавливает stream
- [ ] Логи не содержат содержимого ответов
- [ ] Tests проходят (mocked + integration)
- [ ] Frontend хук работает с реальным backend

## Команды

```powershell
# Backend
cd backend
pytest tests/routers/test_llm_ws.py -v
uvicorn app.main:app --reload

# Frontend
cd frontend
npm test useLLMStream
npm run tauri dev
```

## Коммит

```
feat(backend,frontend): WebSocket streaming for LLM responses

Backend:
- /ws/stream endpoint for real-time LLM token streaming
- Automatic deanonymization of final response using session registry
- Validation, error handling, structured logging without PII

Frontend:
- useLLMStream hook with streaming state management
- Separate thinking/text accumulation
- Cancel and reset support

Closes task #8
```
