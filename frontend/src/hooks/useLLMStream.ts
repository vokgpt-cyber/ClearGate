import { useState, useCallback, useRef } from 'react';

import { wsUrl } from '@/lib/api';

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

const initialState: StreamState = {
  isStreaming: false,
  thinking: '',
  text: '',
  finalText: null,
  error: null,
  metadata: null,
};

export function useLLMStream() {
  const [state, setState] = useState<StreamState>(initialState);
  const wsRef = useRef<WebSocket | null>(null);

  const start = useCallback((request: StreamRequest) => {
    setState({ ...initialState, isStreaming: true });

    const ws = new WebSocket(`${wsUrl()}/ws/stream`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          session_id: request.sessionId,
          anonymized_text: request.anonymizedText,
          prompt: request.prompt,
          provider: request.provider,
          model: request.model,
          thinking_level: request.thinkingLevel ?? 'high',
          max_tokens: request.maxTokens ?? 8192,
        }),
      );
    };

    ws.onmessage = (event: MessageEvent) => {
      const msg = JSON.parse(event.data as string) as {
        type: string;
        content?: string;
        metadata?: Record<string, unknown>;
      };

      switch (msg.type) {
        case 'thinking_delta':
          setState((s) => ({ ...s, thinking: s.thinking + (msg.content ?? '') }));
          break;
        case 'text_delta':
          setState((s) => ({ ...s, text: s.text + (msg.content ?? '') }));
          break;
        case 'final':
          setState((s) => ({
            ...s,
            finalText: msg.content ?? '',
            metadata: msg.metadata ?? null,
            isStreaming: false,
          }));
          break;
        case 'error':
          setState((s) => ({ ...s, error: msg.content ?? 'Unknown error', isStreaming: false }));
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
    setState(initialState);
  }, [cancel]);

  return { state, start, cancel, reset };
}
