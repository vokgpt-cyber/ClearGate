'use client';

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
} from 'react';
import type { ReactNode } from 'react';
import ruMessages from '@/lib/locales/ru.json';
import enMessages from '@/lib/locales/en.json';

type Locale = 'ru' | 'en';
type Messages = typeof ruMessages;

const messagesMap: Record<Locale, Messages> = { ru: ruMessages, en: enMessages };

function getNestedValue(obj: unknown, path: string): string {
  const keys = path.split('.');
  let current: unknown = obj;
  for (const key of keys) {
    if (current == null || typeof current !== 'object') return path;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === 'string' ? current : path;
}

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

export const LocaleContext = createContext<LocaleContextValue>({
  locale: 'ru',
  setLocale: () => {},
  t: (key) => key,
});

export function useLocale() {
  return useContext(LocaleContext);
}

/** Default locale used both on the server and on the very first client
 * render. Must be stable so that SSR markup matches initial client markup. */
const DEFAULT_LOCALE: Locale = 'ru';

export function LocaleProvider({ children }: { children: ReactNode }) {
  // IMPORTANT: always start with DEFAULT_LOCALE so server and client render
  // the same markup on the first pass. We pick up the user's saved locale
  // from localStorage *after* mount in a useEffect, which triggers a
  // normal re-render without a hydration mismatch.
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    try {
      const stored = localStorage.getItem('cleargate_locale') as Locale | null;
      if (stored && stored !== locale && (stored === 'ru' || stored === 'en')) {
        setLocaleState(stored);
      }
    } catch {
      // localStorage unavailable (e.g. privacy mode) — stay on default.
    }
    // We intentionally run this only once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setLocale = useCallback((newLocale: Locale) => {
    setLocaleState(newLocale);
    try {
      localStorage.setItem('cleargate_locale', newLocale);
    } catch {
      // no-op
    }
  }, []);

  const t = useCallback(
    (key: string) => getNestedValue(messagesMap[locale], key),
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return (
    <LocaleContext.Provider value={value}>
      {children}
    </LocaleContext.Provider>
  );
}
