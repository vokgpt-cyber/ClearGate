# Task 10: Theme System and Internationalization (RU/EN, Light/Dark)

## Контекст

CLEARGATE должен поддерживать переключение между русским и английским языками интерфейса, а также светлой и тёмной темами. Переключение должно работать без перезагрузки, состояние сохраняется в localStorage. Все пользовательские строки централизованы в i18n словарях. Дизайн-система основана на CSS-переменных, переключаемых добавлением класса на `<html>`.

## Зависимости

- Task 01 (project init)
- Task 05 (SplitScreen — основной потребитель темы)
- Task 09 (LLMPanel — основной потребитель i18n)

## Цель

Реализовать systembad для тем и локализации, два toggle компонента, словари RU/EN со всеми ключами, использованными в задачах 5 и 9, и дефолтный layout с этими переключателями в header.

## Требования

### CSS-переменные для тем

```css
/* frontend/src/styles/globals.css */

@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    /* Light theme (default) */
    --color-bg-primary: #FAFAFA;
    --color-bg-secondary: #F5F5F5;
    --color-bg-elevated: #FFFFFF;
    --color-bg-hover: #EBEBEB;
    --color-bg-disabled: #E5E5E5;

    --color-text-primary: #171717;
    --color-text-secondary: #404040;
    --color-text-muted: #737373;
    --color-text-disabled: #A3A3A3;

    --color-border: #E5E5E5;
    --color-border-strong: #D4D4D4;

    --color-accent: #1E3A5F;
    --color-accent-dark: #15293F;
    --color-accent-soft: #DBEAFE;

    --color-success: #059669;
    --color-warning: #D97706;
    --color-danger: #DC2626;
  }

  .dark {
    /* Dark theme */
    --color-bg-primary: #0A0A0A;
    --color-bg-secondary: #171717;
    --color-bg-elevated: #262626;
    --color-bg-hover: #333333;
    --color-bg-disabled: #2E2E2E;

    --color-text-primary: #F5F5F5;
    --color-text-secondary: #D4D4D4;
    --color-text-muted: #A3A3A3;
    --color-text-disabled: #525252;

    --color-border: #2E2E2E;
    --color-border-strong: #404040;

    --color-accent: #4A8BD4;
    --color-accent-dark: #3A6FAA;
    --color-accent-soft: #1E3A5F;

    --color-success: #10B981;
    --color-warning: #F59E0B;
    --color-danger: #EF4444;
  }

  body {
    @apply bg-bg-primary text-text-primary antialiased;
    transition: background-color 0.2s ease, color 0.2s ease;
  }
}
```

### Tailwind config

```typescript
// frontend/tailwind.config.ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: {
          primary: 'var(--color-bg-primary)',
          secondary: 'var(--color-bg-secondary)',
          elevated: 'var(--color-bg-elevated)',
          hover: 'var(--color-bg-hover)',
          disabled: 'var(--color-bg-disabled)',
        },
        text: {
          primary: 'var(--color-text-primary)',
          secondary: 'var(--color-text-secondary)',
          muted: 'var(--color-text-muted)',
          disabled: 'var(--color-text-disabled)',
        },
        border: {
          DEFAULT: 'var(--color-border)',
          strong: 'var(--color-border-strong)',
        },
        accent: {
          DEFAULT: 'var(--color-accent)',
          dark: 'var(--color-accent-dark)',
          soft: 'var(--color-accent-soft)',
        },
        success: 'var(--color-success)',
        warning: 'var(--color-warning)',
        danger: 'var(--color-danger)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        serif: ['PT Serif', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
};

export default config;
```

### useTheme хук

```typescript
// frontend/src/hooks/useTheme.ts
'use client';

import { useEffect, useState, useCallback } from 'react';

type Theme = 'light' | 'dark';

const THEME_KEY = 'cleargate_theme';

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>('dark');

  useEffect(() => {
    const stored = localStorage.getItem(THEME_KEY) as Theme | null;
    const initial: Theme = stored ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setThemeState(initial);
    document.documentElement.classList.toggle('dark', initial === 'dark');
  }, []);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    localStorage.setItem(THEME_KEY, newTheme);
    document.documentElement.classList.toggle('dark', newTheme === 'dark');
  }, []);

  const toggle = useCallback(() => {
    setTheme(theme === 'light' ? 'dark' : 'light');
  }, [theme, setTheme]);

  return { theme, setTheme, toggle };
}
```

### useLocale хук + i18n setup

```typescript
// frontend/src/lib/i18n.ts
'use client';

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import ru from './locales/ru.json';
import en from './locales/en.json';

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      ru: { translation: ru },
      en: { translation: en },
    },
    fallbackLng: 'ru',
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'cleargate_locale',
      caches: ['localStorage'],
    },
  });

export default i18n;
```

```typescript
// frontend/src/hooks/useLocale.ts
'use client';

import { useTranslation } from 'react-i18next';
import { useCallback } from 'react';

type Locale = 'ru' | 'en';

export function useLocale() {
  const { i18n } = useTranslation();
  const locale = (i18n.language?.split('-')[0] ?? 'ru') as Locale;

  const setLocale = useCallback((newLocale: Locale) => {
    i18n.changeLanguage(newLocale);
    localStorage.setItem('cleargate_locale', newLocale);
    document.documentElement.lang = newLocale;
  }, [i18n]);

  const toggle = useCallback(() => {
    setLocale(locale === 'ru' ? 'en' : 'ru');
  }, [locale, setLocale]);

  return { locale, setLocale, toggle };
}
```

### Toggle компоненты

```tsx
// frontend/src/components/ThemeToggle.tsx
'use client';

import { useTheme } from '@/hooks/useTheme';

export function ThemeToggle() {
  const { theme, toggle } = useTheme();

  return (
    <button
      onClick={toggle}
      className="flex h-9 w-9 items-center justify-center rounded-md border border-border hover:bg-bg-hover"
      aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} theme`}
      title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}
    >
      {theme === 'light' ? (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      ) : (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      )}
    </button>
  );
}
```

```tsx
// frontend/src/components/LocaleToggle.tsx
'use client';

import { useLocale } from '@/hooks/useLocale';

export function LocaleToggle() {
  const { locale, toggle } = useLocale();

  return (
    <button
      onClick={toggle}
      className="flex h-9 items-center gap-2 rounded-md border border-border px-3 hover:bg-bg-hover"
      aria-label={`Switch to ${locale === 'ru' ? 'English' : 'Russian'}`}
    >
      <span className="text-sm font-medium">
        {locale === 'ru' ? 'RU' : 'EN'}
      </span>
      <span className="text-xs text-text-muted">
        {locale === 'ru' ? '→ EN' : '→ RU'}
      </span>
    </button>
  );
}
```

### Словари

```json
// frontend/src/lib/locales/ru.json
{
  "app": {
    "name": "CLEARGATE",
    "tagline": "Завеса, за которой — адвокатская тайна"
  },
  "nav": {
    "new_session": "Новая сессия",
    "history": "История",
    "settings": "Настройки"
  },
  "common": {
    "save": "Сохранить",
    "cancel": "Отмена",
    "edit": "Редактировать",
    "delete": "Удалить",
    "close": "Закрыть",
    "loading": "Загрузка...",
    "error": "Ошибка"
  },
  "entity": {
    "accept": "Принять",
    "reject": "Отклонить",
    "edit": "Редактировать",
    "confidence": "Уверенность",
    "types": {
      "PER": "ФИО",
      "ORG": "Организация",
      "MON": "Сумма",
      "DATE": "Дата",
      "ADDR": "Адрес",
      "RU_INN": "ИНН",
      "RU_OGRN": "ОГРН",
      "RU_SNILS": "СНИЛС",
      "RU_PASSPORT": "Паспорт",
      "RU_BANK_ACCOUNT": "Банковский счёт",
      "PHONE": "Телефон",
      "EMAIL": "Email",
      "CASE_NUMBER": "Номер дела"
    }
  },
  "llm": {
    "provider": "Провайдер",
    "model": "Модель",
    "thinking_level": "Уровень анализа",
    "thinking_levels": {
      "off": "Выключен",
      "low": "Низкий",
      "medium": "Средний",
      "high": "Высокий",
      "max": "Максимальный"
    },
    "prompt": "Запрос",
    "prompt_placeholder": "Опишите задачу для LLM...",
    "templates": "Шаблоны",
    "estimated_cost": "Примерная стоимость",
    "estimating": "Расчёт",
    "input_tokens": "Входные токены",
    "output_tokens": "Выходные токены",
    "thinking_tokens": "Токены анализа",
    "send_to_provider": "Отправить запрос",
    "confirm_send_title": "Подтвердите отправку",
    "confirm_send_message": "Будет отправлено {{length}} символов анонимизированного текста. Стоимость: ~${{cost}}. Убедитесь, что анонимизация корректна.",
    "confirm_send": "Отправить"
  },
  "prompts": {
    "analyze_contract": {
      "title": "Анализ договора",
      "text": "Проанализируй этот договор. Выдели ключевые условия, обязательства сторон, сроки, штрафы и потенциальные риски."
    },
    "find_risks": {
      "title": "Найти риски",
      "text": "Найди в этом документе все юридические риски, которые могут возникнуть для нашей стороны. Для каждого риска укажи степень критичности и предложи меры минимизации."
    },
    "prepare_opinion": {
      "title": "Подготовить заключение",
      "text": "Подготовь правовое заключение по этому документу с обоснованием со ссылками на применимые нормы права."
    },
    "answer_client": {
      "title": "Ответить клиенту",
      "text": "На основе этого документа подготовь ответ клиенту в понятной форме, объясняющий ключевые моменты и наши рекомендации."
    }
  },
  "session": {
    "create": "Создать сессию",
    "upload_document": "Загрузить документ",
    "drag_drop": "Перетащите файл сюда или нажмите для выбора",
    "supported_formats": "Поддерживаются: DOCX, PDF, TXT"
  }
}
```

```json
// frontend/src/lib/locales/en.json
{
  "app": {
    "name": "CLEARGATE",
    "tagline": "The veil that protects attorney-client privilege"
  },
  "nav": {
    "new_session": "New session",
    "history": "History",
    "settings": "Settings"
  },
  "common": {
    "save": "Save",
    "cancel": "Cancel",
    "edit": "Edit",
    "delete": "Delete",
    "close": "Close",
    "loading": "Loading...",
    "error": "Error"
  },
  "entity": {
    "accept": "Accept",
    "reject": "Reject",
    "edit": "Edit",
    "confidence": "Confidence",
    "types": {
      "PER": "Person",
      "ORG": "Organization",
      "MON": "Amount",
      "DATE": "Date",
      "ADDR": "Address",
      "RU_INN": "INN",
      "RU_OGRN": "OGRN",
      "RU_SNILS": "SNILS",
      "RU_PASSPORT": "Passport",
      "RU_BANK_ACCOUNT": "Bank account",
      "PHONE": "Phone",
      "EMAIL": "Email",
      "CASE_NUMBER": "Case number"
    }
  },
  "llm": {
    "provider": "Provider",
    "model": "Model",
    "thinking_level": "Thinking level",
    "thinking_levels": {
      "off": "Off",
      "low": "Low",
      "medium": "Medium",
      "high": "High",
      "max": "Maximum"
    },
    "prompt": "Prompt",
    "prompt_placeholder": "Describe the task for the LLM...",
    "templates": "Templates",
    "estimated_cost": "Estimated cost",
    "estimating": "Estimating",
    "input_tokens": "Input tokens",
    "output_tokens": "Output tokens",
    "thinking_tokens": "Thinking tokens",
    "send_to_provider": "Send request",
    "confirm_send_title": "Confirm sending",
    "confirm_send_message": "About to send {{length}} characters of anonymized text. Estimated cost: ~${{cost}}. Verify the anonymization is correct.",
    "confirm_send": "Send"
  },
  "prompts": {
    "analyze_contract": {
      "title": "Analyze contract",
      "text": "Analyze this contract. Identify key terms, party obligations, deadlines, penalties, and potential risks."
    },
    "find_risks": {
      "title": "Find risks",
      "text": "Find all legal risks in this document for our party. For each risk, indicate severity and suggest mitigation measures."
    },
    "prepare_opinion": {
      "title": "Prepare opinion",
      "text": "Prepare a legal opinion on this document with references to applicable law."
    },
    "answer_client": {
      "title": "Answer client",
      "text": "Based on this document, prepare a client-facing response in clear language explaining key points and our recommendations."
    }
  },
  "session": {
    "create": "Create session",
    "upload_document": "Upload document",
    "drag_drop": "Drag and drop file here or click to select",
    "supported_formats": "Supported: DOCX, PDF, TXT"
  }
}
```

### Обновлённый layout с toggles

```tsx
// frontend/src/app/layout.tsx
import type { Metadata } from 'next';
import './globals.css';
import { I18nProvider } from '@/components/I18nProvider';
import { ThemeToggle } from '@/components/ThemeToggle';
import { LocaleToggle } from '@/components/LocaleToggle';

export const metadata: Metadata = {
  title: 'CLEARGATE',
  description: 'On-premise anonymization gateway for legal AI workflows',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body>
        <I18nProvider>
          <header className="flex items-center justify-between border-b border-border bg-bg-elevated px-6 py-3">
            <div className="flex items-center gap-3">
              <div className="text-2xl font-bold text-accent">CLEARGATE</div>
              <div className="text-sm text-text-muted">Адвокатское бюро ЕПАМ</div>
            </div>
            <div className="flex items-center gap-2">
              <LocaleToggle />
              <ThemeToggle />
            </div>
          </header>
          <main className="h-[calc(100vh-3.5rem)]">{children}</main>
        </I18nProvider>
      </body>
    </html>
  );
}
```

```tsx
// frontend/src/components/I18nProvider.tsx
'use client';

import { I18nextProvider } from 'react-i18next';
import i18n from '@/lib/i18n';

export function I18nProvider({ children }: { children: React.ReactNode }) {
  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
```

## Файлы для создания

```
frontend/src/styles/globals.css
frontend/tailwind.config.ts
frontend/src/lib/i18n.ts
frontend/src/lib/locales/ru.json
frontend/src/lib/locales/en.json
frontend/src/hooks/useTheme.ts
frontend/src/hooks/useLocale.ts
frontend/src/components/ThemeToggle.tsx
frontend/src/components/LocaleToggle.tsx
frontend/src/components/I18nProvider.tsx
frontend/src/app/layout.tsx     # обновить
```

## Тесты

- Theme toggle меняет класс на html и сохраняет в localStorage
- Locale toggle меняет язык и обновляет ARIA-атрибуты
- Дефолтный язык — русский, дефолтная тема — тёмная
- Все ключи из ru.json присутствуют в en.json (запустить parity-чек скриптом)

```typescript
// tests parity
import ruDict from '@/lib/locales/ru.json';
import enDict from '@/lib/locales/en.json';

function getKeys(obj: any, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return typeof v === 'object' ? getKeys(v, key) : [key];
  });
}

test('ru and en dictionaries have same keys', () => {
  const ruKeys = getKeys(ruDict).sort();
  const enKeys = getKeys(enDict).sort();
  expect(ruKeys).toEqual(enKeys);
});
```

## Acceptance Criteria

- [ ] Переключение темы работает мгновенно, без перезагрузки
- [ ] Переключение языка работает мгновенно, без перезагрузки
- [ ] Состояние сохраняется в localStorage между сессиями
- [ ] Все строки из задач 5 и 9 присутствуют в обоих словарях
- [ ] CSS-переменные работают в Tailwind через `bg-bg-primary`, `text-text-primary` и т.д.
- [ ] Tests парити словарей проходят
- [ ] Никаких хардкоженных русских/английских строк в JSX (проверить grep'ом)
- [ ] Lighthouse accessibility score ≥ 95

## Команды

```powershell
cd frontend
npm install i18next react-i18next i18next-browser-languagedetector
npm test
npm run lint
npm run tauri dev

# Парити-чек словарей
npm run check-i18n
```

## Коммит

```
feat(frontend): theme system and i18n (RU/EN, light/dark)

- CSS variables for theme tokens (light/dark)
- Tailwind config consuming variables for utility classes
- useTheme hook with localStorage persistence and system preference fallback
- useLocale hook with i18next + LanguageDetector
- ThemeToggle and LocaleToggle in header
- Full Russian and English dictionaries with parity test
- Default: dark theme, Russian language

Closes task #10
```
