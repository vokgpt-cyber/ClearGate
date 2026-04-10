# Task 09: LLMPanel UI Component

## Контекст

После ревью анонимизации (Task 05) юрист настраивает запрос к LLM: выбирает провайдера, модель, уровень thinking, пишет промпт, видит оценку стоимости, отправляет. Это нижняя или правая панель главного экрана.

## Зависимости

- Task 05 (SplitScreen)
- Task 07 (Claude adapter — нужны model lists)
- Task 08 (WebSocket streaming)

## Цель

Создать `LLMPanel` компонент с выбором провайдера/модели/thinking, полем промпта, оценкой стоимости в реальном времени и кнопкой отправки с подтверждением.

## Требования

### Компоненты

1. **`LLMPanel.tsx`** — главный контейнер
2. **`ProviderSelector.tsx`** — три карточки провайдеров (Claude/GPT/Gemini)
3. **`ModelSelector.tsx`** — дропдаун моделей выбранного провайдера
4. **`ThinkingSlider.tsx`** — переключатель thinking level
5. **`PromptInput.tsx`** — textarea с предустановленными шаблонами
6. **`CostEstimator.tsx`** — оценка стоимости в реальном времени
7. **`SendButton.tsx`** — кнопка с confirmation dialog

### LLMPanel компонент

```tsx
// frontend/src/components/LLMPanel.tsx
'use client';

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ProviderSelector } from './ProviderSelector';
import { ModelSelector } from './ModelSelector';
import { ThinkingSlider } from './ThinkingSlider';
import { PromptInput } from './PromptInput';
import { CostEstimator } from './CostEstimator';
import { SendButton } from './SendButton';
import { useModelsList } from '@/hooks/useModelsList';
import { useCostEstimate } from '@/hooks/useCostEstimate';
import type { Provider, ThinkingLevel } from '@/types/llm';

interface LLMPanelProps {
  anonymizedText: string;
  onSend: (request: SendRequest) => void;
  disabled?: boolean;
}

interface SendRequest {
  provider: Provider;
  model: string;
  thinkingLevel: ThinkingLevel;
  prompt: string;
}

export function LLMPanel({ anonymizedText, onSend, disabled = false }: LLMPanelProps) {
  const { t } = useTranslation();
  const { models, loading } = useModelsList();

  const [provider, setProvider] = useState<Provider>('claude');
  const [model, setModel] = useState<string>('claude-opus-4-6');
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>('high');
  const [prompt, setPrompt] = useState('');

  // По умолчанию — топовая модель провайдера
  const providerModels = useMemo(
    () => models.filter((m) => m.provider === provider),
    [models, provider]
  );

  const handleProviderChange = (newProvider: Provider) => {
    setProvider(newProvider);
    const topModel = models.filter((m) => m.provider === newProvider)[0];
    if (topModel) setModel(topModel.id);
  };

  const { estimate, loading: estimating } = useCostEstimate({
    text: anonymizedText,
    prompt,
    provider,
    model,
    thinkingLevel,
  });

  const canSend = !disabled && prompt.trim().length > 0 && !loading;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-bg-elevated p-4">
      {/* Provider selector */}
      <div>
        <label className="mb-2 block text-xs font-medium uppercase text-text-muted">
          {t('llm.provider')}
        </label>
        <ProviderSelector value={provider} onChange={handleProviderChange} />
      </div>

      {/* Model selector */}
      <div>
        <label className="mb-2 block text-xs font-medium uppercase text-text-muted">
          {t('llm.model')}
        </label>
        <ModelSelector
          models={providerModels}
          value={model}
          onChange={setModel}
        />
      </div>

      {/* Thinking level */}
      <div>
        <label className="mb-2 block text-xs font-medium uppercase text-text-muted">
          {t('llm.thinking_level')}
        </label>
        <ThinkingSlider value={thinkingLevel} onChange={setThinkingLevel} />
      </div>

      {/* Prompt input */}
      <div>
        <label className="mb-2 block text-xs font-medium uppercase text-text-muted">
          {t('llm.prompt')}
        </label>
        <PromptInput value={prompt} onChange={setPrompt} />
      </div>

      {/* Cost estimate */}
      <CostEstimator estimate={estimate} loading={estimating} />

      {/* Send button */}
      <SendButton
        disabled={!canSend}
        onSend={() => onSend({ provider, model, thinkingLevel, prompt })}
        anonymizedTextLength={anonymizedText.length}
        cost={estimate?.total_cost_usd}
      />
    </div>
  );
}
```

### ProviderSelector

```tsx
// frontend/src/components/ProviderSelector.tsx
'use client';

import { useTranslation } from 'react-i18next';
import type { Provider } from '@/types/llm';

const PROVIDERS: { id: Provider; name: string; icon: string; description: string }[] = [
  { id: 'claude', name: 'Claude', icon: '🟠', description: 'Anthropic' },
  { id: 'openai', name: 'GPT', icon: '🟢', description: 'OpenAI' },
  { id: 'gemini', name: 'Gemini', icon: '🔵', description: 'Google' },
];

interface ProviderSelectorProps {
  value: Provider;
  onChange: (provider: Provider) => void;
}

export function ProviderSelector({ value, onChange }: ProviderSelectorProps) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {PROVIDERS.map((p) => (
        <button
          key={p.id}
          onClick={() => onChange(p.id)}
          className={`rounded-lg border p-3 text-left transition-all ${
            value === p.id
              ? 'border-accent bg-accent-soft ring-2 ring-accent'
              : 'border-border hover:bg-bg-hover'
          }`}
          aria-pressed={value === p.id}
        >
          <div className="text-2xl">{p.icon}</div>
          <div className="text-sm font-medium">{p.name}</div>
          <div className="text-xs text-text-muted">{p.description}</div>
        </button>
      ))}
    </div>
  );
}
```

### PromptInput с шаблонами

```tsx
// frontend/src/components/PromptInput.tsx
'use client';

import { useTranslation } from 'react-i18next';

const PRESET_PROMPTS = [
  { id: 'analyze_contract', labelKey: 'prompts.analyze_contract' },
  { id: 'find_risks', labelKey: 'prompts.find_risks' },
  { id: 'prepare_opinion', labelKey: 'prompts.prepare_opinion' },
  { id: 'answer_client', labelKey: 'prompts.answer_client' },
];

interface PromptInputProps {
  value: string;
  onChange: (value: string) => void;
}

export function PromptInput({ value, onChange }: PromptInputProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={6}
        placeholder={t('llm.prompt_placeholder')}
        className="w-full rounded-md border border-border bg-bg-primary p-3 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
      />
      <div className="flex flex-wrap gap-2">
        <span className="text-xs text-text-muted">{t('llm.templates')}:</span>
        {PRESET_PROMPTS.map((p) => (
          <button
            key={p.id}
            onClick={() => onChange(t(p.labelKey + '.text'))}
            className="rounded-full border border-border px-3 py-1 text-xs hover:bg-bg-hover"
          >
            {t(p.labelKey + '.title')}
          </button>
        ))}
      </div>
    </div>
  );
}
```

### CostEstimator

```tsx
// frontend/src/components/CostEstimator.tsx
'use client';

import { useTranslation } from 'react-i18next';
import type { CostEstimate } from '@/types/llm';

interface CostEstimatorProps {
  estimate: CostEstimate | null;
  loading: boolean;
}

export function CostEstimator({ estimate, loading }: CostEstimatorProps) {
  const { t } = useTranslation();

  if (loading) {
    return <div className="text-xs text-text-muted">{t('llm.estimating')}...</div>;
  }

  if (!estimate) return null;

  return (
    <div className="rounded-md border border-border bg-bg-primary p-3 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-medium">{t('llm.estimated_cost')}</span>
        <span className="text-lg font-bold text-accent">
          ${estimate.total_cost_usd.toFixed(4)}
        </span>
      </div>
      <div className="mt-2 space-y-1 text-text-muted">
        <div className="flex justify-between">
          <span>{t('llm.input_tokens')}</span>
          <span>~{estimate.input_tokens.toLocaleString()} → ${estimate.input_cost_usd.toFixed(4)}</span>
        </div>
        <div className="flex justify-between">
          <span>{t('llm.output_tokens')}</span>
          <span>~{estimate.estimated_output_tokens.toLocaleString()} → ${estimate.output_cost_usd.toFixed(4)}</span>
        </div>
        {estimate.estimated_thinking_tokens > 0 && (
          <div className="flex justify-between">
            <span>{t('llm.thinking_tokens')}</span>
            <span>~{estimate.estimated_thinking_tokens.toLocaleString()} → ${estimate.thinking_cost_usd.toFixed(4)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
```

### SendButton с confirmation

```tsx
// frontend/src/components/SendButton.tsx
'use client';

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface SendButtonProps {
  disabled: boolean;
  onSend: () => void;
  anonymizedTextLength: number;
  cost?: number;
}

export function SendButton({ disabled, onSend, anonymizedTextLength, cost }: SendButtonProps) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="rounded-md border border-warning bg-warning/10 p-3">
        <div className="mb-3 text-sm font-medium text-warning">
          ⚠️ {t('llm.confirm_send_title')}
        </div>
        <div className="mb-3 text-xs text-text-muted">
          {t('llm.confirm_send_message', {
            length: anonymizedTextLength,
            cost: cost?.toFixed(4) ?? '?',
          })}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => { onSend(); setConfirming(false); }}
            className="flex-1 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-dark"
          >
            {t('llm.confirm_send')}
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="rounded-md border border-border px-4 py-2 text-sm hover:bg-bg-hover"
          >
            {t('common.cancel')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      disabled={disabled}
      onClick={() => setConfirming(true)}
      className="w-full rounded-md bg-accent px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-dark disabled:cursor-not-allowed disabled:bg-bg-disabled disabled:text-text-disabled"
    >
      {t('llm.send_to_provider')}
    </button>
  );
}
```

## Файлы для создания

```
frontend/src/components/LLMPanel.tsx
frontend/src/components/ProviderSelector.tsx
frontend/src/components/ModelSelector.tsx
frontend/src/components/ThinkingSlider.tsx
frontend/src/components/PromptInput.tsx
frontend/src/components/CostEstimator.tsx
frontend/src/components/SendButton.tsx
frontend/src/hooks/useModelsList.ts
frontend/src/hooks/useCostEstimate.ts
frontend/src/types/llm.ts
frontend/src/components/__tests__/LLMPanel.test.tsx
```

## Тесты

- ProviderSelector корректно меняет состояние
- При смене провайдера автоматически выбирается топовая модель
- CostEstimator показывает «estimating» во время загрузки
- SendButton требует подтверждения перед вызовом onSend
- Все пресеты промптов вставляются корректно
- Все строки локализованы

## Acceptance Criteria

- [ ] LLMPanel рендерится с дефолтными значениями (Claude Opus 4.6, thinking high)
- [ ] Смена провайдера обновляет список моделей
- [ ] Cost estimate обновляется при изменении промпта (debounce 300ms)
- [ ] Confirmation dialog появляется перед отправкой
- [ ] Все строки локализованы (RU/EN)
- [ ] Выглядит корректно в светлой и тёмной теме
- [ ] Кнопка disabled пока не введён промпт
- [ ] Tests проходят
- [ ] ESLint и TypeScript strict без ошибок

## Команды

```powershell
cd frontend
npm test LLMPanel
npm run tauri dev
```

## Коммит

```
feat(frontend): implement LLMPanel for provider/model selection

- ProviderSelector with three cards (Claude/GPT/Gemini)
- ModelSelector with auto-selecting top model on provider change
- ThinkingSlider with 5 levels (off/low/medium/high/max)
- PromptInput with preset templates for legal tasks
- Real-time CostEstimator with debounced updates
- SendButton with confirmation dialog warning about cloud transmission
- Full i18n support (RU/EN)

Closes task #9
```
