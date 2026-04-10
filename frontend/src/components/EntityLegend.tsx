'use client';

/**
 * EntityLegend — footer strip showing a colour swatch and count for
 * each detected entity type, plus a rolling status indicator while
 * detection is in flight.
 *
 * Iteration 3: the legend is now interactive. Clicking a chip toggles
 * its type between visible and hidden (hidden types are not overlaid
 * on either pane). A separate toggle hides all already-reviewed
 * entities so the user can focus on what still needs attention. A
 * reset button clears every filter.
 *
 * Rendered at the bottom of SplitWorkspace. Order of items follows
 * LEGEND_ORDER from `entity-types.ts`, with any unknown types appended
 * at the end.
 */

import { useMemo } from 'react';
import { useLocale } from '@/hooks/useLocale';
import {
  ENTITY_TYPES,
  LEGEND_ORDER,
  getEntityTypeInfo,
  type EntityTypeCode,
} from '@/lib/entity-types';

export type LegendStatus = 'idle' | 'detecting' | 'detected' | 'error';

interface EntityLegendProps {
  counts: Map<string, number>;
  totalEntities: number;
  visibleEntities: number;
  hiddenTypes: Set<string>;
  onlyUnconfirmed: boolean;
  status: LegendStatus;
  error?: string | null;
  onToggleType: (code: string) => void;
  onToggleOnlyUnconfirmed: () => void;
  onResetFilters: () => void;
}

export function EntityLegend({
  counts,
  totalEntities,
  visibleEntities,
  hiddenTypes,
  onlyUnconfirmed,
  status,
  error,
  onToggleType,
  onToggleOnlyUnconfirmed,
  onResetFilters,
}: EntityLegendProps) {
  const { locale, t } = useLocale();

  const items = useMemo(() => {
    const known = new Set<string>();
    const ordered: { code: string; count: number }[] = [];

    for (const code of LEGEND_ORDER) {
      const n = counts.get(code) ?? 0;
      if (n > 0) {
        ordered.push({ code, count: n });
        known.add(code);
      }
    }
    for (const [code, n] of counts) {
      if (!known.has(code) && n > 0) {
        ordered.push({ code, count: n });
      }
    }
    return ordered;
  }, [counts]);

  const labelFor = (code: string): string => {
    const info = getEntityTypeInfo(code);
    return locale === 'ru' ? info.labelRu : info.labelEn;
  };

  const anyFilter = hiddenTypes.size > 0 || onlyUnconfirmed;

  return (
    <div className="velum-legend" role="status" aria-live="polite">
      <span className="velum-legend__title">{t('legend.title')}</span>

      {status === 'detecting' && totalEntities === 0 && (
        <span className="velum-legend__status velum-legend__status--working">
          {t('legend.detecting')}
        </span>
      )}

      {status === 'detected' && totalEntities === 0 && (
        <span className="velum-legend__status">{t('legend.none')}</span>
      )}

      {status === 'error' && (
        <span className="velum-legend__error">
          {t('legend.error')}: {error ?? 'unknown'}
        </span>
      )}

      {items.map(({ code, count }) => {
        const cssKey =
          ENTITY_TYPES[code as EntityTypeCode]?.cssKey ??
          getEntityTypeInfo(code).cssKey;
        const hidden = hiddenTypes.has(code);
        return (
          <button
            key={code}
            type="button"
            className={`velum-legend__item ${
              hidden ? 'velum-legend__item--hidden' : ''
            }`}
            onClick={() => onToggleType(code)}
            title={labelFor(code)}
            aria-pressed={!hidden}
          >
            <span
              className={`velum-legend__swatch velum-entity--${cssKey}`}
              aria-hidden
            />
            <span className="velum-legend__label">{labelFor(code)}</span>
            <span className="velum-legend__count">{count}</span>
          </button>
        );
      })}

      {totalEntities > 0 && (
        <button
          type="button"
          className={`velum-legend__toggle ${
            onlyUnconfirmed ? 'velum-legend__toggle--on' : ''
          }`}
          onClick={onToggleOnlyUnconfirmed}
          aria-pressed={onlyUnconfirmed}
        >
          {t('legend.onlyUnconfirmed')}
        </button>
      )}

      {anyFilter && (
        <button
          type="button"
          className="velum-legend__reset"
          onClick={onResetFilters}
          title={t('legend.resetFilters')}
        >
          {t('legend.resetFilters')}
        </button>
      )}

      {status === 'detected' && totalEntities > 0 && (
        <span className="velum-legend__status">
          {t('legend.total')}: {visibleEntities === totalEntities
            ? totalEntities
            : `${visibleEntities}/${totalEntities}`}
        </span>
      )}
    </div>
  );
}
