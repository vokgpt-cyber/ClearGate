'use client';

import { useState, useCallback } from 'react';
import { Header } from '@/components/Header';
import { SplitScreen } from '@/components/SplitScreen';
import { LLMPanel } from '@/components/LLMPanel';
import { EntityNavigator } from '@/components/EntityNavigator';
import type { DetectedEntity } from '@/types/entities';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [anonymizedText, setAnonymizedText] = useState('');
  const [entities, setEntities] = useState<DetectedEntity[]>([]);

  const handleAnonymized = useCallback(
    (sid: string, text: string, ents: DetectedEntity[]) => {
      setSessionId(sid);
      setAnonymizedText(text);
      setEntities(ents);
    },
    [],
  );

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100vh', backgroundColor: 'var(--bg-primary)',
      color: 'var(--text-primary)',
    }}>
      {/* Header */}
      <Header sessionEntityCount={entities.length} />

      {/* Main area: SplitScreen + Entity Navigator */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Center: SplitScreen */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Split editor */}
          <div style={{ flex: 1, minHeight: 0 }}>
            <SplitScreen onAnonymized={handleAnonymized} />
          </div>

          {/* LLM Panel — bottom of center column */}
          <LLMPanel sessionId={sessionId} anonymizedText={anonymizedText} />
        </div>

        {/* Right sidebar: Entity Navigator */}
        <div style={{
          width: 'var(--entity-panel-width)',
          borderLeft: '1px solid var(--border)',
          backgroundColor: 'var(--bg-primary)',
          overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
        }}>
          <EntityNavigator entities={entities} />
        </div>
      </div>
    </div>
  );
}
