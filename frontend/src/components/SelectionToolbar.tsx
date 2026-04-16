'use client';

/**
 * SelectionToolbar — floating "Anonymize" menu that appears under the
 * user's cursor when they select text in EITHER pane of the workspace.
 *
 * The toolbar itself is passive. SplitWorkspace:
 *   1. Listens for mouseup anywhere in the document.
 *   2. Inspects the current selection, figures out which pane it lives
 *      in, and translates its offsets back to the ORIGINAL (left-pane)
 *      coordinate system.
 *   3. Hands us a SelectionInfo that carries the cursor position
 *      (`anchor`) and the left-pane offsets.
 *
 * We only render a single-button "Анонимизировать" control which
 * expands into a 2-column type picker when clicked. Position is
 * computed from `selection.anchor` so the popover actually appears
 * under the cursor the user just released — the expected Google Docs /
 * Harvey.AI-style affordance.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocale } from '@/hooks/useLocale';
import {
  ENTITY_TYPES,
  LEGEND_ORDER,
  type EntityTypeCode,
} from '@/lib/entity-types';

export interface SelectionInfo {
  /** Where to anchor the toolbar (cursor position in viewport coords). */
  anchor: { x: number; y: number };
  /** Selected text (what the user sees). */
  text: string;
  /** Plain-text offsets in the ORIGINAL document (left-pane space). */
  start: number;
  end: number;
  /** Which pane the selection was made in — useful for debugging. */
  pane: 'left' | 'right';
}

interface SelectionToolbarProps {
  selection: SelectionInfo | null;
  busy?: boolean;
  error?: string | null;
  onAddEntity: (info: SelectionInfo, entityType: EntityTypeCode | string) => void;
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
  const customInputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const [customValue, setCustomValue] = useState('');
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  // Reset the expanded state whenever we get a fresh selection.
  useEffect(() => {
    setOpen(false);
    setCustomMode(false);
    setCustomValue('');
  }, [selection?.start, selection?.end, selection?.pane]);

  // Auto-focus the custom input when entering custom mode.
  useEffect(() => {
    if (customMode) customInputRef.current?.focus();
  }, [customMode]);

  useLayoutEffect(() => {
    if (!selection) {
      setPosition(null);
      return;
    }
    const el = ref.current;
    const width = el?.offsetWidth ?? 200;
    const height = el?.offsetHeight ?? 44;
    const gap = 10;
    const margin = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // Default: position the toolbar BELOW the cursor, centered on X.
    let top = selection.anchor.y + gap;
    let left = selection.anchor.x - width / 2;

    // Flip above if there is not enough room below.
    if (top + height > vh - margin) {
      top = selection.anchor.y - height - gap;
    }

    // Clamp horizontally and vertically inside the viewport.
    left = Math.min(Math.max(left, margin), vw - width - margin);
    top = Math.min(Math.max(top, margin), vh - height - margin);

    setPosition({ top, left });
    // Recalculate when open/customMode change — height changes significantly.
  }, [selection, open, customMode]);

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
      className={`cleargate-selection ${open ? 'cleargate-selection--open' : ''}`}
      style={{
        top: position?.top ?? -9999,
        left: position?.left ?? -9999,
      }}
      // Prevent selection loss / mouseup bubbling from eating clicks on
      // the toolbar buttons themselves.
      onMouseDown={(e) => {
        if ((e.target as Element)?.tagName !== 'INPUT') e.preventDefault();
      }}
    >
      {!open ? (
        <button
          type="button"
          className="cleargate-selection__primary"
          onClick={() => setOpen(true)}
          disabled={busy}
        >
          <span className="cleargate-selection__icon" aria-hidden>+</span>
          {busy ? t('selection.adding') : t('selection.addAs')}        </button>
      ) : (
        <div className="cleargate-selection__types">
          <div className="cleargate-selection__title">{t('selection.pickType')}</div>
          {!customMode ? (
            <>
              <ul>
                {LEGEND_ORDER.map((code) => {
                  const info = ENTITY_TYPES[code as EntityTypeCode];
                  const label = locale === 'ru' ? info.labelRu : info.labelEn;
                  return (
                    <li key={code}>
                      <button
                        type="button"
                        className="cleargate-selection__type"
                        onClick={() => onAddEntity(selection, code)}
                        disabled={busy}
                      >
                        <span
                          className={`cleargate-selection__swatch cleargate-entity--${info.cssKey}`}
                          aria-hidden
                        />
                        {label}
                      </button>
                    </li>
                  );
                })}
              </ul>
              <button
                type="button"
                className="cleargate-selection__custom-toggle"
                onClick={() => setCustomMode(true)}
                disabled={busy}
              >
                {t('selection.customType')}
              </button>
            </>
          ) : (
            <div className="cleargate-selection__custom-input">
              <input
                ref={customInputRef}
                type="text"
                className="cleargate-selection__custom-field"
                placeholder={t('selection.customPlaceholder')}
                value={customValue}
                onChange={(e) => setCustomValue(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === 'Enter' && customValue.trim()) {
                    onAddEntity(selection, customValue.trim().toUpperCase());
                  } else if (e.key === 'Escape') {
                    setCustomMode(false);
                    setCustomValue('');
                  }
                }}
                onKeyUp={(e) => e.stopPropagation()}
                disabled={busy}
              />
              <button
                type="button"
                className="cleargate-selection__custom-confirm"
                onClick={() => {
                  if (customValue.trim()) {
                    onAddEntity(selection, customValue.trim().toUpperCase());
                  }
                }}
                disabled={busy || !customValue.trim()}
              >
                {t('selection.addAs')}
              </button>
            </div>
          )}
          {error && <div className="cleargate-selection__error">{error}</div>}
        </div>
      )}
    </div>
  );
}
