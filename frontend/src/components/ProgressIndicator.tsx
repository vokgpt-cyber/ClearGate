'use client';

/**
 * ProgressIndicator — Apple-style progress bar with status text.
 *
 * Shows a thin animated progress bar and status text when anonymization is in progress.
 * Cycles through stages: prep -> structured -> entities -> context -> done/error.
 * When the parent component sets a non-'prep' stage, that overrides the internal timer.
 */

import { useEffect, useState } from 'react';
import { useLocale } from '@/hooks/useLocale';

interface ProgressIndicatorProps {
  active: boolean;
  stage: 'idle' | 'prep' | 'structured' | 'entities' | 'context' | 'done' | 'error';
  entityCount?: number;
  deepScan?: boolean;
}

export function ProgressIndicator({
  active,
  stage,
  entityCount,
  deepScan,
}: ProgressIndicatorProps) {
  const { t } = useLocale();
  const [internalStage, setInternalStage] = useState<
    'idle' | 'prep' | 'structured' | 'entities' | 'context' | 'done' | 'error'
  >('idle');

  // When active and parent stage is 'prep', cycle through stages on a timer.
  // Otherwise, use the parent's stage.
  const displayStage = active && stage === 'prep' ? internalStage : stage;

  useEffect(() => {
    if (!active || stage !== 'prep') {
      setInternalStage('idle');
      return;
    }

    // Start from 'prep' if we just became active
    if (internalStage === 'idle') {
      setInternalStage('prep');
    }

    // Timers for stage transitions
    const timers: ReturnType<typeof setTimeout>[] = [];

    if (internalStage === 'prep') {
      timers.push(
        setTimeout(() => setInternalStage('structured'), 2000),
      );
    } else if (internalStage === 'structured') {
      timers.push(
        setTimeout(() => setInternalStage('entities'), 8000),
      );
    } else if (internalStage === 'entities' && deepScan) {
      timers.push(
        setTimeout(() => setInternalStage('context'), 25000),
      );
    }

    return () => {
      timers.forEach((t) => clearTimeout(t));
    };
  }, [active, stage, internalStage, deepScan]);

  if (!active || displayStage === 'idle') {
    return null;
  }

  const getStatusText = () => {
    switch (displayStage) {
      case 'prep':
        return t('progress.prep');
      case 'structured':
        return t('progress.structured');
      case 'entities':
        return t('progress.entities');
      case 'context':
        return t('progress.context');
      case 'done':
        return entityCount !== undefined
          ? t('progress.done').replace('{count}', String(entityCount))
          : t('progress.done');
      case 'error':
        return t('progress.error');
      default:
        return '';
    }
  };

  const isError = displayStage === 'error';

  return (
    <div className="cleargate-progress">
      <div className="cleargate-progress__bar">
        <div
          className={`cleargate-progress__bar-fill ${isError ? 'cleargate-progress__bar-fill--error' : ''}`}
        />
      </div>
      <div className={`cleargate-progress__status ${isError ? 'cleargate-progress__status--error' : ''}`}>
        {getStatusText()}
      </div>
    </div>
  );
}
