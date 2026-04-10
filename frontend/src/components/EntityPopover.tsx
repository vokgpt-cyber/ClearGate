'use client';

/**
 * EntityPopover — floating action menu shown when the user clicks a
 * highlighted entity in either pane.
 *
 * Actions:
 *   - Accept  — mark the entity as confirmed (visual: solid underline,
 *               slightly muted fill).
 *   - Reject  — "Do not anonymize" — the left pane keeps a dashed
 *               rejected style and the right pane restores the original
 *               text for this span.
 *   - Change type → submenu with every known EntityTypeCode. Switches
 *               the category (and consequently the placeholder).
 *   - Remove  — only offered for `custom` (user-added) entities.
 *
 * This component is purely presentational: it receives handlers from
 * SplitWorkspace and the list of known types from entity-types.ts.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocale } from '@/hooks/useLocale';
import {
  ENTITY_TYPES,
  LEGEND_ORDER,
  getEntityTypeInfo,
  type EntityTypeCode,
} from '@/lib/entity-types';
import type { InteractiveEntity } from '@/lib/entity-overlay';

export interface EntityPopoverAnchor {
  /** Viewport-relative anchor rectangle (usually the clicked mark's bounding rect). */
  rect: DOMRect;
  /** The entity the popover is acting on. */
  entity: InteractiveEntity;
}

interface EntityPopoverProps {
  anchor: EntityPopoverAnchor | null;
  onAccept: (entity: InteractiveEntity) => void;
  onReject: (entity: InteractiveEntity) => void;
  onChangeType: (entity: InteractiveEntity, newType: string) => void;
  onRemove: (entity: InteractiveEntity) => void;
  onClose: () => void;
}

export function EntityPopover({
  anchor,
  onAccept,
  onReject,
  onChangeType,
  onRemove,
  onClose,
}: EntityPopoverProps) {
  const { locale, t } = useLocale();
  const ref = useRef<HTMLDivElement | null>(null);
  const [submenuOpen, setSubmenuOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  // Recompute position whenever the anchor changes. We position the
  // popover just below the anchor rect, keeping it clamped inside the
  // viewport so it never overflows.
  useLayoutEffect(() => {
    if (!anchor) {
      setPosition(null);
      setSubmenuOpen(false);
      return;
    }
    const el = ref.current;
    const width = el?.offsetWidth ?? 220;
    const height = el?.offsetHeight ?? 140;
    const margin = 8;
    const gap = 6;
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let top = anchor.rect.bottom + gap;
    // If it would overflow below, flip to above.
    if (top + height > vh - margin) {
      top = Math.max(margin, anchor.rect.top - height - gap);
    }
    let left = anchor.rect.left + anchor.rect.width / 2 - width / 2;
    left = Math.min(Math.max(left, margin), vw - width - margin);
    setPosition({ top, left });
  }, [anchor]);

  // Dismiss on Escape or outside click.
  useEffect(() => {
    if (!anchor) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const handleClick = (e: MouseEvent) => {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener('keydown', handleKey);
    // Delay outside-click registration so the click that opened us
    // doesn't immediately close us.
    const t = window.setTimeout(() => {
      window.addEventListener('mousedown', handleClick);
    }, 0);
    return () => {
      window.removeEventListener('keydown', handleKey);
      window.clearTimeout(t);
      window.removeEventListener('mousedown', handleClick);
    };
  }, [anchor, onClose]);

  if (!anchor) return null;

  const { entity } = anchor;
  const info = getEntityTypeInfo(entity.entity_type);
  const label = locale === 'ru' ? info.labelRu : info.labelEn;
  const isCustom = entity.state === 'custom';

  return (
    <div
      ref={ref}
      className="velum-popover"
      role="menu"
      style={{
        top: position?.top ?? -9999,
        left: position?.left ?? -9999,
      }}
    >
      <div className="velum-popover__header">
        <span className={`velum-popover__swatch velum-entity--${info.cssKey}`} aria-hidden />
        <span className="velum-popover__title">{label}</span>
        <span className="velum-popover__text" title={entity.text}>
          {truncate(entity.text, 36)}
        </span>
      </div>
      {!submenuOpen ? (
        <ul className="velum-popover__list" role="menu">
          {entity.state !== 'accepted' && (
            <li>
              <button
                type="button"
                role="menuitem"
                className="velum-popover__action velum-popover__action--accept"
                onClick={() => onAccept(entity)}
              >
                <span className="velum-popover__icon" aria-hidden>✓</span>
                {entity.state === 'rejected'
                  ? t('popover.reanonymize')
                  : t('popover.accept')}
              </button>
            </li>
          )}
          {entity.state !== 'rejected' && (
            <li>
              <button
                type="button"
                role="menuitem"
                className="velum-popover__action velum-popover__action--reject"
                onClick={() => onReject(entity)}
              >
                <span className="velum-popover__icon" aria-hidden>∅</span>
                {t('popover.reject')}
              </button>
            </li>
          )}
          <li>
            <button
              type="button"
              role="menuitem"
              className="velum-popover__action"
              onClick={() => setSubmenuOpen(true)}
            >
              <span className="velum-popover__icon" aria-hidden>⇌</span>
              {t('popover.changeType')}
            </button>
          </li>
          {isCustom && (
            <li>
              <button
                type="button"
                role="menuitem"
                className="velum-popover__action velum-popover__action--danger"
                onClick={() => onRemove(entity)}
              >
                <span className="velum-popover__icon" aria-hidden>×</span>
                {t('popover.remove')}
              </button>
            </li>
          )}
        </ul>
      ) : (
        <div className="velum-popover__submenu">
          <div className="velum-popover__submenu-title">
            {t('popover.pickType')}
          </div>
          <ul className="velum-popover__types">
            {LEGEND_ORDER.map((code) => {
              const typeInfo = ENTITY_TYPES[code as EntityTypeCode];
              const typeLabel = locale === 'ru' ? typeInfo.labelRu : typeInfo.labelEn;
              const current = code === entity.entity_type;
              return (
                <li key={code}>
                  <button
                    type="button"
                    role="menuitem"
                    className={`velum-popover__type ${
                      current ? 'velum-popover__type--current' : ''
                    }`}
                    onClick={() => onChangeType(entity, code)}
                    disabled={current}
                  >
                    <span
                      className={`velum-popover__swatch velum-entity--${typeInfo.cssKey}`}
                      aria-hidden
                    />
                    {typeLabel}
                  </button>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            className="velum-popover__back"
            onClick={() => setSubmenuOpen(false)}
          >
            ← {t('popover.cancel')}
          </button>
        </div>
      )}
    </div>
  );
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + '…';
}
