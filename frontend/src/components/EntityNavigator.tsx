'use client';

import { useState, useMemo } from 'react';
import { useLocale } from '@/hooks/useLocale';
import { getEntityColor } from '@/lib/colors';
import type { DetectedEntity } from '@/types/entities';

interface EntityNavigatorProps {
  entities: DetectedEntity[];
  onEntityClick?: (entity: DetectedEntity) => void;
}

export function EntityNavigator({ entities, onEntityClick }: EntityNavigatorProps) {
  const { t } = useLocale();
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(new Set());

  const grouped = useMemo(() => {
    const groups: Record<string, DetectedEntity[]> = {};
    for (const e of entities) {
      (groups[e.entity_type] ??= []).push(e);
    }
    return Object.entries(groups).sort(([, a], [, b]) => b.length - a.length);
  }, [entities]);

  const toggleType = (type: string) => {
    setExpandedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type); else next.add(type);
      return next;
    });
  };

  if (entities.length === 0) {
    return (
      <div style={{
        padding: '1.5rem 1rem',
        color: 'var(--text-muted)',
        fontSize: '0.8125rem',
        fontStyle: 'italic',
        textAlign: 'center',
      }}>
        {t('session.noEntities')}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '0.75rem 1rem',
        borderBottom: '1px solid var(--border)',
        fontSize: '0.75rem',
        fontWeight: 600,
        color: 'var(--text-secondary)',
        display: 'flex',
        justifyContent: 'space-between',
      }}>
        <span>{t('session.entities')}</span>
        <span style={{ color: 'var(--text-muted)' }}>{entities.length}</span>
      </div>

      {/* Grouped list */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0.25rem 0' }}>
        {grouped.map(([type, items]) => {
          const color = getEntityColor(type);
          const isOpen = expandedTypes.has(type);
          const typeLabel = t(`entity.types.${type}`) || type;

          return (
            <div key={type}>
              {/* Group header */}
              <button
                onClick={() => toggleType(type)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  width: '100%', padding: '0.5rem 1rem',
                  border: 'none', backgroundColor: 'transparent',
                  cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600,
                  color: 'var(--text-primary)', textAlign: 'left',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  <span style={{
                    width: '8px', height: '8px', borderRadius: '2px',
                    backgroundColor: color.bg, border: `1px solid ${color.border}`,
                  }} />
                  {typeLabel}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.6875rem' }}>
                  {isOpen ? '\u25BE' : '\u25B8'} {items.length}
                </span>
              </button>

              {/* Expanded items */}
              {isOpen && (
                <div style={{ padding: '0 0.5rem 0.25rem 1.5rem' }}>
                  {items.map((entity, i) => (
                    <button
                      key={`${entity.start}-${i}`}
                      onClick={() => onEntityClick?.(entity)}
                      style={{
                        display: 'block', width: '100%', textAlign: 'left',
                        padding: '0.25rem 0.5rem', marginBottom: '1px',
                        border: 'none', borderRadius: '2px',
                        backgroundColor: 'transparent',
                        cursor: 'pointer', fontSize: '0.75rem',
                        color: 'var(--text-primary)',
                      }}
                      title={`Score: ${entity.score.toFixed(2)} | ${entity.source_layer}`}
                    >
                      <span style={{
                        backgroundColor: color.bg, color: color.text,
                        padding: '0.0625rem 0.25rem', borderRadius: '2px',
                        fontSize: '0.6875rem',
                      }}>
                        {entity.text.length > 35 ? entity.text.slice(0, 35) + '\u2026' : entity.text}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
