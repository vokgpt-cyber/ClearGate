# CLAUDE.md — Frontend (Tauri + Next.js)

Sub-инструкции для Claude Code при работе в каталоге `frontend/`. Этот файл дополняет root [`CLAUDE.md`](../CLAUDE.md), не заменяет его.

## Обзор

Frontend CLEARGATE — Tauri 2.10 desktop shell + React 19 + Next.js 15 (статический экспорт) + TypeScript 5 strict + Tailwind CSS 4. Главные компоненты: SplitScreen с подсветкой сущностей, LLMPanel для выбора провайдера, WebSocket-стриминг ответов LLM, переключатели тем (light/dark) и языков (RU/EN).

## Структура

```
frontend/
├── src-tauri/                  # Rust shell, минимальный
│   ├── src/main.rs
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── icons/
├── src/
│   ├── app/                    # Next.js app router
│   │   ├── layout.tsx          # Root layout с header
│   │   ├── page.tsx            # Dashboard
│   │   ├── session/[id]/page.tsx  # Split-screen
│   │   └── globals.css
│   ├── components/
│   │   ├── SplitScreen.tsx
│   │   ├── EntityHighlighter.tsx
│   │   ├── EntityPopover.tsx
│   │   ├── EntityNavigator.tsx
│   │   ├── LLMPanel.tsx
│   │   ├── ProviderSelector.tsx
│   │   ├── ModelSelector.tsx
│   │   ├── ThinkingSlider.tsx
│   │   ├── PromptInput.tsx
│   │   ├── CostEstimator.tsx
│   │   ├── SendButton.tsx
│   │   ├── DiffViewer.tsx
│   │   ├── DocumentUpload.tsx
│   │   ├── CommandPalette.tsx
│   │   ├── ThemeToggle.tsx
│   │   ├── LocaleToggle.tsx
│   │   └── I18nProvider.tsx
│   ├── hooks/
│   │   ├── useTheme.ts
│   │   ├── useLocale.ts
│   │   ├── useAnonymize.ts
│   │   ├── useLLMStream.ts
│   │   ├── useSyncedScroll.ts
│   │   ├── useEntityRegistry.ts
│   │   ├── useModelsList.ts
│   │   └── useCostEstimate.ts
│   ├── lib/
│   │   ├── api.ts              # API client
│   │   ├── colors.ts           # Entity color palette
│   │   ├── i18n.ts             # i18next config
│   │   └── locales/
│   │       ├── ru.json
│   │       └── en.json
│   ├── types/
│   │   ├── entities.ts
│   │   └── llm.ts
│   └── styles/
│       └── globals.css
├── public/
├── next.config.js
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
└── package.json
```

## Команды

```powershell
# Установка
npm install

# Dev
npm run dev                    # только Next.js (для быстрой UI разработки)
npm run tauri dev              # полное Tauri окно

# Build
npm run build
npm run tauri build            # production бандл

# Тесты
npm test                       # vitest
npm test -- --watch            # watch mode
npm test -- ComponentName      # конкретный файл

# Линтинг и форматирование
npm run lint
npm run lint:fix
npm run format
npm run typecheck              # tsc --noEmit
```

## Стиль кода (TypeScript-специфика)

### Strict mode
- Никаких `any` без явного `// eslint-disable-line` с обоснованием
- `unknown` вместо `any` для неизвестных типов
- Все props компонентов типизированы через interface (не type, для совместимости)

### React conventions
- Только функциональные компоненты, никаких классов
- Хуки именуются `useXxx`
- Контролируемые компоненты предпочтительнее uncontrolled
- `useCallback` и `useMemo` только когда есть профайлер-доказанная необходимость
- Никаких inline объектов как props (создаст бесконечный re-render)

### Структура компонента
```tsx
// 1. 'use client' если нужно
'use client';

// 2. Imports (внешние → локальные)
import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';

import { useTheme } from '@/hooks/useTheme';
import type { DetectedEntity } from '@/types/entities';

// 3. Interface props
interface MyComponentProps {
  value: string;
  onChange: (value: string) => void;
}

// 4. Компонент
export function MyComponent({ value, onChange }: MyComponentProps) {
  const { t } = useTranslation();
  const { theme } = useTheme();
  const [local, setLocal] = useState('');

  const handleClick = useCallback(() => {
    onChange(local);
  }, [local, onChange]);

  return (
    <div className="rounded-md bg-bg-elevated p-4">
      {/* ... */}
    </div>
  );
}
```

### Tailwind conventions
- Использовать **CSS-переменные** через токены: `bg-bg-primary`, `text-text-primary`, `border-border`
- НЕ использовать прямые цвета типа `bg-blue-500` — они не переключаются между темами
- Утилиты по группам: layout → spacing → sizing → colors → typography → effects
- Длинные строки className разбивать через template literals или `clsx`

### i18next
- **Никаких** хардкоженных строк на русском или английском в JSX
- Все строки через `const { t } = useTranslation()` и `t('namespace.key')`
- Структурированные ключи: `entity.types.PER`, не `personLabel`
- Для пluralization — `t('items', { count: n })` с правилами в JSON

### Type safety
```typescript
// Discriminated unions для message types
type StreamMessage =
  | { type: 'thinking_delta'; content: string }
  | { type: 'text_delta'; content: string }
  | { type: 'final'; content: string; metadata: Record<string, unknown> }
  | { type: 'error'; content: string };

// Используй switch с exhaustiveness check
function handle(msg: StreamMessage) {
  switch (msg.type) {
    case 'thinking_delta': /* ... */ break;
    case 'text_delta': /* ... */ break;
    case 'final': /* ... */ break;
    case 'error': /* ... */ break;
    default: {
      const _exhaustive: never = msg;
      throw new Error(`Unhandled type: ${_exhaustive}`);
    }
  }
}
```

## Что специфично для frontend

### Никогда не делай
- НЕ хардкодь русские/английские строки в JSX
- НЕ используй `bg-blue-500` (не переключается с темами) — только токены `bg-bg-primary`, `bg-accent`, etc.
- НЕ вызывай API напрямую из компонентов — только через хуки `useXxx`
- НЕ храни секреты или API keys на клиенте
- НЕ используй `localStorage` для чувствительных данных (только для preferences темы/языка)
- НЕ блокируй UI на тяжёлых операциях — используй `Suspense` и стриминг

### Всегда делай
- Локализуй ВСЕ строки через i18next
- Поддерживай обе темы — проверяй визуально
- Добавляй ARIA-атрибуты для accessibility (`aria-label`, `role`)
- Тестируй с клавиатуры (Tab, Enter, Escape)
- Используй CSS-переменные через Tailwind токены
- Memo'й только то, что доказано тормозит

### Tauri особенности
- Static export (`output: 'export'` в next.config.js) — никаких server actions
- Capability config в `tauri.conf.json` — каждое разрешение явно
- Использование Tauri API: `import { invoke } from '@tauri-apps/api/core'`
- HTTP-вызовы к локальному backend через стандартный `fetch`

### Производительность
- Список из 1000+ сущностей — виртуализация через `@tanstack/react-virtual`
- Heavy renders — `React.memo` с правильными props
- WebSocket — один на сессию, не открывать новый на каждый chunk
- Большие документы — chunking и lazy rendering

## Связанные документы

@../CLAUDE.md
@../docs/ARCHITECTURE.md
@../docs/CODE_STYLE.md
@../docs/adr/0001-use-tauri-over-electron.md
