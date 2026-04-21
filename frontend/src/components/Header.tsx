'use client';

/**
 * Header — top bar. Iteration 1 layout.
 *
 * Thin strip with locale + theme toggles on the right.
 * The backend health dot + version badge are rendered as a subtle
 * floating indicator in the bottom-right corner of the viewport.
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTheme } from '@/hooks/useTheme';
import { useLocale } from '@/hooks/useLocale';
import { useAuth } from '@/hooks/useAuth';
import { healthCheck } from '@/lib/api';

const APP_VERSION = 'v0.7.3';

export function Header() {
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useLocale();
  const { user, logout } = useAuth();
  const router = useRouter();
  const [backendOk, setBackendOk] = useState(false);

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

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
      <header className="cleargate-header">
        <div className="cleargate-header__left" />

        <div className="cleargate-header__right">
          {user ? (
            <span
              className="cleargate-header__user"
              title={`${t('auth.signedInAs')} ${user.username}`}
            >
              {user.username}
            </span>
          ) : null}
          <button
            type="button"
            className="cleargate-header__pill"
            onClick={() => setLocale(locale === 'ru' ? 'en' : 'ru')}
            aria-label="Toggle language"
          >
            {locale === 'ru' ? 'EN' : 'RU'}
          </button>
          <button
            type="button"
            className="cleargate-header__pill"
            onClick={toggleTheme}
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
          {user ? (
            <button
              type="button"
              className="cleargate-header__pill"
              onClick={handleLogout}
              aria-label={t('auth.logout')}
            >
              {t('auth.logout')}
            </button>
          ) : null}
        </div>
      </header>

      {/* Floating version badge */}
      <div className="cleargate-version-badge" title={backendOk ? t('status.connected') : t('status.disconnected')}>
        <span
          className="cleargate-version-badge__dot"
          data-ok={backendOk ? 'true' : 'false'}
        />
        <span className="cleargate-version-badge__text">{APP_VERSION}</span>
      </div>
    </>
  );
}
