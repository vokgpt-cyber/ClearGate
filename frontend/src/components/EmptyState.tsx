'use client';

/**
 * EmptyState — shown when no document is loaded yet.
 *
 * A large, calm drop zone with a clear call-to-action and a short
 * statement of what CLEARGATE does. Harvey/Legal-tech style: confident and
 * restrained, not playful.
 */

import { useCallback, useRef, useState } from 'react';
import { useLocale } from '@/hooks/useLocale';

interface EmptyStateProps {
  onFile: (file: File) => void;
  onFiles?: (files: File[]) => void;
  isWorking?: boolean;
  error?: string | null;
}

export function EmptyState({ onFile, onFiles, isWorking, error }: EmptyStateProps) {
  const { t } = useLocale();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = Array.from(e.dataTransfer.files ?? []).filter((file) => {
        const lowerName = file.name.toLowerCase();
        return (
          lowerName.endsWith('.docx') ||
          lowerName.endsWith('.pdf') ||
          lowerName.endsWith('.txt')
        );
      });
      if (files.length === 0) return;
      if (files.length === 1) onFile(files[0]);
      else onFiles?.(files);
    },
    [onFile, onFiles],
  );

  return (
    <div
      className={`cleargate-empty ${dragging ? 'is-drag' : ''}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <div className="cleargate-empty__card">
        <div className="cleargate-empty__eyebrow">{t('empty.eyebrow')}</div>
        <h1 className="cleargate-empty__title">{t('empty.title')}</h1>
        <p className="cleargate-empty__lede">{t('empty.lede')}</p>

        <button
          type="button"
          className="cleargate-empty__cta"
          onClick={() => inputRef.current?.click()}
          disabled={isWorking}
        >
          {isWorking ? t('empty.working') : t('empty.pick')}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".docx,.pdf,.txt"
          multiple
          style={{ display: 'none' }}
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length === 1) onFile(files[0]);
            if (files.length > 1) onFiles?.(files);
            e.target.value = '';
          }}
        />
        <div className="cleargate-empty__hint">{t('empty.hint')}</div>
        {error && <div className="cleargate-empty__error">{error}</div>}
      </div>
    </div>
  );
}
