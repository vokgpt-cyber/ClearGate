'use client';

/**
 * DocxViewer — renders a DOCX document with Word-like fidelity inside the
 * browser using docx-preview. Iteration 1 of the new anonymizer UX.
 *
 * Responsibilities:
 *   - Fetch raw DOCX bytes from the backend by session id
 *   - Render them via docx-preview into a scrollable container
 *   - Expose the rendered container through an `onReady` callback so other
 *     components (DocxAnchorMap, overlay layers in future iterations) can
 *     read text nodes and DOM positions.
 *
 * No interactivity yet — Iteration 1 is purely presentational. The user
 * should only see the document rendered as if opened in Word.
 */

import { useEffect, useRef, useState } from 'react';
import { useLocale } from '@/hooks/useLocale';

interface DocxViewerProps {
  /** Session id that has a DOCX attached (returned from upload). */
  documentId: string | null;
  /** Called once rendering completes with the rendered container element. */
  onReady?: (container: HTMLElement) => void;
  /** Optional class name added to the outer wrapper. */
  className?: string;
  /** Optional label shown at the top (e.g. 'Оригинал' / 'Анонимизированный'). */
  label?: string;
  /** When set, fetch DOCX bytes from this URL instead of the default. */
  urlOverride?: string | null;
}

type Status = 'idle' | 'loading' | 'ready' | 'error';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export function DocxViewer({ documentId, onReady, className, label, urlOverride }: DocxViewerProps) {
  const { t } = useLocale();
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!documentId || !containerRef.current) {
      setStatus('idle');
      return;
    }

    const container = containerRef.current;
    let cancelled = false;

    setStatus('loading');
    setError(null);
    container.innerHTML = '';

    (async () => {
      try {
        const fetchUrl = urlOverride ?? `${API_URL}/api/documents/${documentId}/raw`;
        const response = await fetch(fetchUrl);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        }
        const blob = await response.blob();
        if (cancelled) return;

        // Dynamic import keeps docx-preview out of the initial bundle and
        // out of SSR (it touches DOM APIs not available on the server).
        const docx = await import('docx-preview');
        if (cancelled) return;

        await docx.renderAsync(blob, container, undefined, {
          className: 'velum-docx',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
          breakPages: true,
          ignoreLastRenderedPageBreak: true,
          experimental: true,
          trimXmlDeclaration: true,
          useBase64URL: false,
          renderHeaders: true,
          renderFooters: true,
          renderFootnotes: true,
          renderEndnotes: true,
          // renderChanges: false — not a track-changes viewer
          debug: false,
        });

        if (cancelled) return;
        setStatus('ready');
        onReady?.(container);
      } catch (e) {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.error('[DocxViewer] render failed', e);
        setError(e instanceof Error ? e.message : String(e));
        setStatus('error');
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [documentId, onReady, urlOverride]);

  return (
    <div className={`velum-docx-viewer ${className ?? ''}`}>
      {label && (
        <div className="velum-docx-viewer__label">
          <span>{label}</span>
          {status === 'loading' && (
            <span className="velum-docx-viewer__spinner" aria-label={t('docx.loading')}>
              {t('docx.loading')}
            </span>
          )}
        </div>
      )}
      <div className="velum-docx-viewer__scroll">
        <div ref={containerRef} className="velum-docx-viewer__container" />
        {status === 'idle' && (
          <div className="velum-docx-viewer__placeholder">{t('docx.empty')}</div>
        )}
        {status === 'error' && (
          <div className="velum-docx-viewer__error">
            <strong>{t('docx.error')}</strong>
            <span>{error}</span>
          </div>
        )}
      </div>
    </div>
  );
}
