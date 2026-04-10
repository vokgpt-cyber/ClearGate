'use client';

import { useEffect, useState } from 'react';
import { useTheme } from '@/hooks/useTheme';
import { useLocale } from '@/hooks/useLocale';
import { healthCheck } from '@/lib/api';

interface HeaderProps {
  sessionEntityCount?: number;
}

export function Header({ sessionEntityCount }: HeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useLocale();
  const [backendOk, setBackendOk] = useState(false);

  useEffect(() => {
    const check = async () => {
      try { await healthCheck(); setBackendOk(true); } catch { setBackendOk(false); }
    };
    check();
    const id = setInterval(check, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <header style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      height: 'var(--header-height)',
      padding: '0 1.25rem',
      borderBottom: '1px solid var(--border)',
      backgroundColor: 'var(--bg-primary)',
    }}>
      {/* Left: logo + subtitle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {/* Brand mark — stylized V */}
        <div style={{
          width: '2px', height: '28px',
          backgroundColor: 'var(--color-brand)',
          marginRight: '4px',
        }} />
        <span style={{
          fontFamily: 'var(--font-serif)',
          fontSize: '1.125rem',
          fontWeight: 700,
          letterSpacing: '0.08em',
          color: 'var(--text-primary)',
        }}>
          VELUM
        </span>
        <span style={{
          fontSize: '0.6875rem',
          color: 'var(--text-muted)',
          fontStyle: 'italic',
          fontFamily: 'var(--font-serif)',
        }}>
          {t('app.subtitle')}
        </span>
      </div>

      {/* Right: status + controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
        {/* Entity count badge */}
        {sessionEntityCount != null && sessionEntityCount > 0 && (
          <span style={{
            fontSize: '0.6875rem',
            color: 'var(--text-secondary)',
            padding: '0.125rem 0.5rem',
            borderRadius: '2px',
            backgroundColor: 'var(--bg-secondary)',
          }}>
            {t('session.entities')}: {sessionEntityCount}
          </span>
        )}

        {/* Backend status dot */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }} title={backendOk ? t('status.connected') : t('status.disconnected')}>
          <div style={{
            width: '6px', height: '6px', borderRadius: '50%',
            backgroundColor: backendOk ? 'var(--success)' : 'var(--error)',
          }} />
          <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>
            Alpha
          </span>
        </div>

        {/* Divider */}
        <div style={{ width: '1px', height: '20px', backgroundColor: 'var(--border)' }} />

        {/* Locale toggle */}
        <button onClick={() => setLocale(locale === 'ru' ? 'en' : 'ru')}
          style={{
            padding: '0.25rem 0.5rem', fontSize: '0.6875rem', fontWeight: 500,
            border: '1px solid var(--border)', borderRadius: '2px',
            backgroundColor: 'transparent', color: 'var(--text-secondary)',
            cursor: 'pointer', letterSpacing: '0.04em',
          }}
          aria-label="Toggle language"
        >
          {locale === 'ru' ? 'EN' : 'RU'}
        </button>

        {/* Theme toggle */}
        <button onClick={toggleTheme}
          style={{
            padding: '0.25rem 0.5rem', fontSize: '0.6875rem', fontWeight: 500,
            border: '1px solid var(--border)', borderRadius: '2px',
            backgroundColor: 'transparent', color: 'var(--text-secondary)',
            cursor: 'pointer',
          }}
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? '\u2600' : '\u263E'}
        </button>
      </div>
    </header>
  );
}
