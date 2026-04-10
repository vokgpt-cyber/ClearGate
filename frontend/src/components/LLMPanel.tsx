'use client';

import { useState, useCallback } from 'react';
import { useLocale } from '@/hooks/useLocale';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface LLMPanelProps {
  sessionId: string | null;
  anonymizedText: string;
}

const TEMPLATES = [
  { id: 'analyze', label: 'Analyze', prompt: 'Проанализируй этот юридический документ и дай краткое резюме основных условий, рисков и обязательств сторон.' },
  { id: 'risks', label: 'Risks', prompt: 'Определи все потенциальные юридические риски в этом документе.' },
  { id: 'summary', label: 'Summary', prompt: 'Составь краткое резюме документа: стороны, предмет, сроки, стоимость, ключевые условия.' },
];

export function LLMPanel({ sessionId, anonymizedText }: LLMPanelProps) {
  const { t } = useLocale();
  const [prompt, setPrompt] = useState(TEMPLATES[0].prompt);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [response, setResponse] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSend = useCallback(() => {
    if (!sessionId || !anonymizedText.trim()) return;
    setShowConfirm(true);
  }, [sessionId, anonymizedText]);

  const confirmSend = useCallback(async () => {
    if (!sessionId) return;
    setShowConfirm(false);
    setIsLoading(true);
    setError(null);
    setResponse(null);

    try {
      const fullText = `${prompt}\n\n${anonymizedText}`;
      const resp = await fetch(`${API_URL}/api/sessions/${sessionId}/llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: fullText }),
      });

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(detail.detail || `HTTP ${resp.status}`);
      }

      const data = await resp.json();
      setResponse(data.response);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'LLM request failed');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, anonymizedText, prompt]);

  const canSend = !!sessionId && !!anonymizedText.trim() && !isLoading;

  return (
    <div style={{
      borderTop: '1px solid var(--border)',
      backgroundColor: 'var(--bg-secondary)',
    }}>
      {/* Input row */}
      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
        padding: '0.5rem 0.75rem',
      }}>
        {/* Templates */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: '70px' }}>
          {TEMPLATES.map((tmpl) => (
            <button key={tmpl.id} onClick={() => setPrompt(tmpl.prompt)}
              style={{
                padding: '0.125rem 0.375rem', fontSize: '0.625rem',
                borderRadius: '2px',
                border: `1px solid ${prompt === tmpl.prompt ? 'var(--accent)' : 'var(--border)'}`,
                backgroundColor: prompt === tmpl.prompt ? 'var(--accent)' : 'transparent',
                color: prompt === tmpl.prompt ? '#fff' : 'var(--text-muted)',
                cursor: 'pointer', textAlign: 'left' as const,
              }}
            >{tmpl.label}</button>
          ))}
        </div>

        {/* Prompt */}
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
          rows={2}
          style={{
            flex: 1, padding: '0.375rem 0.5rem', borderRadius: '2px',
            border: '1px solid var(--border)',
            backgroundColor: 'var(--bg-input)', color: 'var(--text-primary)',
            fontFamily: 'var(--font-sans)', fontSize: '0.75rem',
            resize: 'vertical', lineHeight: 1.4,
          }}
          placeholder={t('llm.prompt')}
        />

        {/* Send */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <button onClick={handleSend} disabled={!canSend} style={{
            padding: '0.3rem 0.625rem', borderRadius: '2px',
            border: '1px solid var(--accent)',
            backgroundColor: canSend ? 'var(--accent)' : 'transparent',
            color: canSend ? '#fff' : 'var(--text-muted)',
            cursor: canSend ? 'pointer' : 'not-allowed',
            fontWeight: 600, fontSize: '0.6875rem',
            whiteSpace: 'nowrap' as const,
          }}>
            {isLoading ? t('llm.sending') : t('llm.send')}
          </button>
          <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)' }}>
            Claude Sonnet 4.6
          </span>
        </div>
      </div>

      {/* Confirmation */}
      {showConfirm && (
        <div style={{
          margin: '0 0.75rem 0.5rem', padding: '0.5rem',
          borderRadius: '2px', border: '1px solid var(--accent)',
          backgroundColor: 'var(--bg-elevated)', fontSize: '0.75rem',
        }}>
          <p style={{ fontWeight: 600, marginBottom: '0.25rem' }}>{t('llm.confirmSend')}</p>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.6875rem', marginBottom: '0.375rem' }}>
            {t('llm.confirmMessage')}
          </p>
          <div style={{ display: 'flex', gap: '0.375rem' }}>
            <button onClick={confirmSend} style={{
              padding: '0.2rem 0.5rem', borderRadius: '2px', border: 'none',
              backgroundColor: 'var(--accent)', color: '#fff', cursor: 'pointer', fontSize: '0.6875rem',
            }}>{t('llm.send')}</button>
            <button onClick={() => setShowConfirm(false)} style={{
              padding: '0.2rem 0.5rem', borderRadius: '2px',
              border: '1px solid var(--border)', backgroundColor: 'transparent',
              color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.6875rem',
            }}>{t('llm.cancel')}</button>
          </div>
        </div>
      )}

      {/* Response */}
      {(response || error) && (
        <div style={{
          borderTop: '1px solid var(--border)',
          maxHeight: '250px', overflow: 'auto',
          padding: '0.5rem 0.75rem',
        }}>
          {response && (
            <div style={{
              padding: '0.5rem', borderRadius: '2px',
              border: '1px solid var(--border)',
              backgroundColor: 'var(--bg-primary)',
              fontSize: '0.8125rem', lineHeight: 1.7, whiteSpace: 'pre-wrap',
            }}>
              {response}
            </div>
          )}
          {error && (
            <div style={{ fontSize: '0.75rem', color: 'var(--error)', padding: '0.25rem 0' }}>
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
