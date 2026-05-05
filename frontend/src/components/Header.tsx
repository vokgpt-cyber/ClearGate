'use client';

/**
 * Header — top bar. Iteration 1 layout.
 *
 * Thin strip with locale + theme toggles on the right.
 * The backend health dot + version badge are rendered as a subtle
 * floating indicator in the bottom-right corner of the viewport.
 */

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTheme } from '@/hooks/useTheme';
import { useLocale } from '@/hooks/useLocale';
import { useAuth } from '@/hooks/useAuth';
import { healthCheck } from '@/lib/api';

const FALLBACK_VERSION = 'v0.9.0';

export function Header() {
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useLocale();
  const { user, logout } = useAuth();
  const router = useRouter();
  const [backendOk, setBackendOk] = useState(false);
  const [version, setVersion] = useState(FALLBACK_VERSION);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const health = await healthCheck();
        if (!cancelled) {
          setBackendOk(true);
          if (health.version) setVersion(`v${health.version.replace(/^v/i, '')}`);
        }
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

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && menuRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [menuOpen]);

  const goTo = (path: string) => {
    setMenuOpen(false);
    router.push(path);
  };

  return (
    <>
      <header className="cleargate-header">
        <div className="cleargate-header__left" />

        <div className="cleargate-header__right">
          {user ? (
            <div className="cleargate-header__profile-menu" ref={menuRef}>
              <button
                type="button"
                className="cleargate-header__user"
                title={`${t('auth.signedInAs')} ${user.username}`}
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                onClick={() => setMenuOpen((open) => !open)}
              >
                {user.username}
              </button>
              {menuOpen && (
                <div className="cleargate-header__dropdown" role="menu">
                  {user.role === 'admin' && (
                    <>
                      <button
                        type="button"
                        className="cleargate-header__menu-item"
                        onClick={() => goTo('/admin/users')}
                        role="menuitem"
                      >
                        {t('admin.users.title')}
                      </button>
                      <button
                        type="button"
                        className="cleargate-header__menu-item"
                        onClick={() => goTo('/admin/feedback')}
                        role="menuitem"
                      >
                        {t('admin.feedback.title')}
                      </button>
                      <button
                        type="button"
                        className="cleargate-header__menu-item"
                        onClick={() => goTo('/admin/errors')}
                        role="menuitem"
                      >
                        {t('admin.errors.title')}
                      </button>
                      <button
                        type="button"
                        className="cleargate-header__menu-item"
                        onClick={() => goTo('/admin/analytics')}
                        role="menuitem"
                      >
                        {t('admin.analytics.title')}
                      </button>
                      <div className="cleargate-header__menu-separator" />
                    </>
                  )}
                  <button
                    type="button"
                    className="cleargate-header__menu-item"
                    onClick={() => {
                      setLocale(locale === 'ru' ? 'en' : 'ru');
                      setMenuOpen(false);
                    }}
                    role="menuitem"
                  >
                    {locale === 'ru' ? t('locale.en') : t('locale.ru')}
                  </button>
                  <button
                    type="button"
                    className="cleargate-header__menu-item"
                    onClick={() => {
                      toggleTheme();
                      setMenuOpen(false);
                    }}
                    role="menuitem"
                  >
                    {theme === 'dark' ? t('theme.light') : t('theme.dark')}
                  </button>
                  <div className="cleargate-header__menu-separator" />
                  <button
                    type="button"
                    className="cleargate-header__menu-item cleargate-header__menu-item--danger"
                    onClick={handleLogout}
                    role="menuitem"
                  >
                    {t('auth.logout')}
                  </button>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </header>

      {/* Floating version badge */}
      <div className="cleargate-version-badge" title={backendOk ? t('status.connected') : t('status.disconnected')}>
        <span
          className="cleargate-version-badge__dot"
          data-ok={backendOk ? 'true' : 'false'}
        />
        <span className="cleargate-version-badge__text">{version}</span>
      </div>
    </>
  );
}
