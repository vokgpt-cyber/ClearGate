'use client';

import { useState, useCallback, useRef } from 'react';
import { useLocale } from '@/hooks/useLocale';
import type { DetectedEntity } from '@/types/entities';
import { getEntityColor } from '@/lib/colors';
import { API_URL, createSession, anonymizeText } from '@/lib/api';

interface SplitScreenProps {
  onAnonymized?: (sessionId: string, anonymizedText: string, entities: DetectedEntity[]) => void;
}

/** Render text with highlighted entity spans. */
function HighlightedText({ text, entities }: { text: string; entities: DetectedEntity[] }) {
  if (!entities.length) return <>{text}</>;

  const sorted = [...entities].sort((a, b) => a.start - b.start);
  const parts: React.ReactNode[] = [];
  let cursor = 0;

  for (const entity of sorted) {
    if (entity.start > cursor) {
      parts.push(text.slice(cursor, entity.start));
    }
    if (entity.start >= cursor) {
      const color = getEntityColor(entity.entity_type);
      parts.push(
        <mark
          key={`${entity.start}-${entity.end}`}
          title={`${entity.entity_type} (${(entity.score * 100).toFixed(0)}%)`}
          style={{
            backgroundColor: color.bg,
            color: color.text,
            borderBottom: `2px solid ${color.border}`,
            padding: '0 2px',
            borderRadius: '2px',
            cursor: 'default',
          }}
        >
          {text.slice(entity.start, entity.end)}
        </mark>,
      );
      cursor = entity.end;
    }
  }

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return <>{parts}</>;
}

export function SplitScreen({ onAnonymized }: SplitScreenProps) {
  const { t } = useLocale();
  const [originalText, setOriginalText] = useState('');
  const [anonymizedText, setAnonymizedText] = useState('');
  const [entities, setEntities] = useState<DetectedEntity[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleAnonymize = useCallback(async () => {
    if (!originalText.trim()) return;
    setIsLoading(true);
    setError(null);

    try {
      let sid = sessionId;
      if (!sid) {
        const session = await createSession();
        sid = session.session_id;
        setSessionId(sid);
      }

      const result = await anonymizeText(sid, originalText);
      setAnonymizedText(result.anonymized_text);
      setEntities(result.entities as DetectedEntity[]);
      onAnonymized?.(sid, result.anonymized_text, result.entities as DetectedEntity[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Anonymization failed');
    } finally {
      setIsLoading(false);
    }
  }, [originalText, sessionId, onAnonymized]);

  const uploadFile = useCallback(async (file: File) => {
    setIsLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch(`${API_URL}/api/documents/upload`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      setOriginalText(data.text);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }, [uploadFile]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
    >
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        padding: '0.375rem 0.75rem',
        borderBottom: '1px solid var(--border)',
        backgroundColor: 'var(--bg-secondary)',
      }}>
        {/* Upload button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          style={{
            padding: '0.3rem 0.625rem', borderRadius: '2px',
            border: '1px solid var(--border)',
            backgroundColor: 'transparent', color: 'var(--text-secondary)',
            cursor: 'pointer', fontSize: '0.75rem',
          }}
        >
          Upload
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".docx,.pdf,.txt"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadFile(f); }}
          style={{ display: 'none' }}
        />

        {/* Anonymize button */}
        <button
          onClick={handleAnonymize}
          disabled={isLoading || !originalText.trim()}
          style={{
            padding: '0.3rem 0.75rem', borderRadius: '2px',
            border: '1px solid var(--accent)',
            backgroundColor: isLoading ? 'var(--text-muted)' : 'var(--accent)',
            color: '#fff', cursor: isLoading ? 'not-allowed' : 'pointer',
            fontWeight: 600, fontSize: '0.75rem',
            opacity: !originalText.trim() ? 0.5 : 1,
          }}
        >
          {isLoading ? t('editor.anonymizing') : t('editor.anonymize')}
        </button>

        {entities.length > 0 && (
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
            {t('session.entities')}: {entities.length}
          </span>
        )}

        {error && <span style={{ fontSize: '0.6875rem', color: 'var(--error)' }}>{error}</span>}
      </div>

      {/* Split panels */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Left: Original with highlighting */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)' }}>
          <div style={{
            padding: '0.3rem 0.75rem', fontSize: '0.625rem', fontWeight: 600,
            color: 'var(--text-muted)', textTransform: 'uppercase' as const,
            letterSpacing: '0.06em',
            borderBottom: '1px solid var(--border)', backgroundColor: 'var(--bg-secondary)',
          }}>
            {t('editor.original')}
          </div>
          {entities.length > 0 ? (
            /* Show highlighted read-only view when entities exist */
            <div style={{
              flex: 1, padding: '0.75rem', overflow: 'auto',
              backgroundColor: 'var(--bg-primary)',
              fontSize: '0.8125rem', lineHeight: 1.7, whiteSpace: 'pre-wrap',
            }}>
              <HighlightedText text={originalText} entities={entities} />
            </div>
          ) : (
            /* Editable textarea before anonymization */
            <textarea
              value={originalText}
              onChange={(e) => setOriginalText(e.target.value)}
              placeholder={t('editor.paste')}
              style={{
                flex: 1, padding: '0.75rem', border: 'none', outline: 'none', resize: 'none',
                backgroundColor: 'var(--bg-primary)', color: 'var(--text-primary)',
                fontFamily: 'var(--font-sans)', fontSize: '0.8125rem', lineHeight: 1.7,
              }}
            />
          )}
        </div>

        {/* Right: Anonymized text */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{
            padding: '0.3rem 0.75rem', fontSize: '0.625rem', fontWeight: 600,
            color: 'var(--text-muted)', textTransform: 'uppercase' as const,
            letterSpacing: '0.06em',
            borderBottom: '1px solid var(--border)', backgroundColor: 'var(--bg-secondary)',
          }}>
            {t('editor.anonymized')}
          </div>
          <div style={{
            flex: 1, padding: '0.75rem', overflow: 'auto',
            backgroundColor: 'var(--bg-primary)',
            fontSize: '0.8125rem', lineHeight: 1.7, whiteSpace: 'pre-wrap',
          }}>
            {anonymizedText || (
              <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontFamily: 'var(--font-serif)' }}>
                {t('session.noEntities')}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
