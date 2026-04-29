'use client';

/**
 * CLEARGATE — root page.
 *
 * Shell layout:
 *   ┌──────────┬────────────────────────────────────────┐
 *   │          │ Header (brand status, locale, theme)   │
 *   │ Sidebar  ├────────────────────────────────────────┤
 *   │          │ SplitWorkspace  /or/  EmptyState       │
 *   └──────────┴────────────────────────────────────────┘
 *
 * We now maintain a *list* of uploaded sessions so the user can open
 * several documents in one run and freely switch between them via the
 * sidebar. Each session owns its own SplitWorkspace instance (keyed by
 * sessionId) so the anonymization state of one document never leaks
 * into another.
 */

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Header } from '@/components/Header';
import { Sidebar } from '@/components/Sidebar';
import { EmptyState } from '@/components/EmptyState';
import { SplitWorkspace } from '@/components/SplitWorkspace';
import { CommandPalette } from '@/components/CommandPalette';
import { FeedbackWidget } from '@/components/FeedbackWidget';
import { createSession, listSessions, uploadDocx } from '@/lib/api';
import { useAuth } from '@/hooks/useAuth';
import { useLocale } from '@/hooks/useLocale';
import type { InteractiveEntity } from '@/lib/entity-overlay';

interface LoadedDoc {
  sessionId: string;
  name: string;
  openedAt: number;
}

export default function Home() {
  // Protected-route gate. While the initial /me probe is running we
  // render a minimal loading card instead of the full shell; once it
  // resolves, an unauthenticated caller is redirected to /login and
  // the hook below bails out before fetching any protected data.
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();
  const { t } = useLocale();
  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
    }
  }, [authLoading, user, router]);
  const isAuthed = !!user;

  const [sessions, setSessions] = useState<LoadedDoc[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isPicking, setIsPicking] = useState(false);
  const [isWorking, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [entityCache, setEntityCache] = useState<Record<string, InteractiveEntity[]>>({});

  const handleAnonymizationComplete = useCallback(
    (sessionId: string, entities: InteractiveEntity[]) => {
      setEntityCache((prev) => ({ ...prev, [sessionId]: entities }));
    },
    [],
  );

  // Restore persisted sessions from the backend on mount — but only
  // once the auth check has confirmed the user is signed in. Firing
  // listSessions() while unauthenticated triggers an avoidable 401
  // that clutters the backend logs and confuses pilot operators.
  useEffect(() => {
    if (!isAuthed) return;
    let cancelled = false;
    listSessions()
      .then((metas) => {
        if (cancelled || metas.length === 0) return;
        const restored: LoadedDoc[] = metas
          .filter((m) => m.has_document)
          .map((m) => ({
            sessionId: m.session_id,
            name: m.docx_filename ?? 'Untitled',
            openedAt: new Date(m.created_at).getTime(),
          }));
        if (restored.length > 0) {
          setSessions(restored);
          setActiveId(restored[0].sessionId);
        }
      })
      .catch(() => {
        // Backend may not be ready yet — silently ignore
      });
    return () => { cancelled = true; };
  }, [isAuthed]);

  const handleFile = useCallback(async (file: File) => {
    setWorking(true);
    setError(null);
    try {
      const session = await createSession('ru', { enableLlmLayer: true });
      await uploadDocx(session.session_id, file);
      const doc: LoadedDoc = {
        sessionId: session.session_id,
        name: file.name,
        openedAt: Date.now(),
      };
      setSessions((prev) => [doc, ...prev]);
      setActiveId(doc.sessionId);
      setIsPicking(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  }, []);

  const handleNewDocument = useCallback(() => {
    setIsPicking(true);
    setError(null);
  }, []);

  const handleClose = useCallback(() => {
    setIsPicking(true);
    setError(null);
  }, []);

  const handleSelectSession = useCallback((id: string) => {
    setActiveId(id);
    setIsPicking(false);
  }, []);

  const activeDoc = activeId
    ? sessions.find((s) => s.sessionId === activeId) ?? null
    : null;

  const sidebarSessions = sessions.map((s) => ({
    id: s.sessionId,
    title: s.name,
    openedAt: s.openedAt,
  }));

  const showWorkspace = activeDoc && !isPicking;

  // Render a neutral splash until the auth state is resolved; once
  // resolved, unauthenticated callers are being redirected to /login
  // by the effect above, so we don't leak any protected UI.
  if (authLoading || !isAuthed) {
    return (
      <div className="cg-login cg-login--loading">
        <div className="cg-login__checking">{t('auth.checking')}</div>
      </div>
    );
  }

  return (
    <div className="cleargate-app">
      <Sidebar
        sessions={sidebarSessions}
        activeSessionId={showWorkspace ? activeDoc.sessionId : null}
        onNewDocument={handleNewDocument}
        onSelectSession={handleSelectSession}
      />
      <div className="cleargate-app__main">
        <Header />
        <div className="cleargate-app__content">
          {showWorkspace ? (
            <SplitWorkspace
              key={activeDoc.sessionId}
              documentId={activeDoc.sessionId}
              documentName={activeDoc.name}
              onClose={handleClose}
              initialEntities={entityCache[activeDoc.sessionId] ?? []}
              onAnonymizationComplete={handleAnonymizationComplete}
            />
          ) : (
            <EmptyState
              onFile={handleFile}
              isWorking={isWorking}
              error={error}
            />
          )}
        </div>
      </div>
      <CommandPalette
        sessions={sidebarSessions}
        onOpenDocument={handleNewDocument}
      />
      <FeedbackWidget />
    </div>
  );
}
