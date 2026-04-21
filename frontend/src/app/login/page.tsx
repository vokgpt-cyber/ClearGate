'use client';

/**
 * /login — standalone sign-in screen for the pilot deployment.
 *
 * Sprint B.4: sits outside the protected-route gate so an unauthenticated
 * user can land here directly. After a successful POST /api/auth/login
 * the backend drops an HttpOnly `cg_session` cookie and we push the
 * returned user into AuthContext, then redirect to `/`.
 *
 * We deliberately keep the screen minimal — no "forgot password" or
 * self-registration. Pilot accounts are seeded by the admin CLI
 * (Sprint B.5) and a forgotten password means a cleargate-admin
 * reset-password call.
 */

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { useLocale } from '@/hooks/useLocale';
import { useTheme } from '@/hooks/useTheme';

export default function LoginPage() {
  const router = useRouter();
  const { user, isLoading, login } = useAuth();
  const { t, locale, setLocale } = useLocale();
  const { theme } = useTheme();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // If the cookie is already valid, skip the form entirely.
  useEffect(() => {
    if (!isLoading && user) {
      router.replace('/');
    }
  }, [isLoading, user, router]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (submitting) return;
      setSubmitting(true);
      setError(null);
      try {
        await login(username, password);
        router.replace('/');
      } catch (err) {
        // `request()` throws "API error 401: ..." on bad credentials.
        // We map any 401 to the friendly translated message; other
        // failures (network, 500s) surface via errorNetwork.
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes('401')) {
          setError(t('auth.errorInvalid'));
        } else {
          setError(t('auth.errorNetwork'));
        }
      } finally {
        setSubmitting(false);
      }
    },
    [login, username, password, router, submitting, t],
  );

  // While the initial /me probe is still in flight, don't flash the form.
  if (isLoading || user) {
    return (
      <div className="cg-login cg-login--loading" data-theme={theme}>
        <div className="cg-login__checking">{t('auth.checking')}</div>
      </div>
    );
  }

  return (
    <div className="cg-login" data-theme={theme}>
      <div className="cg-login__card">
        <div className="cg-login__brand">
          <div className="cg-login__brand-title">{t('auth.loginTitle')}</div>
          <div className="cg-login__brand-sub">{t('auth.loginSubtitle')}</div>
        </div>

        <form className="cg-login__form" onSubmit={handleSubmit} noValidate>
          <label className="cg-login__field">
            <span className="cg-login__label">{t('auth.username')}</span>
            <input
              type="text"
              autoComplete="username"
              autoFocus
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={submitting}
            />
          </label>

          <label className="cg-login__field">
            <span className="cg-login__label">{t('auth.password')}</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />
          </label>

          {error ? (
            <div className="cg-login__error" role="alert">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            className="cg-login__submit"
            disabled={submitting || !username || !password}
          >
            {submitting ? t('auth.submitting') : t('auth.submit')}
          </button>
        </form>

        <div className="cg-login__footer">
          <button
            type="button"
            className="cg-login__lang"
            onClick={() => setLocale(locale === 'ru' ? 'en' : 'ru')}
          >
            {locale === 'ru' ? t('locale.en') : t('locale.ru')}
          </button>
        </div>
      </div>
    </div>
  );
}
