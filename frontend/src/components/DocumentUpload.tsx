'use client';

import { useState, useCallback, useRef } from 'react';
import { useLocale } from '@/hooks/useLocale';

interface DocumentUploadProps {
  onTextLoaded: (text: string) => void;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const ACCEPTED = '.docx,.pdf,.txt';
const MAX_SIZE = 50 * 1024 * 1024; // 50 MB

export function DocumentUpload({ onTextLoaded }: DocumentUploadProps) {
  const { t } = useLocale();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFile = useCallback(async (file: File) => {
    if (file.size > MAX_SIZE) {
      setError('File too large (max 50 MB)');
      return;
    }

    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!ext || !['docx', 'pdf', 'txt'].includes(ext)) {
      setError('Unsupported format. Use DOCX, PDF, or TXT.');
      return;
    }

    setIsUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const resp = await fetch(`${API_URL}/api/documents/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const msg = await resp.text();
        throw new Error(msg);
      }

      const data = await resp.json();
      onTextLoaded(data.text);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  }, [onTextLoaded]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }, [uploadFile]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
  }, [uploadFile]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      style={{
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        padding: '2rem',
        border: `2px dashed ${isDragging ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: '4px',
        backgroundColor: isDragging ? 'var(--bg-secondary)' : 'transparent',
        cursor: 'pointer',
        transition: 'all 0.15s',
        minHeight: '120px',
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        onChange={handleFileInput}
        style={{ display: 'none' }}
      />

      {isUploading ? (
        <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
          Uploading...
        </span>
      ) : (
        <>
          <span style={{
            fontSize: '0.875rem', color: 'var(--text-secondary)',
            fontFamily: 'var(--font-serif)', fontStyle: 'italic',
          }}>
            {isDragging ? 'Drop file here' : 'Drag & drop DOCX, PDF, or TXT'}
          </span>
          <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: '0.375rem' }}>
            or click to browse (max 50 MB)
          </span>
        </>
      )}

      {error && (
        <span style={{ fontSize: '0.75rem', color: 'var(--error)', marginTop: '0.375rem' }}>
          {error}
        </span>
      )}
    </div>
  );
}
