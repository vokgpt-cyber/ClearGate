# Task 05: SplitScreen UI Component

## Контекст

Главный экран CLEARGATE — split-screen ревью анонимизации. Слева — оригинальный текст с подсветкой обнаруженных сущностей по типам, справа — анонимизированная версия с плейсхолдерами в тех же цветах. Юрист должен иметь возможность ревьюить каждую сущность (принять / отклонить / редактировать / добавить вручную).

## Зависимости

- Task 01 (project init)
- Прочитать `docs/ARCHITECTURE.md` раздел 6 (Frontend)

## Цель

Создать React-компоненты, реализующие main split-screen экран с интерактивной подсветкой сущностей и панелью навигации.

## Требования

### Компоненты

1. **`SplitScreen.tsx`** — главный контейнер с двумя панелями
2. **`EntityHighlighter.tsx`** — рендер текста с подсвеченными сущностями
3. **`EntityPopover.tsx`** — попавер с действиями (accept/reject/edit) при клике
4. **`EntityNavigator.tsx`** — боковая панель со списком сущностей
5. **`SyncedScroll.tsx`** — хук/компонент для синхронной прокрутки
6. **`useEntityRegistry.ts`** — хук для работы с реестром сущностей на клиенте

### Цветовая палитра

```typescript
// frontend/src/lib/colors.ts
export const ENTITY_COLORS = {
  PER:             { light: '#DBEAFE', dark: '#1E3A5F', label: 'ФИО',        icon: '👤' },
  ORG:             { light: '#FEF3C7', dark: '#4A3728', label: 'Организация', icon: '🏢' },
  MON:             { light: '#D1FAE5', dark: '#1A3A2A', label: 'Сумма',      icon: '💰' },
  DATE:            { light: '#FCE7F3', dark: '#4A1D3D', label: 'Дата',       icon: '📅' },
  ADDR:            { light: '#E0E7FF', dark: '#272566', label: 'Адрес',      icon: '📍' },
  CASE_NUMBER:     { light: '#F3E8FF', dark: '#3B1D66', label: 'Дело',       icon: '📄' },
  RU_INN:          { light: '#FFEDD5', dark: '#4A2A1A', label: 'ИНН',        icon: '🆔' },
  RU_OGRN:         { light: '#FFEDD5', dark: '#4A2A1A', label: 'ОГРН',       icon: '🆔' },
  RU_SNILS:        { light: '#FFEDD5', dark: '#4A2A1A', label: 'СНИЛС',      icon: '🆔' },
  RU_PASSPORT:     { light: '#FFEDD5', dark: '#4A2A1A', label: 'Паспорт',    icon: '🆔' },
  RU_BANK_ACCOUNT: { light: '#FFEDD5', dark: '#4A2A1A', label: 'Счёт',       icon: '🆔' },
  PHONE:           { light: '#CCFBF1', dark: '#1A3B3B', label: 'Телефон',    icon: '📞' },
  EMAIL:           { light: '#CCFBF1', dark: '#1A3B3B', label: 'Email',      icon: '📞' },
} as const;

export type EntityType = keyof typeof ENTITY_COLORS;
```

### SplitScreen компонент

```tsx
// frontend/src/components/SplitScreen.tsx
'use client';

import { useState, useRef, useCallback } from 'react';
import { EntityHighlighter } from './EntityHighlighter';
import { EntityNavigator } from './EntityNavigator';
import { EntityPopover } from './EntityPopover';
import { useSyncedScroll } from '@/hooks/useSyncedScroll';
import type { DetectedEntity } from '@/types/entities';

interface SplitScreenProps {
  originalText: string;
  anonymizedText: string;
  entities: DetectedEntity[];
  onEntityUpdate: (entity: DetectedEntity, action: 'accept' | 'reject' | 'edit', newValue?: string) => void;
  onEntityAdd: (selectedText: string, type: string, position: number) => void;
}

export function SplitScreen({
  originalText,
  anonymizedText,
  entities,
  onEntityUpdate,
  onEntityAdd,
}: SplitScreenProps) {
  const [splitRatio, setSplitRatio] = useState(0.5);
  const [activeEntity, setActiveEntity] = useState<DetectedEntity | null>(null);
  const [popoverPosition, setPopoverPosition] = useState<{ x: number; y: number } | null>(null);

  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);

  useSyncedScroll(leftRef, rightRef);

  const handleEntityClick = useCallback(
    (entity: DetectedEntity, event: React.MouseEvent) => {
      setActiveEntity(entity);
      setPopoverPosition({ x: event.clientX, y: event.clientY });
    },
    []
  );

  const handleResizerDrag = useCallback((e: React.MouseEvent) => {
    // Drag handler для изменения пропорций панелей
    // ...
  }, []);

  return (
    <div className="flex h-full w-full">
      {/* Left panel — original text */}
      <div
        ref={leftRef}
        className="overflow-auto bg-bg-secondary p-6"
        style={{ width: `${splitRatio * 100}%` }}
      >
        <EntityHighlighter
          text={originalText}
          entities={entities}
          onEntityClick={handleEntityClick}
          variant="original"
        />
      </div>

      {/* Resizer */}
      <div
        className="w-1 cursor-col-resize bg-border hover:bg-accent"
        onMouseDown={handleResizerDrag}
        role="separator"
        aria-label="Изменить размер панелей"
      />

      {/* Right panel — anonymized text */}
      <div
        ref={rightRef}
        className="overflow-auto bg-bg-secondary p-6"
        style={{ width: `${(1 - splitRatio) * 100}%` }}
      >
        <EntityHighlighter
          text={anonymizedText}
          entities={entities}
          onEntityClick={handleEntityClick}
          variant="anonymized"
        />
      </div>

      {/* Popover */}
      {activeEntity && popoverPosition && (
        <EntityPopover
          entity={activeEntity}
          position={popoverPosition}
          onAction={(action, newValue) => {
            onEntityUpdate(activeEntity, action, newValue);
            setActiveEntity(null);
          }}
          onClose={() => setActiveEntity(null)}
        />
      )}
    </div>
  );
}
```

### EntityHighlighter компонент

```tsx
// frontend/src/components/EntityHighlighter.tsx
'use client';

import { useMemo } from 'react';
import { ENTITY_COLORS, type EntityType } from '@/lib/colors';
import { useTheme } from '@/hooks/useTheme';
import type { DetectedEntity } from '@/types/entities';

interface EntityHighlighterProps {
  text: string;
  entities: DetectedEntity[];
  onEntityClick: (entity: DetectedEntity, event: React.MouseEvent) => void;
  variant: 'original' | 'anonymized';
}

export function EntityHighlighter({ text, entities, onEntityClick, variant }: EntityHighlighterProps) {
  const { theme } = useTheme();

  // Сортируем сущности по позиции и строим сегменты текста
  const segments = useMemo(() => {
    const sorted = [...entities].sort((a, b) => a.start - b.start);
    const result: Array<{ text: string; entity?: DetectedEntity }> = [];
    let cursor = 0;

    for (const entity of sorted) {
      if (entity.start > cursor) {
        result.push({ text: text.slice(cursor, entity.start) });
      }
      const entityText = variant === 'original'
        ? text.slice(entity.start, entity.end)
        : entity.placeholder ?? `[${entity.entity_type}_?]`;
      result.push({ text: entityText, entity });
      cursor = entity.end;
    }
    if (cursor < text.length) {
      result.push({ text: text.slice(cursor) });
    }
    return result;
  }, [text, entities, variant]);

  return (
    <div className="font-serif text-base leading-relaxed whitespace-pre-wrap">
      {segments.map((seg, i) => {
        if (!seg.entity) {
          return <span key={i}>{seg.text}</span>;
        }
        const colors = ENTITY_COLORS[seg.entity.entity_type as EntityType];
        const bgColor = theme === 'dark' ? colors.dark : colors.light;
        return (
          <span
            key={i}
            onClick={(e) => onEntityClick(seg.entity!, e)}
            className="cursor-pointer rounded px-0.5 transition-colors hover:opacity-80"
            style={{ backgroundColor: bgColor }}
            title={`${colors.label} ${colors.icon}`}
            data-entity-type={seg.entity.entity_type}
          >
            {seg.text}
          </span>
        );
      })}
    </div>
  );
}
```

### EntityPopover

```tsx
// frontend/src/components/EntityPopover.tsx
'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { DetectedEntity } from '@/types/entities';

interface EntityPopoverProps {
  entity: DetectedEntity;
  position: { x: number; y: number };
  onAction: (action: 'accept' | 'reject' | 'edit', newValue?: string) => void;
  onClose: () => void;
}

export function EntityPopover({ entity, position, onAction, onClose }: EntityPopoverProps) {
  const { t } = useTranslation();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(entity.text);
  const ref = useRef<HTMLDivElement>(null);

  // Закрытие при клике вне попапа и Escape
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-50 rounded-lg border border-border bg-bg-elevated p-4 shadow-xl"
      style={{ left: position.x, top: position.y + 10 }}
      role="dialog"
    >
      <div className="mb-3">
        <div className="text-xs font-medium uppercase text-text-muted">
          {t(`entity.types.${entity.entity_type}`)}
        </div>
        {isEditing ? (
          <input
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            className="mt-1 w-full rounded border border-border bg-bg-primary p-1 text-sm"
            autoFocus
          />
        ) : (
          <div className="text-sm font-medium">{entity.text}</div>
        )}
        <div className="mt-1 text-xs text-text-muted">
          {t('entity.confidence')}: {Math.round(entity.score * 100)}%
        </div>
      </div>
      <div className="flex gap-2">
        {isEditing ? (
          <>
            <button
              onClick={() => onAction('edit', editValue)}
              className="rounded bg-accent px-3 py-1 text-xs text-white hover:bg-accent-dark"
            >
              {t('common.save')}
            </button>
            <button
              onClick={() => setIsEditing(false)}
              className="rounded border border-border px-3 py-1 text-xs hover:bg-bg-hover"
            >
              {t('common.cancel')}
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => onAction('accept')}
              className="rounded bg-success px-3 py-1 text-xs text-white"
              aria-label={t('entity.accept')}
            >
              ✅ {t('entity.accept')}
            </button>
            <button
              onClick={() => onAction('reject')}
              className="rounded bg-danger px-3 py-1 text-xs text-white"
              aria-label={t('entity.reject')}
            >
              ❌ {t('entity.reject')}
            </button>
            <button
              onClick={() => setIsEditing(true)}
              className="rounded border border-border px-3 py-1 text-xs hover:bg-bg-hover"
            >
              ✏️ {t('common.edit')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
```

### useSyncedScroll хук

```typescript
// frontend/src/hooks/useSyncedScroll.ts
import { useEffect, type RefObject } from 'react';

export function useSyncedScroll<T extends HTMLElement>(
  refA: RefObject<T>,
  refB: RefObject<T>
) {
  useEffect(() => {
    const a = refA.current;
    const b = refB.current;
    if (!a || !b) return;

    let isScrollingA = false;
    let isScrollingB = false;

    const handleScrollA = () => {
      if (isScrollingB) return;
      isScrollingA = true;
      const ratio = a.scrollTop / (a.scrollHeight - a.clientHeight);
      b.scrollTop = ratio * (b.scrollHeight - b.clientHeight);
      requestAnimationFrame(() => { isScrollingA = false; });
    };

    const handleScrollB = () => {
      if (isScrollingA) return;
      isScrollingB = true;
      const ratio = b.scrollTop / (b.scrollHeight - b.clientHeight);
      a.scrollTop = ratio * (a.scrollHeight - a.clientHeight);
      requestAnimationFrame(() => { isScrollingB = false; });
    };

    a.addEventListener('scroll', handleScrollA);
    b.addEventListener('scroll', handleScrollB);
    return () => {
      a.removeEventListener('scroll', handleScrollA);
      b.removeEventListener('scroll', handleScrollB);
    };
  }, [refA, refB]);
}
```

## Файлы для создания

```
frontend/src/components/SplitScreen.tsx
frontend/src/components/EntityHighlighter.tsx
frontend/src/components/EntityPopover.tsx
frontend/src/components/EntityNavigator.tsx
frontend/src/hooks/useSyncedScroll.ts
frontend/src/hooks/useEntityRegistry.ts
frontend/src/lib/colors.ts
frontend/src/types/entities.ts
frontend/src/components/__tests__/SplitScreen.test.tsx
frontend/src/components/__tests__/EntityHighlighter.test.tsx
```

## Тесты (Vitest + React Testing Library)

- `EntityHighlighter` корректно рендерит сегменты с подсветкой
- Клик по сущности вызывает `onEntityClick`
- Цвета меняются при смене темы
- `SplitScreen` синхронизирует прокрутку
- `EntityPopover` корректно обрабатывает accept/reject/edit
- `EntityPopover` закрывается по Escape и клику вне

## Acceptance Criteria

- [ ] Компоненты рендерятся без ошибок
- [ ] Сущности подсвечены правильными цветами для светлой и тёмной темы
- [ ] Синхронная прокрутка работает (Cypress smoke test или ручная проверка)
- [ ] Все интерактивные элементы доступны с клавиатуры
- [ ] WCAG AA (4.5:1) для всех цветовых комбинаций — проверить через axe-core
- [ ] Все строки локализованы через i18next
- [ ] Тесты проходят: `npm test`
- [ ] ESLint без ошибок
- [ ] TypeScript strict mode без ошибок

## Команды для запуска

```powershell
cd frontend
npm install
npm test
npm run lint
npm run tauri dev
```

## Коммит

```
feat(frontend): implement SplitScreen component with entity highlighting

- SplitScreen with synchronized scrolling between original and anonymized panels
- EntityHighlighter rendering text with color-coded entity highlights
- EntityPopover for accept/reject/edit actions on detected entities
- 8-color palette with light/dark theme variants (WCAG AA compliant)
- Resizable split with drag handle
- Keyboard navigation support

Closes task #5
```
