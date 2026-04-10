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
import { logSel } from '@/lib/debug-log';
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

  // [Velum/sel] diagnostic log I — every render of the toolbar
  logSel('I toolbar render', {
    hasSelection: !!selection,
    pane: selection?.pane,
    start: selection?.start,
    end: selection?.end,
    position,
  });

  // Reset the expanded state whenever we get a fresh selection.
  useEffect(() => {
    setOpen(false);
  }, [selection?.start, selection?.end, selection?.pane]);

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

    // [Velum/sel] diagnostic log J — layout pass
    logSel('J toolbar layout', {
      hasRef: !!el,
      width,
      height,
      vw,
      vh,
      anchor: selection.anchor,
      top,
      left,
    });

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
      // Prevent selection loss / mouseup bubbling from eating clicks on
      // the toolbar buttons themselves.
      onMouseDown={(e) => e.preventDefault()}
    >
      {!open ? (
        <button
          type="button"
          className="velum-selection__primary"
          onClick={() => setOpen(true)}
          disabled={busy}
        >
          <span className="velum-selection__icon" aria-hidden>+</span>
          {busy ? t('selection.adding') : t('selection.addAs')}        </button>
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
