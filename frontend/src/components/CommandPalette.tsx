'use client';

/**
 * CommandPalette — Cmd/Ctrl+K modal for quick navigation and actions.
 *
 * Grouped commands:
 *   - "Документы" (docs) — current sessions
 *   - "Действия" (actions) — upload, anonymize, export
 *   - "Навигация" (nav) — home, admin (if authorized)
 */

import { useEffect, useState, useCallback } from 'react';
import { Command } from 'cmdk';
import { useRouter } from 'next/navigation';
import { useLocale } from '@/hooks/useLocale';
import { useAuth } from '@/hooks/useAuth';

interface CommandPaletteProps {
  sessions: Array<{ id: string; title: string }>;
  onOpenDocument: () => void;
}

export function CommandPalette({ sessions, onOpenDocument }: CommandPaletteProps) {
  const { t } = useLocale();
  const router = useRouter();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const isAdmin = user?.role === 'admin';

  // Ctrl+K / Cmd+K opens the palette
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(!open);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  const handleSelectSession = useCallback((sessionId: string) => {
    setOpen(false);
    // The parent page.tsx will handle switching to this session
  }, []);

  const handleNavigate = useCallback((path: string) => {
    setOpen(false);
    router.push(path);
  }, [router]);

  if (!open) return null;

  return (
    <div className="cleargate-cmdk-overlay" onClick={() => setOpen(false)}>
      <Command className="cleargate-cmdk-dialog" onClick={(e) => e.stopPropagation()}>
        <Command.Input
          placeholder={t('cmdk.placeholder') || 'Type a command...'}
          className="cleargate-cmdk-input"
        />
        <Command.List className="cleargate-cmdk-list">
          <Command.Empty>{t('cmdk.noResults') || 'No results found.'}</Command.Empty>

          {/* Documents */}
          {sessions.length > 0 && (
            <Command.Group heading={t('cmdk.documents') || 'Документы'}>
              {sessions.map((session) => (
                <Command.Item
                  key={session.id}
                  value={session.id}
                  onSelect={handleSelectSession}
                  className="cleargate-cmdk-item"
                >
                  {session.title}
                </Command.Item>
              ))}
            </Command.Group>
          )}

          {/* Actions */}
          <Command.Group heading={t('cmdk.actions') || 'Действия'}>
            <Command.Item
              value="upload-document"
              onSelect={onOpenDocument}
              className="cleargate-cmdk-item"
            >
              {t('cmdk.uploadDocument') || 'Загрузить документ'}
            </Command.Item>
            <Command.Item
              value="anonymize"
              onSelect={() => {
                // This would be triggered by the workspace
                setOpen(false);
              }}
              className="cleargate-cmdk-item"
            >
              {t('cmdk.anonymize') || 'Анонимизировать'}
            </Command.Item>
            <Command.Item
              value="export"
              onSelect={() => {
                setOpen(false);
              }}
              className="cleargate-cmdk-item"
            >
              {t('cmdk.exportDocx') || 'Экспорт DOCX'}
            </Command.Item>
          </Command.Group>

          {/* Navigation */}
          <Command.Group heading={t('cmdk.navigation') || 'Навигация'}>
            <Command.Item
              value="home"
              onSelect={() => handleNavigate('/')}
              className="cleargate-cmdk-item"
            >
              {t('cmdk.home') || 'Главная'}
            </Command.Item>
            {isAdmin && (
              <Command.Item
                value="admin"
                onSelect={() => handleNavigate('/admin')}
                className="cleargate-cmdk-item"
              >
                {t('cmdk.admin') || 'Администратор'}
              </Command.Item>
            )}
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}
