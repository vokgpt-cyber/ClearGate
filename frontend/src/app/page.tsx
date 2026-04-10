'use client';

/**
 * VELUM — root page.
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

import { useCallback, useState } from 'react';
import { Header } from '@/components/Header';
import { Sidebar } from '@/components/Sidebar';
import { EmptyState } from '@/components/EmptyState';
import { SplitWorkspace } from '@/components/SplitWorkspace';
import { createSession, uploadDocx } from '@/lib/api';

interface LoadedDoc {
  sessionId: string;
  name: string;
  openedAt: number;
}

export default function Home() {
  const [sessions, setSessions] = useState<LoadedDoc[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isPicking, setIsPicking] = useState(false);
  const [isWorking, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(async (file: File) => {
    setWorking(true);
    setError(null);
    try {
      const session = await createSession();
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

  return (
    <div className="velum-app">
      <Sidebar
        sessions={sidebarSessions}
        activeSessionId={showWorkspace ? activeDoc.sessionId : null}
        onNewDocument={handleNewDocument}
        onSelectSession={handleSelectSession}
      />
      <div className="velum-app__main">
        <Header />
        <div className="velum-app__content">
          {showWorkspace ? (
            <SplitWorkspace
              key={activeDoc.sessionId}
              documentId={activeDoc.sessionId}
              documentName={activeDoc.name}
              onClose={handleClose}
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
    </div>
  );
}
