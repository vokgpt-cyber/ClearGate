'use client';

/**
 * Sidebar — left navigation column, Harvey/EPAM style.
 *
 * Iteration 1 scope:
 *   - CLEARGATE brand mark at the top
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
  onDeleteSession?: (id: string) => void;
}

export function Sidebar({
  sessions,
  activeSessionId,
  onNewDocument,
  onSelectSession,
  onDeleteSession,
}: SidebarProps) {
  const { t } = useLocale();

  return (
    <aside className="cleargate-sidebar">
      <div className="cleargate-sidebar__brand">
        <div className="cleargate-sidebar__brand-bar" aria-hidden />
        <div className="cleargate-sidebar__brand-text">
          <span className="cleargate-sidebar__brand-name">CLEARGATE</span>
        </div>
      </div>

      <button
        type="button"
        className="cleargate-sidebar__new-btn"
        onClick={onNewDocument}
      >
        <span className="cleargate-sidebar__new-btn-plus" aria-hidden>
          +
        </span>
        <span>{t('sidebar.newDocument')}</span>
      </button>

      <div className="cleargate-sidebar__section-label">
        {t('sidebar.recentSessions')}
      </div>

      <div className="cleargate-sidebar__list">
        {sessions.length === 0 ? (
          <div className="cleargate-sidebar__empty">{t('sidebar.noSessions')}</div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`cleargate-sidebar__item ${
                s.id === activeSessionId ? 'is-active' : ''
              }`}
            >
              <button
                type="button"
                className="cleargate-sidebar__item-main"
                onClick={() => onSelectSession?.(s.id)}
                title={s.title}
              >
                <span className="cleargate-sidebar__item-title">{s.title}</span>
                <span className="cleargate-sidebar__item-meta">
                  {formatRelative(s.openedAt)}
                </span>
              </button>
              {onDeleteSession && (
                <button
                  type="button"
                  className="cleargate-sidebar__item-delete"
                  onClick={() => onDeleteSession(s.id)}
                  title={t('sidebar.deleteSession')}
                  aria-label={`${t('sidebar.deleteSession')}: ${s.title}`}
                >
                  x
                </button>
              )}
            </div>
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
