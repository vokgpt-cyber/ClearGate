'use client';

/**
 * Header — top bar. Iteration 1 layout.
 *
 * The VELUM brand has moved to the Sidebar, so the Header is now a thin
 * strip that only shows: backend health status on the left (quiet) and
 * locale + theme toggles on the right.
 *
 * Kept intentionally restrained — Harvey-style headers are almost
 * invisible; they should not compete with the document view.
 */

import { useEffect, useState } from 'react';
import { useTheme } from '@/hooks/useTheme';
import { useLocale } from '@/hooks/useLocale';
import { healthCheck } from '@/lib/api';

export function Header() {
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useLocale();
  const [backendOk, setBackendOk] = useState(false);
  const [profile, setProfile] = useState<string>('alpha');

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const info = await healthCheck();
        if (cancelled) return;
        setBackendOk(true);
        if (info.profile) setProfile(info.profile);
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
    <header className="velum-header">
      <div className="velum-header__left">
        <div
          className="velum-header__status"
          title={backendOk ? t('status.connected') : t('status.disconnected')}
        >
          <span
            className="velum-header__status-dot"
            data-ok={backendOk ? 'true' : 'false'}
          />
          <span className="velum-header__status-text">
            {backendOk ? t('status.connected') : t('status.disconnected')}
          </span>
          <span className="velum-header__profile">{profile}</span>
        </div>
      </div>

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
  );
}
