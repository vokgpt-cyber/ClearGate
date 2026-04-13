'use client';

/**
 * Sidebar — left navigation column, Harvey/EPAM style.
 *
 * Iteration 1 scope:
 *   - VELUM brand mark at the top
 *   - "New document" button (primary action, burgundy accent)
 *   - A static placeholder list showing the currently-loaded session
 *     (or an empty-state message). Full session history / Matters list
 *     comes in iteration 7.
 *
 * Deliberately restrained: no icons library, no animations, no fluff.
 * Strict serif brand type + thin dividers + lots of whitespace.
 */

import { useLocale } from '@/hooks/useLocale';

interface SidebarSessionItem {
  id: string;
  title: string;
  /** Unix ms when the session was opened. */
  openedAt: number;
}

interface SidebarProps {
  sessions: SidebarSessionItem[];
  activeSessionId: string | null;
  onNewDocument: () => void;
  onSelectSession?: (id: string) => void;
}

export function Sidebar({
  sessions,
  activeSessionId,
  onNewDocument,
  onSelectSession,
}: SidebarProps) {
  const { t } = useLocale();

  return (
    <aside className="velum-sidebar">
      <div className="velum-sidebar__brand">
        <div className="velum-sidebar__brand-bar" aria-hidden />
        <div className="velum-sidebar__brand-text">
          <span className="velum-sidebar__brand-name">VELUM</span>
        </div>
      </div>

      <button
        type="button"
        className="velum-sidebar__new-btn"
        onClick={onNewDocument}
      >
        <span className="velum-sidebar__new-btn-plus" aria-hidden>
          +
        </span>
        <span>{t('sidebar.newDocument')}</span>
      </button>

      <div className="velum-sidebar__section-label">
        {t('sidebar.recentSessions')}
      </div>

      <div className="velum-sidebar__list">
        {sessions.length === 0 ? (
          <div className="velum-sidebar__empty">{t('sidebar.noSessions')}</div>
        ) : (
          sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`velum-sidebar__item ${
                s.id === activeSessionId ? 'is-active' : ''
              }`}
              onClick={() => onSelectSession?.(s.id)}
              title={s.title}
            >
              <span className="velum-sidebar__item-title">{s.title}</span>
              <span className="velum-sidebar__item-meta">
                {formatRelative(s.openedAt)}
              </span>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}

function formatRelative(openedAt: number): string {
  const diffSec = Math.floor((Date.now() - openedAt) / 1000);
  if (diffSec < 60) return 'сейчас';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} мин`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} ч`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay} д`;
}
