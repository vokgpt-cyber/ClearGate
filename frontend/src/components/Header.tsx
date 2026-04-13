'use client';

/**
 * Header — top bar. Iteration 1 layout.
 *
 * Thin strip with locale + theme toggles on the right.
 * The backend health dot + version badge are rendered as a subtle
 * floating indicator in the bottom-right corner of the viewport.
 */

import { useEffect, useState } from 'react';
import { useTheme } from '@/hooks/useTheme';
import { useLocale } from '@/hooks/useLocale';
import { healthCheck } from '@/lib/api';

const APP_VERSION = 'v0.7.3';

export function Header() {
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useLocale();
  const [backendOk, setBackendOk] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        await healthCheck();
        if (!cancelled) setBackendOk(true);
      } catch {
        if (!cancelled) setBackendOk(false);
      }
    };
    check();
    const id = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <>
      <header className="velum-header">
        <div className="velum-header__left" />

        <div className="velum-header__right">
          <button
            type="button"
            className="velum-header__pill"
            onClick={() => setLocale(locale === 'ru' ? 'en' : 'ru')}
            aria-label="Toggle language"
          >
            {locale === 'ru' ? 'EN' : 'RU'}
          </button>
          <button
            type="button"
            className="velum-header__pill"
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>

      {/* Floating version badge */}
      <div className="velum-version-badge" title={backendOk ? t('status.connected') : t('status.disconnected')}>
        <span
          className="velum-version-badge__dot"
          data-ok={backendOk ? 'true' : 'false'}
        />
        <span className="velum-version-badge__text">{APP_VERSION}</span>
      </div>
    </>
  );
}
