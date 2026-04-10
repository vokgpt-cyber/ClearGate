'use client';

/**
 * SelectionToolbar — floating "Add as entity" menu that appears when
 * the user selects text in the ORIGINAL pane of the workspace.
 *
 * The toolbar itself is passive: SplitWorkspace tracks the selection,
 * computes the anchor rect, and hands it in via props. We only render
 * the button with a type picker and call back when the user picks.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocale } from '@/hooks/useLocale';
import {
  ENTITY_TYPES,
  LEGEND_ORDER,
  type EntityTypeCode,
} from '@/lib/entity-types';

export interface SelectionInfo {
  /** Viewport-relative rect of the selection (from getBoundingClientRect). */
  rect: DOMRect;
  /** Selected text (what the user sees). */
  text: string;
  /** Plain-text offsets inside the document (backend-aligned). */
  start: number;
  end: number;
}

interface SelectionToolbarProps {
  selection: SelectionInfo | null;
  busy?: boolean;
  error?: string | null;
  onAddEntity: (info: SelectionInfo, entityType: EntityTypeCode) => void;
  onDismiss: () => void;
}

export function SelectionToolbar({
  selection,
  busy,
  error,
  onAddEntity,
  onDismiss,
}: SelectionToolbarProps) {
  const { locale, t } = useLocale();
  const ref = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!selection) {
      setPosition(null);
      setOpen(false);
      return;
    }
    const el = ref.current;
    const width = el?.offsetWidth ?? 180;
    const height = el?.offsetHeight ?? 40;
    const gap = 8;
    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // Prefer above the selection; flip below if there's no room.
    let top = selection.rect.top - height - gap;
    if (top < margin) {
      top = Math.min(selection.rect.bottom + gap, vh - height - margin);
    }
    let left = selection.rect.left + selection.rect.width / 2 - width / 2;
    left = Math.min(Math.max(left, margin), vw - width - margin);
    setPosition({ top, left });
  }, [selection]);

  useEffect(() => {
    if (!selection) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [selection, onDismiss]);

  if (!selection) return null;

  return (
    <div
      ref={ref}
      className={`velum-selection ${open ? 'velum-selection--open' : ''}`}
      style={{
        top: position?.top ?? -9999,
        left: position?.left ?? -9999,
      }}
    >
      {!open ? (
        <button
          type="button"
          className="velum-selection__primary"
          onClick={() => setOpen(true)}
          disabled={busy}
        >
          <span className="velum-selection__icon" aria-hidden>+</span>
          {busy ? t('selection.adding') : t('selection.addAs')}…
        </button>
      ) : (
        <div className="velum-selection__types">
          <div className="velum-selection__title">{t('selection.pickType')}</div>
          <ul>
            {LEGEND_ORDER.map((code) => {
              const info = ENTITY_TYPES[code as EntityTypeCode];
              const label = locale === 'ru' ? info.labelRu : info.labelEn;
              return (
                <li key={code}>
                  <button
                    type="button"
                    className="velum-selection__type"
                    onClick={() => onAddEntity(selection, code)}
                    disabled={busy}
                  >
                    <span
                      className={`velum-selection__swatch velum-entity--${info.cssKey}`}
                      aria-hidden
                    />
                    {label}
                  </button>
                </li>
              );
            })}
          </ul>
          {error && <div className="velum-selection__error">{error}</div>}
        </div>
      )}
    </div>
  );
}
